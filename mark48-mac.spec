# PyInstaller spec for MARK XLVIII on macOS — build with:
#   pyinstaller mark48-mac.spec
#
# Produces dist/MarkXLVIII.app, ready to be wrapped in a .dmg (see
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
        # config/certs/, or memory/long_term.json (personal, git-ignored data).
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
    name='MarkXLVIII',
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
    name='MarkXLVIII',
)

app = BUNDLE(
    coll,
    name='MarkXLVIII.app',
    icon='config/jarvis.icns',
    bundle_identifier='com.fatihmakes.markxlviii',
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
