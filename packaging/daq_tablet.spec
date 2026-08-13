# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for daq_tablet (run build_windows.bat / build_linux.sh)
import os

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

spec_dir = os.path.dirname(os.path.abspath(SPEC))
app_dir = os.path.abspath(os.path.join(spec_dir, ".."))

hiddenimports = [
    "PyQt5",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebEngineCore",
    "PyQt5.sip",
    "PyQt5.QtSvg",
    "pyqtgraph",
    "numpy",
    "pandas",
    "serial",
    "openpyxl",
    "psutil",
    "scipy",
]

datas = [
    (os.path.join(app_dir, "hmi_web"), "hmi_web"),
    (os.path.join(app_dir, "core", "icons"), os.path.join("core", "icons")),
]
try:
    datas += collect_data_files("pyqtgraph")
except Exception:
    pass

# UPX 压缩 python3xx.dll / VCRUNTIME 后，Windows LoadLibrary 常报
# “Failed to load Python DLL / 找不到指定的模块”，因此默认关闭。
upx_exclude = [
    "python3.dll",
    "python314.dll",
    "python313.dll",
    "python312.dll",
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
]

a = Analysis(
    [os.path.join(app_dir, "main.py")],
    pathex=[app_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="daq_tablet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=upx_exclude,
    console=False,
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
    upx=False,
    upx_exclude=upx_exclude,
    name="daq_tablet",
)
