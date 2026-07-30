# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 规格文件（在「目标架构」的机器上运行打包）
用法见同目录 build_linux.sh / build_windows.bat
"""
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = [
    'PyQt5',
    'pyqtgraph',
    'numpy',
    'pandas',
    'serial',
    'openpyxl',
    'psutil',
    'scipy',
]

# 收集 pyqtgraph 等可能用到的数据文件
datas = []
try:
    datas += collect_data_files('pyqtgraph')
except Exception:
    pass

a = Analysis(
    ['../main.py'],
    pathex=['..'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib'],
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
    name='daq_tablet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 程序；调试时可改 True 看报错
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='daq_tablet',
)
