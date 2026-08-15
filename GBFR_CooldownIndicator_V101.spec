# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/gbfr_overlay_qt_v6.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/embedded_roll_icon.png', '.'), ('assets/app_icon.ico', '.'), ('GBFR_Character_Skills_Buffs.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='GBFR_CooldownIndicator_V101',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)
