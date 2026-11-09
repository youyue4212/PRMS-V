# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for daq_tablet (run build_windows.bat / build_linux.sh)
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

spec_dir = os.path.dirname(os.path.abspath(SPEC))
app_dir = os.path.abspath(os.path.join(spec_dir, ".."))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

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
    "serial.tools",
    "serial.tools.list_ports",
    "openpyxl",
    "openpyxl.cell",
    "openpyxl.workbook",
    "openpyxl.styles",
    "psutil",
    "scipy",
    "core",
    "core.algorithm",
    "core.alarm_log_page",
    "core.alarm_logger",
    "core.alarm_logger_english",
    "core.autosave_worker",
    "core.config",
    "core.config_ui",
    "core.control_room_page",
    "core.detector",
    "core.diagnostics",
    "core.excel_io",
    "core.home_page",
    "core.icons",
    "core.industrial_dialogs",
    "core.logger",
    "core.login_dialog",
    "core.main_window",
    "core.master_summary",
    "core.pages",
    "core.raw_logger",
    "core.singleton",
    "core.software_keyboard",
    "core.tcp_detector",
    "core.themes",
    "core.timeout_manager",
    "core.translation",
    "core.ui_base",
    "core.ui_components",
    "core.ui_tokens",
    "core.user_management_dialog",
    "core.user_manager",
    "core.utils",
    "core.vehicle_dashboard_page",
    "core.vehicle.rtsp_preview",
    "core.vehicle.rtsp_url",
    "core.vehicle.hik_isapi",
    "core.vehicle.camera_service",
    "core.vehicle.alarm_clip_recorder",
    "core.vehicle.evidence_export",
    "core.vehicle.evidence_assets",
    "cv2",
]
try:
    hiddenimports += collect_submodules("core")
except Exception:
    pass

binaries = []
try:
    cv2_datas, cv2_binaries, cv2_hidden = collect_all("cv2")
    datas_pre = []
    datas_pre += cv2_datas
    binaries += cv2_binaries
    hiddenimports += cv2_hidden
except Exception as exc:
    raise SystemExit(
        "打包需要 opencv-python（车辆 RTSP 预览）。"
        " 请在 .venv_pack 中执行: pip install opencv-python\n"
        " 详情: %s" % exc
    )

datas = [
    (os.path.join(app_dir, "hmi_web"), "hmi_web"),
    (os.path.join(app_dir, "core", "icons"), os.path.join("core", "icons")),
]
try:
    datas += collect_data_files("pyqtgraph")
except Exception:
    pass
try:
    datas += datas_pre
except NameError:
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
    binaries=binaries,
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
