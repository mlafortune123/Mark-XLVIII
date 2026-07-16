"""core/styles.py — shared list of speaking-style options JARVIS's voice can
be set to.

Same mechanism as core/accents.py: Gemini's speech APIs have no structured
style field, so `instruction` is natural-language text embedded directly
into prompts (main.py, actions/screen_processor.py, core/voice_preview.py),
not an API parameter.
"""

# (code, display_name, instruction) — `code` is what's stored in
# preferences.json. `instruction` is the natural-language style directive
# embedded in prompts, or None for "no override, use the voice's default."
SUPPORTED_STYLES = [
    ("default",    "Default",    None),
    ("newscaster", "Newscaster", "a professional newscaster delivery style"),
    ("casual",     "Casual",     "a relaxed, casual conversational style"),
    ("cheerful",   "Cheerful",   "an upbeat, cheerful style"),
    ("calm",       "Calm",       "a calm, soothing style"),
    ("formal",     "Formal",     "a formal, professional style"),
]

DEFAULT_STYLE = "default"

_BY_CODE = {code: (name, instr) for code, name, instr in SUPPORTED_STYLES}


def style_name(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[0] if entry else None


def style_instruction(code: str) -> str | None:
    entry = _BY_CODE.get(code)
    return entry[1] if entry else None
