"""
core/cloud_llm.py — Unified cloud "brain" provider for JARVIS.

Single place that talks to the cloud Gemini, OpenAI, and Anthropic (Claude)
APIs for one-shot text/vision/audio-transcription calls used across
actions/*.py (planning, summarizing, code help, vision, search fallbacks…).

NOT to be confused with core/llm_client.py — that is a completely separate
subsystem for *local* inference (Ollama, or any local OpenAI-wire-compatible
server such as LM Studio/LocalAI/Jan). This module never touches that one.

The active provider and per-provider API keys are read from
config/api_keys.json via memory/config_manager.py.
"""
from __future__ import annotations

import base64
import io

from memory.config_manager import get_ai_provider, get_api_key


class CloudLLMError(RuntimeError):
    """Raised when a cloud provider call fails."""


class CloudLLMUnsupportedError(CloudLLMError):
    """Raised when the selected provider doesn't support the requested capability
    (e.g. audio transcription on Anthropic — the Messages API has no audio input)."""


# Per-role, per-provider model tiers. Mirrors the "cheap/fast vs quality"
# tiering the codebase already applied per-action with different Gemini
# model names.
#
# NOTE: OpenAI model IDs below should be re-verified against current OpenAI
# docs before/while relying on them — not verified live in this pass.
_MODELS = {
    "fast":    {"gemini": "gemini-2.5-flash-lite", "openai": "gpt-4.1-mini", "anthropic": "claude-haiku-4-5"},
    "default": {"gemini": "gemini-2.5-flash",       "openai": "gpt-4.1",     "anthropic": "claude-sonnet-5"},
    "quality": {"gemini": "gemini-2.5-flash",       "openai": "gpt-4.1",     "anthropic": "claude-opus-4-8"},
}

_clients: dict[str, object] = {}


def get_provider() -> str:
    """Returns 'gemini' | 'openai' | 'anthropic' — the currently selected AI brain."""
    return get_ai_provider()


def _model_for(provider: str, role: str) -> str:
    tier = _MODELS.get(role, _MODELS["default"])
    if provider not in tier:
        raise CloudLLMError(f"Unknown provider: {provider!r}")
    return tier[provider]


def _require_key(provider: str) -> str:
    key = get_api_key(provider)
    if not key:
        raise CloudLLMError(
            f"No API key configured for provider '{provider}'. "
            "Add it in the setup screen or config/api_keys.json."
        )
    return key


def _get_client(provider: str):
    """Memoized per-(provider, key) client so a changed key doesn't reuse a stale client."""
    key = _require_key(provider)
    cache_key = f"{provider}:{key}"
    if cache_key in _clients:
        return _clients[cache_key]

    if provider == "gemini":
        from google import genai
        client = genai.Client(api_key=key)
    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=key)
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    else:
        raise CloudLLMError(f"Unknown provider: {provider!r}")

    _clients[cache_key] = client
    return client


# ── Text ─────────────────────────────────────────────────────────────────────

def generate_text(
    prompt: str,
    system: str | None = None,
    role: str = "default",
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    provider = get_provider()
    m = model or _model_for(provider, role)
    try:
        if provider == "gemini":
            return _gemini_text(prompt, system, m)
        if provider == "openai":
            return _openai_text(prompt, system, m, max_tokens)
        if provider == "anthropic":
            return _anthropic_text(prompt, system, m, max_tokens)
    except CloudLLMError:
        raise
    except Exception as e:
        raise CloudLLMError(f"{provider} generate_text failed: {e}") from e
    raise CloudLLMError(f"Unknown provider: {provider!r}")


def _gemini_text(prompt: str, system: str | None, model: str) -> str:
    from google.genai import types as gtypes
    client = _get_client("gemini")
    config = gtypes.GenerateContentConfig(system_instruction=system) if system else None
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return (response.text or "").strip()


def _openai_text(prompt: str, system: str | None, model: str, max_tokens: int) -> str:
    client = _get_client("openai")
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
    return (response.choices[0].message.content or "").strip()


def _anthropic_text(prompt: str, system: str | None, model: str, max_tokens: int) -> str:
    client = _get_client("anthropic")
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return "".join(b.text for b in response.content if b.type == "text").strip()


# ── Vision ───────────────────────────────────────────────────────────────────

def generate_vision(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    system: str | None = None,
    role: str = "default",
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    provider = get_provider()
    m = model or _model_for(provider, role)
    try:
        if provider == "gemini":
            return _gemini_vision(prompt, image_bytes, mime_type, system, m)
        if provider == "openai":
            return _openai_vision(prompt, image_bytes, mime_type, system, m, max_tokens)
        if provider == "anthropic":
            return _anthropic_vision(prompt, image_bytes, mime_type, system, m, max_tokens)
    except CloudLLMError:
        raise
    except Exception as e:
        raise CloudLLMError(f"{provider} generate_vision failed: {e}") from e
    raise CloudLLMError(f"Unknown provider: {provider!r}")


def _gemini_vision(prompt: str, image_bytes: bytes, mime_type: str, system: str | None, model: str) -> str:
    from google.genai import types as gtypes
    client = _get_client("gemini")
    config = gtypes.GenerateContentConfig(system_instruction=system) if system else None
    response = client.models.generate_content(
        model=model,
        contents=[gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
        config=config,
    )
    return (response.text or "").strip()


def _openai_vision(
    prompt: str, image_bytes: bytes, mime_type: str, system: str | None, model: str, max_tokens: int
) -> str:
    client = _get_client("openai")
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ],
    })
    response = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
    return (response.choices[0].message.content or "").strip()


def _anthropic_vision(
    prompt: str, image_bytes: bytes, mime_type: str, system: str | None, model: str, max_tokens: int
) -> str:
    client = _get_client("anthropic")
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return "".join(b.text for b in response.content if b.type == "text").strip()


# ── Audio transcription ─────────────────────────────────────────────────────

def generate_audio_transcript(
    prompt: str,
    audio_bytes: bytes,
    mime_type: str,
    role: str = "default",
) -> str:
    provider = get_provider()
    if provider == "anthropic":
        raise CloudLLMUnsupportedError(
            "Audio transcription isn't available with Claude — Anthropic's API has no "
            "audio input support. Switch the AI provider to Gemini or OpenAI for this."
        )
    try:
        if provider == "gemini":
            return _gemini_audio(prompt, audio_bytes, mime_type, role)
        if provider == "openai":
            return _openai_audio(prompt, audio_bytes, mime_type)
    except CloudLLMError:
        raise
    except Exception as e:
        raise CloudLLMError(f"{provider} generate_audio_transcript failed: {e}") from e
    raise CloudLLMError(f"Unknown provider: {provider!r}")


def _gemini_audio(prompt: str, audio_bytes: bytes, mime_type: str, role: str) -> str:
    client = _get_client("gemini")
    model = _model_for("gemini", role)
    response = client.models.generate_content(
        model=model,
        contents=[prompt, {"mime_type": mime_type, "data": audio_bytes}],
    )
    return (response.text or "").strip()


def _openai_audio(prompt: str, audio_bytes: bytes, mime_type: str) -> str:
    client = _get_client("openai")
    ext = mime_type.split("/")[-1] if "/" in mime_type else "wav"
    buf = io.BytesIO(audio_bytes)
    buf.name = f"audio.{ext}"
    transcript = client.audio.transcriptions.create(model="whisper-1", file=buf)
    text = (transcript.text or "").strip()

    # If the prompt asks for more than a bare transcript (e.g. "summarize this
    # audio"), run the transcript through a follow-up text call.
    if prompt and "transcribe" not in prompt.lower():
        return generate_text(f"{prompt}\n\nTranscript:\n{text}", role="default")
    return text
