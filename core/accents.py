"""core/accents.py — shared list of accent options JARVIS's voice can be
locked to.

Gemini's speech APIs have no structured accent field — SpeechConfig/
VoiceConfig only expose voice_config/language_code/multi_speaker_voice_config
(confirmed against the installed SDK's model_fields). Google's own docs
confirm accent is controlled purely through natural-language prompt
instructions (e.g. "Accent: Southern California valley girl..."), so
`instruction` here is text meant to be embedded directly into a system
prompt (main.py, actions/screen_processor.py) or a one-shot TTS call's
`contents` (core/voice_preview.py), not an API parameter.

Single source of truth for the Preferences dropdown (ui.py), same pattern as
core/languages.py / core/voices.py.
"""

# (code, display_name, instruction) — `code` is what's stored in
# preferences.json. `instruction` is the natural-language accent directive
# embedded in prompts, or None for "no override, use the voice's default."
SUPPORTED_ACCENTS = [
    ("default",    "Default",    None),
    ("british",    "British",    "a British (Received Pronunciation) English accent"),
    ("american",   "American",   "a General American English accent"),
    ("australian", "Australian", "an Australian English accent"),
    ("indian",     "Indian",     "an Indian English accent"),
    ("irish",      "Irish",      "an Irish English accent"),
    ("scottish",   "Scottish",   "a Scottish English accent"),
]

DEFAULT_ACCENT = "default"

_BY_CODE = {code: (name, instr) for code, name, instr in SUPPORTED_ACCENTS}


def accent_name(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[0] if entry else None


def accent_instruction(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[1] if entry else None
