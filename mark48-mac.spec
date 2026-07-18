# PyInstaller spec for JARVIS on macOS — build with:
#   pyinstaller mark48-mac.spec
#
# Produces dist/JARVIS.app, ready to be wrapped in a .dmg (see
# scripts/build_dmg.sh). Must be run on macOS.

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundled read-only resources — see mark48.spec (Windows) for the
        # same rationale. Do NOT add config/api_keys.json, config/preferences.json,
        # config/vault_path.json, config/certs/, or memory/long_term.json
        # (personal, git-ignored data). The Obsidian vault itself lives
        # outside the app entirely (default ~/Documents/JarvisVault) so it
        # never needs bundling or exclusion here.
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
        'faster_whisper', 'vosk', 'kokoro', 'torch', 'transformers',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='JARVIS',
)

app = BUNDLE(
    coll,
    name='JARVIS.app',
    icon='config/jarvis.icns',
    bundle_identifier='com.TechInATux.jarvis',
    info_plist={
        'CFBundleShortVersionString': '48.0.0',
        'NSMicrophoneUsageDescription':
            'JARVIS needs microphone access for real-time voice conversation.',
        'NSCameraUsageDescription':
            'JARVIS needs camera access so it can see and describe what the webcam sees.',
        'NSAppleEventsUsageDescription':
            'JARVIS controls volume, apps, and system settings via AppleScript.',
        'NSHighResolutionCapable': True,
        # Screen Recording (used for screen-vision capture) has no Info.plist
        # key — macOS prompts for it automatically on first use and the user
        # must approve it in System Settings > Privacy & Security, then
        # relaunch the app.
    },
)
