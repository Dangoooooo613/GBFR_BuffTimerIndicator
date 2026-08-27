# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/gbfr_overlay_qt_v6.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/embedded_roll_icon.png', '.'),
        ('assets/app_icon.ico', '.'),
        ('GBFR_Character_Skills_Buffs.json', '.'),
        ('assets/effect_id_class.json', 'assets'),
        ('assets/skillboard_map.json', 'assets'),
        ('src/i18n.json', '.'),
        ('version.json', '.'),
    ],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtNetwork', 'mastery_reader', 'buff_data_generated', 'i18n_loader',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['numpy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GBFR_CooldownIndicator_V2040",
    icon='assets/app_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
)
