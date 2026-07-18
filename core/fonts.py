"""core/fonts.py — custom Avengeance font families for ui.py.

Registers a small set of bundled font files with Qt's application font
database and exposes the resolved family names as module-level constants.
`load_fonts()` must be called after a QApplication instance exists (a Qt
requirement for QFontDatabase) — ui.py does this immediately after
constructing QApplication, before any widget is built.

Only three roles are used, deliberately not the whole Avengeance pack:
a big stylized "display" family for rare pure-branding text (the
"J.A.R.V.I.S" logo, the orb centerpiece, the phone-pairing code), and a
bold "header" family for structural chrome (section titles, buttons,
badges). Everything else in the UI (log panel, inputs, dense/small status
text) stays on the system monospace font — see Plans/avengeance-fonts.md
for the full per-widget rationale.

`_base_dir()` is duplicated locally rather than imported from main.py,
matching this repo's existing convention (see actions/screen_processor.py,
actions/reminder.py, etc.) — main.py imports ui.py, so ui.py/core modules
it uses can't import back from main.py without a cycle.
"""

import sys
from pathlib import Path

from PyQt6.QtGui import QFontDatabase


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_FONT_DIR = _base_dir() / "assets" / "fonts" / "avengeance"

_FILES = {
    "display":     "AvengeanceMightiestAvenger-837g.ttf",
    "header_bold": "AvengeanceHeroicAvengerBold-MM2J.ttf",
    "header":      "AvengeanceHeroicAvengerNormal-Bz7d.ttf",
}

# The rest of the pack — not wired into any role, only registered so the
# font-debug overlay (ui.py, Ctrl+Shift+F) can preview every available
# style, including ones nothing currently uses.
_EXTRA_FILES = {
    "base":          "Avengeance-YolO.ttf",
    "header_italic": "AvengeanceHeroicAvengerItalic-rRyy.ttf",
    "header_bold_italic": "AvengeanceHeroicAvengerBoldItalic-R73A.ttf",
}

# Fallbacks until load_fonts() runs (or if a file fails to load) — the app
# must never crash or look broken over a missing/corrupt font file.
DISPLAY_FAMILY = "Courier New"
HEADER_BOLD_FAMILY = "Courier New"
HEADER_FAMILY = "Courier New"

# (label, family) for every font registered — used only by the debug overlay.
ALL_FONTS: list[tuple[str, str]] = []

_loaded = False


def _register(role: str, filename: str, families: dict) -> None:
    path = _FONT_DIR / filename
    try:
        font_id = QFontDatabase.addApplicationFont(str(path))
        names = QFontDatabase.applicationFontFamilies(font_id)
        if names:
            families[role] = names[0]
        else:
            print(f"[fonts] ⚠️  Could not register font family from {path}")
    except Exception as e:
        print(f"[fonts] ⚠️  Failed to load {path}: {e}")


def load_fonts() -> None:
    """Register the bundled Avengeance fonts with Qt. Safe to call more
    than once (no-ops after the first successful run)."""
    global DISPLAY_FAMILY, HEADER_BOLD_FAMILY, HEADER_FAMILY, ALL_FONTS, _loaded
    if _loaded:
        return
    _loaded = True

    families = {}
    for role, filename in _FILES.items():
        _register(role, filename, families)
    for role, filename in _EXTRA_FILES.items():
        _register(role, filename, families)

    DISPLAY_FAMILY = families.get("display", DISPLAY_FAMILY)
    HEADER_BOLD_FAMILY = families.get("header_bold", HEADER_BOLD_FAMILY)
    HEADER_FAMILY = families.get("header", HEADER_FAMILY)

    ALL_FONTS = [
        (role, family)
        for role, family in families.items()
    ] + [("system_mono", "Courier New")]
