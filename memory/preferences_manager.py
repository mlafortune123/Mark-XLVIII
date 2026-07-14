import json
from datetime import datetime

from memory.config_manager import CONFIG_DIR

PREFS_FILE = CONFIG_DIR / "preferences.json"

DEFAULT_PREFS = {
    "onboarded":        False,
    "startup_news":     True,
    "startup_weather":  False,
    "weather_city":     "",
    "followed_topics":  [],
    "topic_digest_last": "",
    "language":         "auto",
    "voice":            "Charon",
}


def load_preferences() -> dict:
    if not PREFS_FILE.exists():
        return dict(DEFAULT_PREFS)
    try:
        data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_PREFS)
        merged.update(data)
        return merged
    except Exception as e:
        print(f"[Preferences] ⚠️ Load error: {e}")
        return dict(DEFAULT_PREFS)


def save_preferences(update: dict) -> None:
    prefs = load_preferences()
    prefs.update(update)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(
        json.dumps(prefs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def complete_onboarding(update: dict) -> None:
    update = dict(update)
    update["onboarded"] = True
    save_preferences(update)


def is_onboarded() -> bool:
    return bool(load_preferences().get("onboarded", False))


def mark_topic_digest_sent(date_str: str | None = None) -> None:
    save_preferences({"topic_digest_last": date_str or datetime.now().strftime("%Y-%m-%d")})
