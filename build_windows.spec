# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file — PT AI Voice
Build: pyinstaller build_windows.spec
"""
import os
import sys
import importlib

# ── Tìm đường dẫn customtkinter tự động ──────────────────────────────────
ctk_path = os.path.dirname(importlib.import_module("customtkinter").__file__)

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Đóng gói toàn bộ customtkinter (themes, assets, icons...)
        (ctk_path, 'customtkinter'),
        # File config mẫu
        ('voice_config.json', '.'),
    ],
    hiddenimports=[
        'customtkinter',
        'edge_tts',
        'edge_tts.communicate',
        'edge_tts.list_voices',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.ttk',
        'asyncio',
        'concurrent.futures',
        'json',
        'dataclasses',
        'tempfile',
        'shutil',
        'subprocess',
        'threading',
        'pathlib',
        'base64',
        're',
        'xml.etree.ElementTree',
        'certifi',
        'aiohttp',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        'pytest',
        'unittest',
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
    [],                     # Không gộp vào 1 file (onedir mode — ổn định hơn)
    exclude_binaries=True,
    name='PT AI Voice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Ẩn console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ctk_path, 'assets', 'icons', 'CustomTkinter_icon_Windows.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PT AI Voice',
)
