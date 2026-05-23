# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gdrivelink.py'],
    pathex=[],
    binaries=[],
    datas=[('gdrivelink.ico', '.'), ('GDriveLink-logo-128.png', '.')],
    excludes=['pycparser.lextab', 'pycparser.yacctab'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name='GDriveLink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['gdrivelink.ico'],
)
