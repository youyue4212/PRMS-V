#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAQ Tablet main entry.
Starts in public home-monitor mode (no login). Login unlocks original pages.
"""

import sys
import os
import argparse

# Ensure package root on path
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core import themes
from core.main_window import MainWindow, INSTANCE_ACTIVATE_SERVER
from core.login_dialog import LoginDialog
from core.user_manager import get_user_manager


def _try_activate_existing_instance():
    """If another instance is running, ask it to raise and exit this process."""
    from PyQt5.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_ACTIVATE_SERVER)
    if sock.waitForConnected(200):
        sock.write(b"ACTIVATE")
        sock.flush()
        sock.waitForBytesWritten(200)
        sock.disconnectFromServer()
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="DAQ Tablet")
    parser.add_argument("--fullscreen", action="store_true", help="Start fullscreen")
    parser.add_argument("--keyboard-debug", action="store_true", help="Keyboard debug title")
    parser.add_argument("--login", action="store_true",
                        help="Force login dialog at startup (otherwise public home)")
    parser.add_argument("--control-room", action="store_true",
                        help="Start in control-room PC UI (multi-probe wall)")
    parser.add_argument("--tablet", action="store_true",
                        help="Force field-tablet UI for this session")
    args = parser.parse_args()
    use_fullscreen = args.fullscreen
    keyboard_debug = args.keyboard_debug

    # High-DPI + WebEngine OpenGL share (must be before QApplication)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("DAQ Tablet")
    app.setOrganizationName("Raysen")
    try:
        from core.app_version import APP_VERSION
        app.setApplicationVersion(APP_VERSION)
    except Exception:
        pass

    # UI mode override for this process (also persisted when --control-room/--tablet)
    if args.control_room or args.tablet:
        from core.config import ConfigManager
        cfg = ConfigManager()
        mode = "control_room" if args.control_room else "tablet"
        cfg.update_settings(ui_mode=mode)
        cfg.save_settings()
        print("UI mode set to:", mode)

    if str(os.environ.get("ALLOW_VIEWER_SETTINGS", "0")).strip() == "1":
        print("WARNING: ALLOW_VIEWER_SETTINGS=1 bypasses operator permissions; production must leave this unset")

    is_rpi = os.path.exists("/proc/device-tree/model")
    if not is_rpi and hasattr(os, "uname"):
        try:
            is_rpi = os.uname().machine.startswith("arm")
        except Exception:
            is_rpi = False

    # Single instance
    if _try_activate_existing_instance():
        print("Another instance is running; activation requested.")
        sys.exit(0)

    from PyQt5.QtNetwork import QLocalServer
    # Keep lock via MainWindow activation server; also hold a dummy name for pid file style
    single_instance_lock = QLocalServer()
    try:
        QLocalServer.removeServer(INSTANCE_ACTIVATE_SERVER + "_lock")
    except Exception:
        pass
    if not single_instance_lock.listen(INSTANCE_ACTIVATE_SERVER + "_lock"):
        # Race: another started
        if _try_activate_existing_instance():
            sys.exit(0)
    main._instance_lock = single_instance_lock

    from core.config import ConfigManager
    from core.ui_tokens import CR_CHROME_FONT_PX
    ui_mode = str(getattr(ConfigManager(), "ui_mode", "tablet") or "tablet").lower()
    control_room = ui_mode == "control_room"
    # 平板：9pt 触控。主控室：px 字号，避免高 DPI 下 pt 把顶栏/状态栏撑破。
    font = QFont("Microsoft YaHei")
    if not QFont("Microsoft YaHei").exactMatch():
        font = QFont("Segoe UI")
    if control_room and not is_rpi:
        font.setPixelSize(CR_CHROME_FONT_PX)
    else:
        font.setPointSize(10 if is_rpi else 9)
    app.setFont(font)
    app.setStyleSheet(themes.build_dark_stylesheet(control_room=control_room))

    current_user = None
    if args.login:
        # Optional: start already logged in
        user_manager = get_user_manager()
        login_dialog = LoginDialog(prefer_viewer_autofill=True)
        if login_dialog.exec_() != LoginDialog.Accepted:
            sys.exit(0)
        current_user = login_dialog.get_current_user_info()
        if not current_user:
            QMessageBox.critical(None, "Error", "Cannot get user info")
            sys.exit(1)
        actual = user_manager.get_current_user()
        if actual:
            current_user["role"] = actual.role
    else:
        print("Starting in public home-monitor mode (no login)")

    window = MainWindow(current_user)

    if keyboard_debug:
        window.setWindowTitle(f"{window.windowTitle()} - Keyboard Debug")
        print("Keyboard debug mode enabled")

    if use_fullscreen:
        window.showFullScreen()
        print("Fullscreen enabled")
    else:
        window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
