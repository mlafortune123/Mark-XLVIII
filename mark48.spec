# PyInstaller spec for JARVIS — build with:
#   pyinstaller mark48.spec
#
# Must be run on Windows (PyInstaller does not cross-compile).
# Produces a onedir build in dist/JARVIS/ ready to be wrapped by installer.iss.

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
        # config/preferences.json, config/vault_path.json, config/certs/,
        # or memory/long_term.json here — those are per-user data and must
        # not ship with the build (they're also git-ignored, so a CI
        # checkout won't have them). The Obsidian vault itself lives outside
        # the app entirely (default ~/Documents/JarvisVault) so it never
        # needs bundling or exclusion here.
        ('core/prompt.txt', 'core'),
        ('config/jarvis.ico', 'config'),
        # Pre-generated voice-preview clips (core/voice_preview.py) — the
        # gemini-2.5-flash-tts model this comes from caps free-tier accounts
        # at 10 requests/day, so these ship bundled instead of synthesizing
        # per click. Re-run scripts/generate_voice_previews.py before
        # cutting a release if this directory isn't all 30 voices yet.
        ('core/voice_previews', 'core/voice_previews'),
        # Avengeance font pack (core/fonts.py) — personal-use license file
        # (assets/fonts/avengeance/misc/) travels with it.
        ('assets/fonts/avengeance', 'assets/fonts/avengeance'),
        # HUD web assets (ui.py's QWebEngineView) — HTML/CSS/JS + vendored
        # jarvis-head.js, qwebchannel.js, and IBM Plex Mono woff2 files.
        ('ui_web', 'ui_web'),
    ],
    hiddenimports=[
        'PyQt6.sip',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebChannel',
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
    name='JARVIS',
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
    name='JARVIS',
    # Keep bundled files flat next to the exe (dist/JARVIS/core/...,
    # dist/JARVIS/config/...) instead of PyInstaller 6's default
    # _internal/ subfolder — the app's own path resolution
    # (Path(sys.executable).parent / "core" / "prompt.txt", etc.) assumes
    # a flat layout.
    contents_directory='.',
)
