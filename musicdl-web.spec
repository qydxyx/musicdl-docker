# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all musicdl submodules (dynamic source plugins)
hiddenimports = (
    collect_submodules('musicdl') +
    collect_submodules('cryptography') +
    collect_submodules('Cryptodome') +
    collect_submodules('curl_cffi') +
    collect_submodules('lxml') +
    collect_submodules('av') +
    collect_submodules('flask') +
    collect_submodules('mutagen') +
    collect_submodules('waitress') +
    collect_submodules('nodejs_wheel') +
    ['backend', 'backend.app', 'backend.config', 'backend.sources_registry',
     'backend.streamer', 'backend.downloader', 'backend.library']
)

# Collect data files from nodejs_wheel (node binary for YouTube source)
nodejs_datas = collect_data_files('nodejs_wheel', include_py_files=False)

datas = [
    ('static', 'static'),
    ('backend', 'backend'),
] + nodejs_datas

a = Analysis(
    ['backend/app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='musicdl-web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
