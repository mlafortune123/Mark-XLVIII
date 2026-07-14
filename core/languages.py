"""core/languages.py — shared list of languages JARVIS's voice can be locked to.

Single source of truth for the Preferences dropdown (ui.py) and the
system-prompt override / Gemini Live SpeechConfig lock (main.py,
core/live_voice.py).
"""

# (code, display_name, gemini_locale) — `code` is what's stored in preferences.json.
# `gemini_locale` is the BCP-47 code passed to google.genai.types.SpeechConfig.
SUPPORTED_LANGUAGES = [
    ("auto", "Auto-detect",       None),
    ("en",   "English",           "en-US"),
    ("tr",   "Turkish",           "tr-TR"),
    ("es",   "Spanish",           "es-US"),
    ("fr",   "French",            "fr-FR"),
    ("de",   "German",            "de-DE"),
    ("pt",   "Portuguese",        "pt-BR"),
    ("it",   "Italian",           "it-IT"),
    ("ja",   "Japanese",          "ja-JP"),
    ("ko",   "Korean",            "ko-KR"),
    ("zh",   "Mandarin Chinese",  "cmn-CN"),
    ("ar",   "Arabic",            "ar-XA"),
    ("ru",   "Russian",           "ru-RU"),
    ("hi",   "Hindi",             "hi-IN"),
    ("nl",   "Dutch",             "nl-NL"),
]

_BY_CODE = {code: (name, locale) for code, name, locale in SUPPORTED_LANGUAGES}


def language_name(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[0] if entry else None


def language_locale(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[1] if entry else None
