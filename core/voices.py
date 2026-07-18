"""core/voices.py — shared list of Gemini prebuilt voices JARVIS's Live API
sessions can speak with.

Single source of truth for the Preferences dropdown (ui.py) and the
GeminiLiveSession voice_config lock (main.py, core/live_voice.py,
actions/screen_processor.py).

Source: Gemini API TTS voice list — https://ai.google.dev/gemini-api/docs/generate-content/speech-generation
"""

DEFAULT_VOICE = "Charon"

# (voice_name, style_descriptor) — voice_name is stored in preferences.json
# verbatim and passed straight through to PrebuiltVoiceConfig.voice_name.
SUPPORTED_VOICES = [
    ("Zephyr",        "Bright"),
    ("Puck",          "Upbeat"),
    ("Charon",        "Informative"),
    ("Kore",          "Firm"),
    ("Fenrir",        "Excitable"),
    ("Leda",          "Youthful"),
    ("Orus",          "Firm"),
    ("Aoede",         "Breezy"),
    ("Callirrhoe",    "Easy-going"),
    ("Autonoe",       "Bright"),
    ("Enceladus",     "Breathy"),
    ("Iapetus",       "Clear"),
    ("Umbriel",       "Easy-going"),
    ("Algieba",       "Smooth"),
    ("Despina",       "Smooth"),
    ("Erinome",       "Clear"),
    ("Algenib",       "Gravelly"),
    ("Rasalgethi",    "Informative"),
    ("Laomedeia",     "Upbeat"),
    ("Achernar",      "Soft"),
    ("Alnilam",       "Firm"),
    ("Schedar",       "Even"),
    ("Gacrux",        "Mature"),
    ("Pulcherrima",   "Forward"),
    ("Achird",        "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix",  "Gentle"),
    ("Sadachbia",     "Lively"),
    ("Sadaltager",    "Knowledgeable"),
    ("Sulafat",       "Warm"),
]

_NAMES = {name for name, _style in SUPPORTED_VOICES}


def is_valid_voice(name: str) -> bool:
    return name in _NAMES


def resolve_voice_name(name: str) -> str | None:
    """Case-insensitive lookup — returns the canonical catalog name (correct
    TitleCase) for a voice, or None if it isn't a recognized Gemini voice.
    Used by the change_voice tool, since LLM-supplied text won't reliably
    match the catalog's exact casing."""
    if not name:
        return None
    lname = name.strip().lower()
    for n in _NAMES:
        if n.lower() == lname:
            return n
    return None


# ── OpenAI Realtime voice catalog ────────────────────────────────────────────
# Source: OpenAI's gpt-realtime voice list (marin/cedar are the newest,
# OpenAI-recommended pair; the rest are the legacy eight). These names are
# NOT interchangeable with the Gemini voice names above — Gemini and OpenAI
# each have their own catalog, so callers must pick the right list for the
# active provider (see core.cloud_llm.get_provider()).
DEFAULT_OPENAI_VOICE = "marin"

OPENAI_VOICES = [
    ("marin",   "Newest — recommended"),
    ("cedar",   "Newest — recommended"),
    ("alloy",   "Neutral"),
    ("ash",     "Clear"),
    ("ballad",  "Melodic"),
    ("coral",   "Warm"),
    ("echo",    "Deep"),
    ("sage",    "Calm"),
    ("shimmer", "Bright"),
    ("verse",   "Expressive"),
]

_OPENAI_NAMES = {name for name, _style in OPENAI_VOICES}


def is_valid_openai_voice(name: str) -> bool:
    return name in _OPENAI_NAMES
