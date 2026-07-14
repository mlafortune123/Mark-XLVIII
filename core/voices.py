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
