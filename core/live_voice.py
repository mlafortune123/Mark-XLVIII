"""
core/live_voice.py — Provider-neutral real-time voice session abstraction.

JARVIS's voice loop originally talked directly to Gemini's Live API
(google-genai's `client.aio.live.connect(...)`). This module defines a
provider-neutral interface, `LiveVoiceSession`, plus two implementations:

  GeminiLiveSession      — mechanical extraction of the existing, already-
                            working Gemini Live API code from main.py.
  OpenAIRealtimeSession  — new backend using OpenAI's Realtime API
                            (client.realtime.connect(model=...)).

Claude has no realtime/voice API, so there is no AnthropicLiveSession — when
Claude is the selected "brain" provider, callers should fall back to
GeminiLiveSession for voice (see main.py's provider switch).

Both sessions:
  - stream microphone audio in and speaker audio out via `sounddevice`
  - surface user/assistant transcripts through callbacks
  - dispatch tool calls through a single provider-neutral `tool_dispatch`
    callback (async, `(name: str, args: dict) -> str`), so the actual
    open_app/web_search/etc. business logic is written once in main.py and
    reused by both backends
  - support `send_text()` for injecting an invisible context turn — the
    mechanism actions/proactive.py and actions/system_monitor.py rely on to
    nudge JARVIS without a literal user utterance

KNOWN GAP: the screen-share "vision injection" feature (main.py's
_pending_vision / camera-close-timing state machine, driven by
actions/screen_processor.py) is NOT YET wired through this abstraction — it
remains Gemini-specific, driven directly against the raw Gemini session via
`GeminiLiveSession.raw_session`. Porting it to OpenAI's Realtime API is a
follow-up task, not attempted in this pass.

VERIFICATION NOTE (OpenAIRealtimeSession): built from OpenAI's current
published documentation (client.realtime.connect(model="gpt-realtime-2.1"),
session.update/conversation.item.create/response.create client events;
response.output_audio.delta / response.output_audio_transcript.delta /
response.function_call_arguments.delta / response.done server events). This
has NOT been exercised against a live OpenAI account — per the project plan,
budget real testing time here before relying on it in production, and expect
to need small fixes once run against a real key (event field names in
particular).
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import threading
import time
import traceback
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

import sounddevice as sd

from core.tool_schema import gemini_tools_to_openai_realtime

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)


def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

ToolDispatch = Callable[[str, dict], Awaitable[str]]
StateCallback = Callable[[str], None]
TextCallback = Callable[[str], None]
VoidCallback = Callable[[], None]


def _noop(*_a, **_kw) -> None:
    return None


class LiveVoiceSession(ABC):
    """Provider-neutral real-time voice session. Each subclass owns its full
    connect -> stream audio -> dispatch tool calls -> disconnect lifecycle."""

    def __init__(
        self,
        *,
        api_key: str,
        system_prompt: str,
        tool_declarations: list[dict],
        tool_dispatch: ToolDispatch,
        send_sample_rate: int,
        receive_sample_rate: int,
        channels: int = 1,
        chunk_size: int = 1024,
        on_state: StateCallback | None = None,
        on_user_transcript: TextCallback | None = None,
        on_assistant_transcript: TextCallback | None = None,
        on_connected: VoidCallback | None = None,
        on_turn_complete: Callable[[], Awaitable[None]] | None = None,
        is_muted: Callable[[], bool] | None = None,
        language_code: str | None = None,
        voice_name: str | None = None,
    ):
        self.api_key             = api_key
        self.system_prompt       = system_prompt
        # BCP-47 locale (e.g. "tr-TR") to pin the voice's output language to,
        # or None for auto-detect. Currently only consumed by GeminiLiveSession
        # (Gemini's SpeechConfig.language_code) — OpenAI's Realtime API has no
        # equivalent field, so it relies on the system_prompt-level override.
        self.language_code       = language_code
        # Gemini prebuilt voice name (e.g. "Charon"). Only consumed by
        # GeminiLiveSession — OpenAI's Realtime API has its own separate voice
        # roster and isn't wired to this preference.
        self.voice_name          = voice_name
        self.tool_declarations   = tool_declarations
        self.tool_dispatch       = tool_dispatch
        self.send_sample_rate    = send_sample_rate
        self.receive_sample_rate = receive_sample_rate
        self.channels            = channels
        self.chunk_size          = chunk_size

        self.on_state                = on_state or _noop
        self.on_user_transcript      = on_user_transcript or _noop
        self.on_assistant_transcript = on_assistant_transcript or _noop
        self.on_connected            = on_connected or _noop
        # Fired after each completed turn (transcripts already delivered) —
        # used by main.py to drive the Gemini-only screen-share vision
        # injection. A no-op on backends that don't call it (e.g. OpenAI).
        self.on_turn_complete_hook   = on_turn_complete
        self.is_muted                = is_muted or (lambda: False)

        self._is_speaking   = False
        # threading.Lock (not asyncio.Lock): _is_speaking is read from the
        # sounddevice InputStream callback, which runs on its own OS thread,
        # not the asyncio event loop thread.
        self._speaking_lock = threading.Lock()
        self._interrupted   = False

    def is_speaking(self) -> bool:
        with self._speaking_lock:
            return self._is_speaking

    @abstractmethod
    async def run(self) -> None:
        """Connects and runs the full session lifecycle until cancelled or the
        connection drops. Raises on unrecoverable errors so the caller's
        reconnect loop can retry."""

    @abstractmethod
    async def send_text(self, text: str, turn_complete: bool = True) -> None:
        """Injects a text turn — used for user text-command input, JARVIS's
        own speak() calls, and the proactive engine / system monitor's
        'inject invisible context, model may or may not respond' pattern."""

    @abstractmethod
    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """Pushes a raw PCM audio chunk (e.g. relayed from the phone-mic
        dashboard feature) into the session's outbound audio stream."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Stops the current spoken response immediately and re-opens the mic."""

    def set_speaking(self, value: bool) -> None:
        with self._speaking_lock:
            self._is_speaking = value
        self.on_state("SPEAKING" if value else ("LISTENING" if not self.is_muted() else "SLEEPING"))


# ── Gemini backend ───────────────────────────────────────────────────────────

class GeminiLiveSession(LiveVoiceSession):
    """Wraps google-genai's Live API. This is a refactor of the pre-existing,
    already-working logic that used to live directly in main.py's JarvisLive —
    behavior is intended to be unchanged, just reorganized behind the
    provider-neutral interface."""

    LIVE_MODEL = "gemini-3.1-flash-live-preview"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_session = None          # the underlying google.genai live session, once connected
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None
        self._turn_done_event: asyncio.Event | None = None

    def _build_config(self):
        from google.genai import types
        from core.voices import DEFAULT_VOICE

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=self.system_prompt,
            tools=[{"function_declarations": self.tool_declarations}],
            session_resumption=types.SessionResumptionConfig(),
            # Without this, the model can default to "thinking" on a turn and
            # return only text/thought parts with zero audio — reproduced
            # directly against this exact model: a plain text turn came back
            # audio-less until thinking was disabled. budget=0 forces it
            # straight to the AUDIO response every turn actually needs.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            # gemini-3.1-flash-live-preview: send_client_content() 1007s
            # unless this is set — confirmed empirically it is NOT actually
            # limited to a single "initial" call despite the docs' wording;
            # repeated send_client_content() calls across a session all
            # succeed as long as this is set AND each turns dict includes
            # role="user" (omitting role also 1007s, even with this set).
            history_config=types.HistoryConfig(initial_history_in_client_content=True),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name or DEFAULT_VOICE
                    )
                ),
                language_code=self.language_code,
            ),
        )

    async def send_text(self, text: str, turn_complete: bool = True) -> None:
        if not self.raw_session:
            return
        # role="user" is required on gemini-3.1-flash-live-preview (see
        # history_config note in _build_config()) — omitting it 1007s even
        # though the 2.5 model never needed it.
        await self.raw_session.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]},
            turn_complete=turn_complete,
        )

    async def send_image_turn(self, image_bytes: bytes, mime_type: str, text: str) -> None:
        """Gemini-specific: used by the screen-share vision feature."""
        if not self.raw_session:
            return
        b64 = base64.b64encode(image_bytes).decode("ascii")
        # NOTE: send_realtime_input(video=...) was tried first (it's the
        # "documented" replacement for image content) but empirically does
        # NOT deliver the image to the model — verified with solid-color
        # test images (256x256 green/blue/yellow), which came back as
        # "black"/"white"/wrong colors via video=, but correctly identified
        # every time via this send_client_content() + role="user" path
        # (also requires history_config, see _build_config()).
        await self.raw_session.send_client_content(
            turns={"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_type, "data": b64}},
                {"text": text},
            ]},
            turn_complete=True,
        )

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        if self.out_queue is not None:
            try:
                self.out_queue.put_nowait({"data": pcm_bytes, "mime_type": "audio/pcm"})
            except asyncio.QueueFull:
                pass

    async def interrupt(self) -> None:
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            while True:
                try:
                    q.get_nowait()
                except Exception:
                    break
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()

    async def run(self) -> None:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key, http_options={"api_version": "v1beta"})
        config = self._build_config()

        async with (
            client.aio.live.connect(model=self.LIVE_MODEL, config=config) as session,
            asyncio.TaskGroup() as tg,
        ):
            self.raw_session      = session
            self.audio_in_queue   = asyncio.Queue()
            self.out_queue        = asyncio.Queue(maxsize=200)
            self._turn_done_event = asyncio.Event()

            self.on_connected()
            self.on_state("LISTENING")

            tg.create_task(self._send_realtime())
            tg.create_task(self._listen_audio())
            tg.create_task(self._receive_audio())
            tg.create_task(self._play_audio())

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            # gemini-3.1-flash-live-preview: send_realtime_input(media=...)
            # ("media_chunks") is deprecated server-side and hard-closes the
            # socket with a 1007 — use the explicit audio= kwarg instead.
            await self.raw_session.send_realtime_input(audio=msg)

    async def _listen_audio(self):
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            if not self.is_speaking() and not self.is_muted():
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"},
                )

        with sd.InputStream(
            samplerate=self.send_sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_size,
            callback=callback,
        ):
            while True:
                await asyncio.sleep(0.1)

    async def _receive_audio(self):
        from google.genai import types

        out_buf, in_buf = [], []

        while True:
            async for response in self.raw_session.receive():

                if response.data:
                    if self._interrupted:
                        pass
                    else:
                        if self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        _SLICE = 2400  # ~50ms at 24kHz/16-bit mono — keeps interrupt() responsive
                        data = response.data
                        for i in range(0, len(data), _SLICE):
                            self.audio_in_queue.put_nowait(data[i:i + _SLICE])

                if response.server_content:
                    sc = response.server_content

                    if sc.output_transcription and sc.output_transcription.text:
                        txt = _clean_transcript(sc.output_transcription.text)
                        if txt and txt != (out_buf[-1] if out_buf else ""):
                            out_buf.append(txt)

                    if sc.input_transcription and sc.input_transcription.text:
                        txt = _clean_transcript(sc.input_transcription.text)
                        if txt:
                            in_buf.append(txt)

                    if sc.turn_complete:
                        self._turn_done_event.set()

                        if self._interrupted:
                            self._interrupted = False
                            in_buf, out_buf = [], []
                            continue

                        full_in = " ".join(in_buf).strip()
                        if full_in:
                            self.on_user_transcript(full_in)
                        in_buf = []

                        full_out = " ".join(out_buf).strip()
                        if full_out:
                            self.on_assistant_transcript(full_out)
                        out_buf = []

                        if self.on_turn_complete_hook:
                            await self.on_turn_complete_hook()

                if response.tool_call:
                    fn_responses = []
                    for fc in response.tool_call.function_calls:
                        args = dict(fc.args or {})
                        try:
                            result = await self.tool_dispatch(fc.name, args)
                        except Exception as e:
                            result = f"Tool '{fc.name}' failed: {e}"
                            traceback.print_exc()
                        fn_responses.append(
                            types.FunctionResponse(id=fc.id, name=fc.name, response={"result": result})
                        )
                    await self.raw_session.send_tool_response(function_responses=fn_responses)

    async def _play_audio(self):
        stream = sd.RawOutputStream(
            samplerate=self.receive_sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_size,
        )
        stream.start()

        while True:
            try:
                chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if self._turn_done_event.is_set() and self.audio_in_queue.empty():
                    self.set_speaking(False)
                    self._turn_done_event.clear()
                continue
            self.set_speaking(True)
            try:
                await asyncio.to_thread(stream.write, chunk)
            except (RuntimeError, asyncio.CancelledError):
                break


# ── OpenAI Realtime backend ──────────────────────────────────────────────────

class OpenAIRealtimeSession(LiveVoiceSession):
    """Wraps OpenAI's Realtime API (client.realtime.connect). See the module
    docstring's VERIFICATION NOTE — this has not been exercised against a live
    OpenAI account yet."""

    MODEL = "gpt-realtime-2.1"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connection = None
        self._out_queue: asyncio.Queue | None = None
        self._audio_in_queue: asyncio.Queue = asyncio.Queue()
        self._turn_done_event: asyncio.Event | None = None

    async def send_text(self, text: str, turn_complete: bool = True) -> None:
        if not self._connection:
            return
        await self._connection.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        )
        if turn_complete:
            await self._connection.response.create()

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        if self._out_queue is not None:
            try:
                self._out_queue.put_nowait(pcm_bytes)
            except asyncio.QueueFull:
                pass

    async def interrupt(self) -> None:
        self._interrupted = True
        if self._connection:
            try:
                await self._connection.response.cancel()
            except Exception:
                pass
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()

    async def run(self) -> None:
        from openai import AsyncOpenAI
        from core.voices import DEFAULT_OPENAI_VOICE, is_valid_openai_voice

        client = AsyncOpenAI(api_key=self.api_key)
        tools  = gemini_tools_to_openai_realtime(self.tool_declarations)

        # self.voice_name may still hold a Gemini voice name (e.g. "Charon")
        # if it was picked before switching providers — fall back rather
        # than send OpenAI an invalid voice ID.
        voice = self.voice_name if is_valid_openai_voice(self.voice_name or "") else DEFAULT_OPENAI_VOICE

        async with client.realtime.connect(model=self.MODEL) as connection:
            self._connection      = connection
            self._out_queue       = asyncio.Queue(maxsize=200)
            self._turn_done_event = asyncio.Event()

            await connection.session.update(session={
                "type": "realtime",
                "instructions": self.system_prompt,
                "tools": tools,
                "tool_choice": "auto",
                "audio": {
                    "input":  {"format": {"type": "audio/pcm", "rate": self.send_sample_rate}},
                    "output": {"format": {"type": "audio/pcm", "rate": self.receive_sample_rate}, "voice": voice},
                },
            })

            self.on_connected()
            self.on_state("LISTENING")

            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._send_realtime())
                tg.create_task(self._listen_audio())
                tg.create_task(self._receive_events())
                tg.create_task(self._play_audio())

    async def _send_realtime(self):
        while True:
            pcm_bytes = await self._out_queue.get()
            b64 = base64.b64encode(pcm_bytes).decode("ascii")
            await self._connection.input_audio_buffer.append(audio=b64)

    async def _listen_audio(self):
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            if not self.is_speaking() and not self.is_muted():
                data = indata.tobytes()
                loop.call_soon_threadsafe(self._out_queue.put_nowait, data)

        with sd.InputStream(
            samplerate=self.send_sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_size,
            callback=callback,
        ):
            while True:
                await asyncio.sleep(0.1)

    async def _receive_events(self):
        audio_in_queue = self._audio_in_queue

        out_transcript = ""
        in_transcript  = ""

        async for event in self._connection:
            etype = getattr(event, "type", "")

            if etype == "response.output_audio.delta":
                if not self._interrupted:
                    chunk = base64.b64decode(event.delta)
                    audio_in_queue.put_nowait(chunk)

            elif etype == "response.output_audio_transcript.delta":
                out_transcript += getattr(event, "delta", "") or ""

            elif etype == "conversation.item.input_audio_transcription.delta":
                in_transcript += getattr(event, "delta", "") or ""

            elif etype == "response.done":
                self._turn_done_event.set()

                if self._interrupted:
                    self._interrupted = False
                    in_transcript = out_transcript = ""
                else:
                    if in_transcript.strip():
                        self.on_user_transcript(in_transcript.strip())
                    if out_transcript.strip():
                        self.on_assistant_transcript(out_transcript.strip())
                in_transcript = out_transcript = ""

                # Tool calls surface in the completed response's output items.
                response_obj = getattr(event, "response", None)
                output_items = getattr(response_obj, "output", None) or []
                for item in output_items:
                    if getattr(item, "type", "") != "function_call":
                        continue
                    name    = getattr(item, "name", "")
                    call_id = getattr(item, "call_id", "")
                    raw_args = getattr(item, "arguments", "{}") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}

                    try:
                        result = await self.tool_dispatch(name, args)
                    except Exception as e:
                        result = f"Tool '{name}' failed: {e}"
                        traceback.print_exc()

                    await self._connection.conversation.item.create(item={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"result": result}),
                    })

                if output_items and any(getattr(i, "type", "") == "function_call" for i in output_items):
                    await self._connection.response.create()

            elif etype == "error":
                err = getattr(event, "error", None)
                print(f"[OpenAIRealtime] error: {getattr(err, 'message', event)}")

    async def _play_audio(self):
        audio_in_queue = self._audio_in_queue

        stream = sd.RawOutputStream(
            samplerate=self.receive_sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_size,
        )
        stream.start()

        while True:
            try:
                chunk = await asyncio.wait_for(audio_in_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if self._turn_done_event.is_set() and audio_in_queue.empty():
                    self.set_speaking(False)
                    self._turn_done_event.clear()
                continue
            self.set_speaking(True)
            try:
                await asyncio.to_thread(stream.write, chunk)
            except (RuntimeError, asyncio.CancelledError):
                break
