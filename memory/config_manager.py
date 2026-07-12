import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

PROVIDERS = ("gemini", "openai", "anthropic")

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def _write(data: dict) -> None:
    ensure_config_dir()
    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def save_api_keys(gemini_api_key: str) -> None:
    """Legacy single-key save. Kept for back-compat; delegates to save_api_key()."""
    save_api_key("gemini", gemini_api_key)

def save_api_key(provider: str, key: str) -> None:
    """provider in {'gemini', 'openai', 'anthropic'}."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r} (expected one of {PROVIDERS})")
    data = load_api_keys()
    data[f"{provider}_api_key"] = key.strip()
    _write(data)

def get_api_key(provider: str) -> str | None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r} (expected one of {PROVIDERS})")
    return load_api_keys().get(f"{provider}_api_key") or None

def get_gemini_key() -> str | None:
    return get_api_key("gemini")

def get_openai_key() -> str | None:
    return get_api_key("openai")

def get_anthropic_key() -> str | None:
    return get_api_key("anthropic")

def save_ai_provider(provider: str) -> None:
    """provider in {'gemini', 'openai', 'anthropic'} — the selected AI 'brain'."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r} (expected one of {PROVIDERS})")
    data = load_api_keys()
    data["ai_provider"] = provider
    _write(data)

def get_ai_provider() -> str:
    """Returns the selected AI 'brain' provider. Defaults to 'gemini' when unset
    (preserves current behavior for existing installs with no ai_provider key)."""
    raw = (load_api_keys().get("ai_provider") or "gemini").strip().lower()
    return raw if raw in PROVIDERS else "gemini"

def is_configured() -> bool:
    """
    The Gemini key is always required — voice falls back to Gemini's Live API
    whenever Claude is the selected brain provider (Claude has no realtime/voice
    API), and Gemini is also the default provider. If a non-Gemini provider is
    selected as the brain, that provider's key is required too.
    """
    gemini_key = get_gemini_key()
    if not (gemini_key and len(gemini_key) > 15):
        return False

    provider = get_ai_provider()
    if provider == "gemini":
        return True

    key = get_api_key(provider)
    return bool(key and len(key) > 15)
