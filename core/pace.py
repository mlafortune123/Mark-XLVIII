"""core/pace.py — shared list of speaking-pace options JARVIS's voice can be
set to.

Same mechanism as core/accents.py / core/styles.py: Gemini's prebuilt-voice
TTS has no structured speech-rate field, so `instruction` is natural-language
text embedded directly into prompts, not an API parameter.
"""

# (code, display_name, instruction) — `code` is what's stored in
# preferences.json. `instruction` is the natural-language pace directive
# embedded in prompts, or None for "no override, use the voice's default."
SUPPORTED_PACES = [
    ("default",   "Default (1x)", None),
    ("very_slow", "Very Slow",    "a very slow, deliberate pace"),
    ("slow",      "Slow",         "a slow, relaxed pace"),
    ("fast",      "Fast",         "a brisk, fast pace"),
    ("very_fast", "Very Fast",    "a very fast, rapid pace"),
]

DEFAULT_PACE = "default"

_BY_CODE = {code: (name, instr) for code, name, instr in SUPPORTED_PACES}


def pace_name(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[0] if entry else None


def pace_instruction(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[1] if entry else None


def resolve_pace(text: str) -> str | None:
    """Case-insensitive lookup by code or display name — returns the
    canonical code, or None if unrecognized."""
    if not text:
        return None
    t = text.strip().lower()
    for code, name, _instr in SUPPORTED_PACES:
        if t == code.lower() or t == name.lower():
            return code
    return None
