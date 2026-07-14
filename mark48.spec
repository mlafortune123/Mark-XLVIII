# PyInstaller spec for MARK XLVIII — build with:
#   pyinstaller mark48.spec
#
# Must be run on Windows (PyInstaller does not cross-compile).
# Produces a onedir build in dist/MarkXLVIII/ ready to be wrapped by installer.iss.

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundled read-only resources the app resolves relative to its own
        # install directory (see get_base_dir()/PROMPT_PATH in main.py and
        # the icon lookup in ui.py). Do NOT add config/api_keys.json,
        # config/preferences.json, config/certs/, or memory/long_term.json
        # here — those are per-user data and must not ship with the build
        # (they're also git-ignored, so a CI checkout won't have them).
        ('core/prompt.txt', 'core'),
        ('config/jarvis.ico', 'config'),
    ],
    hiddenimports=[
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Legacy/optional local STT/TTS engines not used by the default
        # config (voice runs through Gemini Live / OpenAI Realtime + edge-tts).
        # Skip if not installed rather than erroring the build.
        'faster_whisper', 'vosk', 'kokoro', 'torch', 'transformers',
        # browser_control.py degrades gracefully without this (see
        # actions/browser_control.py) — excluded to keep the build lean.
        'playwright',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MarkXLVIII',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='config/jarvis.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='MarkXLVIII',
    # Keep bundled files flat next to the exe (dist/MarkXLVIII/core/...,
    # dist/MarkXLVIII/config/...) instead of PyInstaller 6's default
    # _internal/ subfolder — the app's own path resolution
    # (Path(sys.executable).parent / "core" / "prompt.txt", etc.) assumes
    # a flat layout.
    contents_directory='.',
)
