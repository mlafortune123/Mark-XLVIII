"""core/fonts.py — font-family constants for ui.py.

The app previously bundled a custom "Avengeance" font pack for headers/
display text. That's been removed in favor of the platform's default UI
font everywhere (see Plans/avengeance-fonts.md for the original rationale
and Plans/remove-avengeance-fonts.md for why it was reverted) — these
constants now just resolve to Qt's default application font family so
`ui.py`'s existing `QFont(jfonts.DISPLAY_FAMILY, size, ...)` call sites
don't need to change one-by-one.

`load_fonts()` is kept as a no-op entry point (still called once from
`ui.py` after the `QApplication` is constructed) so call sites and
packaging don't need to change if a custom font is ever reintroduced.
"""

# Empty string tells Qt's font matcher to use the default application/
# system font rather than a specific family — this is the "use the
# default font" behavior requested in place of the old bundled pack.
DISPLAY_FAMILY = ""
HEADER_BOLD_FAMILY = ""
HEADER_FAMILY = ""

_loaded = False


def load_fonts() -> None:
    """No-op (kept for call-site compatibility). Previously registered the
    bundled Avengeance font files with Qt; the app now uses the default
    system font everywhere, so there's nothing to register."""
    global _loaded
    _loaded = True
