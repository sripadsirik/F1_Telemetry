# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Marco — F1 25 Race Engineer
#
# Build steps (run from repo root):
#   cd frontend && npm ci && npm run build && cd ..
#   pyinstaller marco.spec --noconfirm
#
# Output: dist/Marco/Marco.exe  (one-dir bundle)

import os

block_cipher = None

# Include the built React frontend
frontend_dist = os.path.join('frontend', 'dist')

a = Analysis(
    ['marco.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle the entire frontend/dist tree
        (frontend_dist, os.path.join('frontend', 'dist')),
    ],
    hiddenimports=[
        # Flask ecosystem
        'flask',
        'flask_socketio',
        'engineio',
        'engineio.async_drivers.threading',
        'socketio',
        'socketio.async_drivers',
        'simple_websocket',
        'werkzeug',
        'werkzeug.routing',
        'werkzeug.serving',
        'jinja2',
        # QR code
        'qrcode',
        'qrcode.image.base',
        'qrcode.image.pure',
        'PIL',
        'PIL.Image',
        # pyttsx3 (TTS)
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        'win32com.client',
        # Data / analytics
        'pandas',
        'numpy',
        'matplotlib',
        'matplotlib.backends.backend_agg',
        # Standard library helpers
        'statistics',
        'csv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'PyQt5', 'PyQt6', 'wx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Marco',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # keep console so UDP/coaching output is visible
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,             # set to 'marco.ico' if you add an icon file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Marco',
)
