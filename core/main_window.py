import sys
import glob
import time
import random
import re
import struct
import serial
import os
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg

from PyQt5.QtCore import (
    Qt, QTimer, QPointF, QThread, QMutex, pyqtSignal, QObject, QEvent
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QLinearGradient, QPainterPath, QFont, QIcon
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy, QStackedWidget,
    QGroupBox, QFileDialog, QCheckBox, QLineEdit, QComboBox, QDoubleSpinBox,
    QSpinBox, QTextEdit, QFormLayout, QStyle, QTabWidget, QDockWidget, QAction,
    QToolBar, QStatusBar, QMessageBox
)
from PyQt5.QtSvg import QSvgWidget

from core.config import ConfigManager
from core import algorithm as alg
from core import icons 
from core.detector import (
    CmdFeedback, SpectrumPacket, search_serial_devices,
    SerialPacketWorker, DevMessage
)
from core.tcp_detector import TcpPacketWorker

from core.ui_base import UIBase
from core.utils import get_battery_percentage
from core.alarm_log_page import AlarmLogPage  # 导入报警记录页面
from core.icons import get_icon_svg  # Assuming your SVG functions are in a separate module

# 导入新模块
from core.ui_components import StatusBar, DataCard, BottomNavBar, AcquisitionButton
from core.diagnostics import FaultCode
from core.pages import OverviewPage, SpectrumPage, SettingsPage, ClientsPage
from core.home_page import HomePage
from core.control_room_page import ControlRoomPage

# 故障摘要 / 概览说明：主页显示前 1～3 条，超出部分放 tooltip
_FAULT_DESC_MAX_LINES = 3
_MASTER_FAULT_CLIENT_ID = "master"
_PROBE_COMM_CODES = (FaultCode.E101, FaultCode.E102, FaultCode.E103)


def _strip_fault_placeholders(text: str) -> str:
    """去掉旧文案残留的占位符，避免界面出现字面量 {probe}。"""
    if not text:
        return ""
    ph = "{" + "probe" + "}"
    return text.replace(ph, "").replace("  ", " ").strip()


def _format_fault_description(messages: list, max_lines: int = _FAULT_DESC_MAX_LINES) -> tuple:
    """返回 (卡片内显示文本, 完整文本用于 tooltip)。"""
    if not messages:
        return "", ""
    cleaned = [_strip_fault_placeholders(m) for m in messages if _strip_fault_placeholders(m)]
    if not cleaned:
        return "", ""
    full_text = "\n".join(cleaned)
    if len(cleaned) <= max_lines:
        return full_text, full_text
    shown = "\n".join(cleaned[:max_lines])
    shown += f"\n… (+{len(cleaned) - max_lines})"
    return shown, full_text

# 导入用户管理模块
from core.user_manager import get_user_manager, UserRole, Permission
from core.industrial_dialogs import ask_confirm, show_warn, show_info, show_error

# 导入超时管理器模块
from core.timeout_manager import get_timeout_manager

# 二次启动时通过本地套接字唤起已运行实例（hide/最小化后点图标用）
INSTANCE_ACTIVATE_SERVER = "daq_tablet_activate"


class MainWindow(QMainWindow, UIBase):
    # 左上角隐藏入口热区（相对主窗口坐标，像素）。树莓派触摸宜略大。
    _SECRET_CORNER_SIZE = 80
    # 离开总览后无操作自动返回：监视短、登录稍长（管理员 3 分钟仍会退出）
    _IDLE_RETURN_PUBLIC_SEC = 45
    _IDLE_RETURN_LOGGED_IN_SEC = 120
    """Main application window"""
    def __init__(self, current_user=None):
        super().__init__()
        
        # 存储用户信息
        self.current_user = current_user
        self.user_manager = get_user_manager()
        
        # 初始化超时管理器
        self.timeout_manager = get_timeout_manager()

        self.control_room_mode = (
            str(getattr(self.config, "ui_mode", "tablet") or "tablet").lower() == "control_room"
        )
        
        # Set window title based on user role
        from core.translation import _t
        if current_user and 'username' in current_user:
            username = current_user['username']
            role_name = self._window_role_name(current_user['role'])
            self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
        else:
            self.setWindowTitle(
                _t("control_room_title") if self.control_room_mode else _t("home_title")
            )
        
        # 设置窗口初始大小，但不固定，允许外部控制全屏或调整大小
        if self.control_room_mode:
            self.resize(1440, 900)
        else:
            self.resize(1024, 600)
        self.setStyleSheet("QMainWindow { background-color: #1a1a1a; }")

        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Status bar - 添加用户信息显示
        self.status_bar = StatusBar()
        if self.control_room_mode and hasattr(self.status_bar, "set_desktop_compact"):
            self.status_bar.set_desktop_compact(True)
        if current_user and 'username' in current_user:
            self.status_bar.update_user_info(current_user['username'], current_user['role'])
        else:
            self.status_bar.update_user_info(_t("status_public_mode"), None)
        main_layout.addWidget(self.status_bar)
        
        # Stacked widget for pages
        # 0: 主显示(免登录) — 平板 HomePage / 主控室 ControlRoomPage
        # 1: 原实时概览  2:能谱  3:诊断  4:报警日志  5:设置
        self.stacked_widget = QStackedWidget()
        
        self.home_page = HomePage(self, headless=bool(self.control_room_mode))
        self.home_page.channel_reset_btn.clicked.connect(self.request_channel_alarm_reset)
        self.control_room_page = ControlRoomPage(self)
        self.control_room_page.probe_selected.connect(self._on_control_room_probe)
        self.control_room_page.open_alarm_log.connect(lambda: self.switch_page(4))
        self.control_room_page.open_diagnostics.connect(self.open_health_or_commissioning)
        self.control_room_page.reset_requested.connect(self.request_channel_alarm_reset)
        self.control_room_page.login_requested.connect(self._on_control_room_session_btn)
        self.control_room_page.reorder_requested.connect(self._on_control_room_reorder)
        self.overview_page = OverviewPage(self)
        self.spectrum_page = SpectrumPage(self)
        self.clients_page = ClientsPage(self)
        self.alarm_log_page = AlarmLogPage(self)
        self.settings_page = SettingsPage(self)

        # Page 0 shell depends on UI mode (tablet vs control room).
        # 未进栈的那一页若仍挂在 MainWindow 下，会在左上角露出残影（Web 滚动条/箭头）。
        self._shell_stash = QWidget(self)
        self._shell_stash.hide()
        self._shell_stash.setFixedSize(0, 0)
        self.primary_home_page = (
            self.control_room_page if self.control_room_mode else self.home_page
        )
        unused_shell = (
            self.home_page if self.control_room_mode else self.control_room_page
        )
        unused_shell.hide()
        unused_shell.setParent(self._shell_stash)
        self.stacked_widget.addWidget(self.primary_home_page)
        self.stacked_widget.addWidget(self.overview_page)
        self.stacked_widget.addWidget(self.spectrum_page)
        self.stacked_widget.addWidget(self.clients_page)
        self.stacked_widget.addWidget(self.alarm_log_page)
        self.stacked_widget.addWidget(self.settings_page)

        # 各页内容（尤其设置页）高度可能超过屏幕；禁止把底栏顶出去。
        self.stacked_widget.setMinimumHeight(0)
        self.stacked_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for i in range(self.stacked_widget.count()):
            page = self.stacked_widget.widget(i)
            if page is None:
                continue
            page.setMinimumHeight(0)
            page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        main_layout.addWidget(self.stacked_widget, 1)
        
        # Acquisition button container - 优化为小屏幕（登录后才显示）
        self.button_container = QWidget()
        self.button_container.setStyleSheet("background-color: #1a1a1a;")
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(20, 6, 20, 6)
        button_layout.setSpacing(12)
        
        # 工控触控目标约 44px
        button_height = 44
        
        # Add save data button
        self.save_data_btn = QPushButton(_t("btn_save"))
        self.save_data_btn.setFixedHeight(button_height)
        self.save_data_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #1976D2;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.save_data_btn.clicked.connect(self.save_data)
        button_layout.addWidget(self.save_data_btn)

        self.start_acq_btn = QPushButton(_t("btn_acq_start"))
        self.start_acq_btn.setFixedHeight(button_height)
        self.start_acq_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2E7D32;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #1B5E20;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.start_acq_btn.clicked.connect(self.on_start_acq)
        self.start_acq_btn.setVisible(False)
        button_layout.addWidget(self.start_acq_btn)

        self.stop_acq_btn = QPushButton(_t("btn_acq_stop"))
        self.stop_acq_btn.setFixedHeight(button_height)
        self.stop_acq_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #C62828;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #8E0000;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.stop_acq_btn.clicked.connect(self.on_stop_acq)
        self.stop_acq_btn.setVisible(False)
        button_layout.addWidget(self.stop_acq_btn)

        self.acquisition_btn = AcquisitionButton()
        self.acquisition_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.acquisition_btn)
        
        # Add user management button (visible only to admin)
        self.user_management_btn = QPushButton(_t("btn_user_mgmt"))
        self.user_management_btn.setFixedHeight(button_height)
        self.user_management_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #9C27B0;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #7B1FA2;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.user_management_btn.clicked.connect(self.show_user_management)
        button_layout.addWidget(self.user_management_btn)

        # Add logout / login button
        self.logout_btn = QPushButton(_t("btn_login"))
        self.logout_btn.setFixedHeight(button_height)
        self.logout_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #45a049;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.logout_btn.clicked.connect(self.login)
        button_layout.addWidget(self.logout_btn)
        
        self.button_container.setLayout(button_layout)
        if self.control_room_mode:
            lay = self.button_container.layout()
            if lay is not None:
                lay.setContentsMargins(16, 4, 16, 4)
            self._apply_control_room_ops_chrome()
        main_layout.addWidget(self.button_container)
        
        # Bottom navigation
        self.bottom_nav = BottomNavBar()
        if self.control_room_mode and hasattr(self.bottom_nav, "set_desktop_compact"):
            self.bottom_nav.set_desktop_compact(True)
        self.bottom_nav.home_btn.clicked.connect(lambda: self.switch_page(0))
        self.bottom_nav.overview_btn.clicked.connect(lambda: self.switch_page(1))
        self.bottom_nav.spectrum_btn.clicked.connect(lambda: self.switch_page(2))
        self.bottom_nav.clients_btn.clicked.connect(lambda: self.switch_page(3))
        self.bottom_nav.alarm_log_btn.clicked.connect(lambda: self.switch_page(4))
        self.bottom_nav.settings_btn.clicked.connect(lambda: self.switch_page(5))
        main_layout.addWidget(self.bottom_nav)
        
        central_widget.setLayout(main_layout)
        
        # 注意：UIBase.__init__()已经调用了setup_ui()，所以这里不需要再次调用
        # 但是我们需要确保回调函数正确设置
        # 在UIBase中设置回调函数
        self.data_updated_callback = self.data_updated
        self.alarm_status_callback = self.update_alarm_status
        self.master_summary_callback = self.on_master_summary_ui
        self.prev_fault_keys = set()
        self._prev_probe_comm_keys = set()

        # 连接超时管理器信号
        self.timeout_manager.timeout_occurred.connect(self.on_admin_timeout)
        self.timeout_manager.timer_updated.connect(self.on_timeout_timer_updated)
        
        # 连接语言切换信号
        self.status_bar.language_changed.connect(self.on_language_changed)
        self.status_bar.clear_requested.connect(self.clear_data)
        self.status_bar.save_requested.connect(lambda: self.save_data())
        self.status_bar.users_requested.connect(self.show_user_management)
        
        # 绑定全局操作事件（所有点击/输入均更新操作时间，重置计时器）
        self.installEventFilter(self)

        # 隐藏入口：不依赖透明覆盖层（Ubuntu 上全透明常被点穿，触摸落在状态栏）。
        # 改为按主窗口左上角坐标长按检测；应用级过滤器保证子控件上的触摸也能收到。
        self._restore_fullscreen_on_show = False
        self._secret_hold_timer = QTimer(self)
        self._secret_hold_timer.setSingleShot(True)
        self._secret_hold_timer.setInterval(1500)
        self._secret_hold_timer.timeout.connect(lambda: self.return_to_desktop(silent=True))
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        # 二次启动唤起：点桌面图标时，把已隐藏/最小化的窗口拉回并全屏
        self._setup_instance_activation_server()
        
        # Setup timer for periodic checking
        self.device_mon_timer = QTimer()
        self.device_mon_timer.timeout.connect(self.check_device_connection)
        self.device_mon_timer.start(1000)  # Check every second
        # Initial check
        self.check_device_connection()
        
        self._last_ui_activity_at = time.time()
        self._idle_home_timer = QTimer(self)
        self._idle_home_timer.timeout.connect(self._check_idle_return_home)
        self._idle_home_timer.start(1000)
        
        # 根据用户权限更新UI（未登录=主显示监视模式）
        self.update_ui_for_user_role()
        for page in (
            self.home_page, self.control_room_page, self.overview_page, self.spectrum_page,
            self.clients_page, self.alarm_log_page, self.settings_page,
        ):
            if hasattr(page, "retranslate_ui"):
                page.retranslate_ui()
        if hasattr(self.bottom_nav, "retranslate_ui"):
            self.bottom_nav.retranslate_ui()
        self._apply_control_room_nav_labels()
        # 冷启动：无主控时占用区显示「未接入主控」，避免默认「通道空闲/主控离线」
        try:
            self._refresh_home_from_probes(getattr(self, "client_data", None) or {})
        except Exception:
            pass
        if self.control_room_mode and hasattr(self, "control_room_page"):
            self.control_room_page.set_login_visible(not self.is_logged_in())
            self.control_room_page.set_reorder_enabled(self.is_logged_in())
            self.control_room_page.set_alarm_polling(True)
            self._refresh_control_room_snapshot()
            if hasattr(self, "status_bar") and hasattr(self.status_bar, "set_battery_visible"):
                self.status_bar.set_battery_visible(False)
        elif hasattr(self, "control_room_page"):
            self.control_room_page.set_alarm_polling(False)
        
        # 如果是管理员模式，启动超时计时器
        if self._is_privileged_user():
            self.timeout_manager.start_timer()
            self.log("Admin mode started, will auto logout after 3 minutes of inactivity", 'INFO')






        # Simulation timer
    def check_device_connection(self):
        # 确保TCP连接已建立
        if isinstance(self.worker, TcpPacketWorker):
            tcp_ready = self.worker.is_tcp_ready()
            self.log(f"TCP ready check: {tcp_ready}", 'DEBUG')
            
            if not tcp_ready:
                # 与设置页一致：始终服务端监听；失败退避，避免 10049 每秒 3 次刷屏
                import time as _time
                now = _time.time()
                host = self.config.tcp_host
                port = self.config.tcp_port
                key = (str(host), int(port), "server")
                backoff = float(getattr(self, "_tcp_reconnect_backoff_sec", 0) or 0)
                last_at = float(getattr(self, "_tcp_reconnect_last_at", 0) or 0)
                if backoff > 0 and (now - last_at) < backoff and getattr(self, "_tcp_reconnect_key", None) == key:
                    self.log(
                        f"TCP reconnect skipped (backoff {backoff:.0f}s after bind/connect failure)",
                        'DEBUG',
                    )
                else:
                    self.log("TCP not ready, attempting to reconnect...", 'INFO')
                    # UI 固定 server；勿用可能过期的 client 模式去 connect 0.0.0.0
                    ok = self.worker.connect_tcp(host, port, "server")
                    self._tcp_reconnect_key = key
                    self._tcp_reconnect_last_at = now
                    if ok:
                        self._tcp_reconnect_backoff_sec = 0
                        self.log("TCP reconnection successful", 'INFO')
                    else:
                        # 指数退避到 30s，改设置后 key 变会立即再试
                        prev = backoff if backoff > 0 else 1.0
                        self._tcp_reconnect_backoff_sec = min(30.0, prev * 2.0)
                        self.log(
                            f"TCP reconnection failed; next retry in {self._tcp_reconnect_backoff_sec:.0f}s",
                            'WARNING',
                        )
        
        is_connected = self.worker.try_connection()
        self.status_bar.update_connection_status(is_connected)
        if isinstance(self.worker, TcpPacketWorker) and is_connected:
            self._ensure_tcp_link_layer()
        
        # 如果连接失败且是串口模式，更新串口设备下拉列表
        if not is_connected and isinstance(self.worker, SerialPacketWorker):
            self.log("Serial connection failed, updating serial port list...", 'INFO')
            self.update_serial_port_combo()

        n_tcp_clients = 0
        if isinstance(self.worker, TcpPacketWorker):
            n_tcp_clients = len(getattr(self.worker, "client_sockets", {}) or {})
        # TCP：仅监听不算「有数据通路」，避免无探头空采；有客户端才自动累计。
        data_path_up = bool(is_connected)
        if isinstance(self.worker, TcpPacketWorker):
            data_path_up = n_tcp_clients > 0
        
        # 自动开始/停止数据采集。检修停采锁期间连上也不自动再开。
        if data_path_up and not self.is_acquiring:
            if self.is_acq_hold_locked():
                self.log(
                    "Connection detected but maintenance hold is active; auto-start suppressed",
                    "DEBUG",
                )
            else:
                self.log(
                    f"Connection detected (is_connected={is_connected}, is_acquiring={self.is_acquiring}), starting acquisition automatically",
                    'INFO',
                )
                success = self.start_acquisition(from_auto=True)
                if success:
                    self.log("Acquisition started successfully", 'INFO')
                else:
                    self.log("Failed to start acquisition", 'WARNING')
        elif not is_connected and self.is_acquiring:
            # 连接断开，自动停止采集（不设停采锁，避免误当成检修停采）
            self.log("Connection lost, stopping acquisition automatically", 'INFO')
            if self.is_acq_hold_locked():
                self.stop_acquisition(hold=True)
            else:
                self.stop_acquisition()
        else:
            # 调试信息
            self.log(f"Connection status: is_connected={is_connected}, is_acquiring={self.is_acquiring}", 'DEBUG')
        self._sync_acq_action_buttons()
            
        # 特殊处理：如果连接存在但数据不显示，强制检查数据流
        if is_connected and self.is_acquiring:
            # 检查数据回调是否设置
            if self.data_updated_callback is None:
                self.log("WARNING: data_updated_callback is None, resetting...", 'WARNING')
                self.data_updated_callback = self.data_updated
            if self.alarm_status_callback is None:
                self.log("WARNING: alarm_status_callback is None, resetting...", 'WARNING')
                self.alarm_status_callback = self.update_alarm_status
            if self.master_summary_callback is None:
                self.master_summary_callback = self.on_master_summary_ui

        # 运行周期性诊断检查（按有效在线探头/IP 去重，避免幽灵连接）
        if hasattr(self, "get_online_probe_client_ids"):
            connected_clients = self.get_online_probe_client_ids()
        else:
            connected_clients = []
            if self.config.tcp_enabled and hasattr(self.worker, 'client_infos'):
                connected_clients = list(self.worker.client_infos.keys())
            else:
                if self.worker and self.worker.is_running:
                    connected_clients = ["serial_client"]

        self.diagnostics_manager.run_periodic_checks(
            connected_clients,
            ignore_clients=[cid for cid in [getattr(self, "master_client_id", None)] if cid],
        )
        self._sync_probe_count_fault()
        self._update_master_diagnostics()
        purged = getattr(self.diagnostics_manager, "purged_offline_clients", None) or []
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        # 在线数已达标：务必清掉幽灵 IP 编号（即使本轮没有 purged 列表）
        if hasattr(self, "prune_disconnected_probe_labels"):
            if purged or (expected > 0 and len(connected_clients) >= expected):
                self.prune_disconnected_probe_labels(connected_clients)
        
        # 更新系统状态（综合报警与故障码）
        self.update_system_status()
        self._update_home_health_and_faults()
        
    
    def is_logged_in(self) -> bool:
        """Whether a real user session is active (not public monitor mode)."""
        return bool(self.current_user and self.current_user.get("username"))
    
    def switch_page(self, index):
        """切换页面。主显示(0)与报警日志(4)公共只读可进；其它页需登录。"""
        public_ok = index in (0, 4)
        if not public_ok and not self.is_logged_in():
            # 主控室公共值班：不弹登录，只允许总览和报警日志
            if getattr(self, "control_room_mode", False):
                return
            # 平板：需要登录；取消则静默回主显示
            if self.login(preferred_page=index, required_for_page=True):
                return
            self._apply_page_index(0)
            return

        self._apply_page_index(index)
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        self._note_ui_activity()

    def open_health_or_commissioning(self):
        """首页健康卡：传感器未配置去设置开通页，其它情况去诊断页。"""
        pkt = getattr(self, "latest_master_summary", None)
        uncfg = False
        try:
            if pkt is not None and self.is_master_online():
                uncfg = int(pkt.sensor_mode_code()) == 2
        except Exception:
            uncfg = False
        if uncfg:
            if (not self.is_logged_in()) and getattr(self, "control_room_mode", False):
                self.switch_page(3)
                return
            self.switch_page(5)
            return
        self.switch_page(3)

    def _current_role(self):
        if isinstance(getattr(self, "current_user", None), dict):
            return self.current_user.get("role")
        return None

    def _is_maintainer_user(self) -> bool:
        return self._current_role() == UserRole.MAINTAINER

    def _is_privileged_user(self) -> bool:
        return self._current_role() in (UserRole.ADMIN, UserRole.MAINTAINER)

    def _window_role_name(self, role) -> str:
        from core.translation import _t

        if role == UserRole.ADMIN:
            return _t("role_admin")
        if role == UserRole.MAINTAINER:
            return _t("role_maintainer")
        return _t("role_viewer")

    def _client_is_master_endpoint(self, client_id: str) -> bool:
        """True when this TCP session is the master, not a probe."""
        cid = str(client_id or "")
        if not cid:
            return False
        master = ""
        if hasattr(self, "_get_master_client_id"):
            master = str(self._get_master_client_id() or "")
        else:
            master = str(getattr(self, "master_client_id", "") or "")
        if master and cid == master:
            return True
        ip = ""
        if hasattr(self, "_extract_client_ip"):
            ip = str(self._extract_client_ip(cid) or "")
        last_ip = str(getattr(self, "_last_master_ip", "") or "")
        return bool(ip and last_ip and ip == last_ip)

    def _describe_last_tcp_timeout(self) -> str:
        """M102 附言只引用主控 socket。探头断连留在 E101/E102，不写进主控故障。"""
        worker = getattr(self, "worker", None)
        meta = dict(getattr(worker, "last_timeout_meta", None) or {})
        if not meta and worker is not None:
            recent = dict(getattr(worker, "_last_link_event", None) or {})
            cid = str(recent.get("client_id") or "")
            if (
                recent.get("kind") in ("socket_error", "peer_closed", "client_removed")
                and self._client_is_master_endpoint(cid)
            ):
                return "链路断开/Socket异常：%s" % cid
            return ""
        if not meta:
            return ""
        recent_cid = str(meta.get("recent_client_id") or "")
        recent_is_master = self._client_is_master_endpoint(recent_cid)
        kind = str(meta.get("kind") or "")
        if kind == "link_drop" and recent_is_master:
            prefix = "链路断开/Socket异常后超时"
        elif kind == "rx_stall":
            prefix = "连接未断开，仅接收空窗超时"
        else:
            prefix = "通信超时"
        extras = []
        try:
            age = float(meta.get("age_sec", 0.0) or 0.0)
            if age > 0:
                extras.append("空窗%.1fs" % age)
        except (TypeError, ValueError):
            pass
        try:
            clients = int(meta.get("clients", 0) or 0)
            if clients > 0:
                extras.append("在线连接%d" % clients)
        except (TypeError, ValueError):
            pass
        recent_kind = str(meta.get("recent_kind") or "")
        if recent_kind and recent_is_master:
            tail = recent_kind
            if recent_cid:
                tail += ":" + recent_cid
            extras.append(tail)
        return prefix + ("（%s）" % "，".join(extras) if extras else "")

    def _product_id_is_unique(self, product_id: int, current_client_id: str = None) -> bool:
        for cid, data in (getattr(self, "client_data", None) or {}).items():
            if not cid or cid == current_client_id:
                continue
            try:
                live_pid = int((data or {}).get("product_id", 0) or 0)
            except (TypeError, ValueError):
                live_pid = 0
            if live_pid > 0 and live_pid == int(product_id):
                return False
        return True

    def _apply_page_index(self, index):
        """切页后的统一收尾：状态栏、首页/曲线刷新、绘图节拍。登录/退出也走这里。"""
        # 先写首页数据再 show，避免 showEvent 把藏页期间的旧画面立刻推上去
        if index == 0:
            if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
                self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
            else:
                self._refresh_home_from_probes(self.client_data)
            if getattr(self, "control_room_mode", False):
                self._refresh_control_room_snapshot()

        self.stacked_widget.setCurrentIndex(index)
        if hasattr(self, "bottom_nav"):
            self.bottom_nav.set_active_button(index)
        if hasattr(self, "status_bar"):
            # 平板主显示用 Web 顶栏藏 Qt 状态栏；主控室模式始终显示状态栏
            if getattr(self, "control_room_mode", False):
                self.status_bar.setVisible(True)
            else:
                self.status_bar.setVisible(index != 0)
            if self.status_bar.isVisible() and hasattr(self.status_bar, "set_clock_visible"):
                self.status_bar.set_clock_visible(True)
        if not self.is_logged_in():
            self._apply_public_chrome(index)
        if index == 0:
            home = getattr(self, "home_page", None)
            if home is not None and hasattr(home, "force_web_flush"):
                home.force_web_flush()
            elif home is not None and hasattr(home, "schedule_web_flush"):
                home.schedule_web_flush(immediate=True)
        elif index in (1, 2):
            self._plot_dirty = True
            self.update_data(update_cps=(index == 1), update_spectrum=(index == 2))
        if hasattr(self, "_sync_plot_timer_interval"):
            self._sync_plot_timer_interval(index)
        if hasattr(self, "alarm_log_page") and hasattr(self.alarm_log_page, "update_auth_controls"):
            self.alarm_log_page.update_auth_controls()
        self._sync_control_room_action_bar()

    def _apply_public_chrome(self, index: int):
        """公共模式 UI：主显示藏底栏；报警日志显示底栏便于返回。主控室模式常显底栏。"""
        if self.is_logged_in():
            return
        self.button_container.setVisible(False)
        self.acquisition_btn.setVisible(False)
        if hasattr(self, "start_acq_btn"):
            self.start_acq_btn.setVisible(False)
        if hasattr(self, "stop_acq_btn"):
            self.stop_acq_btn.setVisible(False)
        self.save_data_btn.setVisible(False)
        self.user_management_btn.setVisible(False)
        # 主控室：公共模式也保留导航，便于看日志/回总览
        if getattr(self, "control_room_mode", False):
            show_nav = True
            show_status = True
        else:
            show_nav = (index == 4)
            show_status = (index == 4)
        self.bottom_nav.setVisible(show_nav)
        if hasattr(self, "status_bar"):
            self.status_bar.setVisible(show_status)
            if show_status:
                from core.translation import _t
                self.status_bar.update_user_info(_t("status_public_readonly_log"), None)
        if hasattr(self, "control_room_page"):
            self.control_room_page.set_login_visible(True)
            self.control_room_page.set_reorder_enabled(False)
    
    def on_start_acq(self):
        """检修用户手动开始采集；同时解除停采锁。"""
        if not self.check_permission_before_action(
            "action_start_acq", Permission.START_STOP_ACQUISITION
        ):
            return
        self.update_operate_time()
        if self.is_acquiring:
            return
        from core.translation import _t
        has_held_data = False
        try:
            has_held_data = bool(self.client_time_series) or any(
                spec is not None and float(np.sum(spec)) > 0
                for spec in (self.client_spectrum_data or {}).values()
            )
        except Exception:
            has_held_data = bool(self.client_time_series or self.client_spectrum_data)
        if self.is_acq_hold_locked() and has_held_data:
            if not ask_confirm(
                self,
                _t("msg_acq_resume_title"),
                _t("msg_acq_resume_text"),
                danger=True,
            ):
                return
        ok = self.start_acquisition()
        if ok:
            self.log("Acquisition started by maintenance", "INFO")
        else:
            self.log("Start acquisition failed", "WARNING")
        self._sync_acq_action_buttons()
        if hasattr(self, "_update_home_health_and_faults"):
            self._update_home_health_and_faults()
        if getattr(self, "control_room_mode", False) and hasattr(self, "_refresh_control_room_snapshot"):
            self._refresh_control_room_snapshot()

    def on_stop_acq(self):
        """检修用户停止采集并上停采锁；保留当前谱/曲线便于保存。"""
        from core.translation import _t
        if not self.check_permission_before_action(
            "action_stop_acq", Permission.START_STOP_ACQUISITION
        ):
            return
        self.update_operate_time()
        if not self.is_acquiring:
            return
        if not ask_confirm(
            self,
            _t("msg_acq_hold_title"),
            _t("msg_acq_hold_text"),
            danger=True,
        ):
            return
        self.stop_acquisition(hold=True)
        self._sync_acq_action_buttons()
        if hasattr(self, "_update_home_health_and_faults"):
            self._update_home_health_and_faults()
        if getattr(self, "control_room_mode", False) and hasattr(self, "_refresh_control_room_snapshot"):
            self._refresh_control_room_snapshot()

    def clear_data(self):
        """清空当前显示累计；采集不停止。未存盘本段先落盘再开新段。"""
        from core.translation import _t
        if not self.check_permission_before_action("action_clear_data", Permission.CLEAR_DATA):
            return

        self.update_operate_time()

        if not ask_confirm(
            self,
            _t("msg_clear_data_title"),
            _t("msg_clear_data_text"),
            danger=True,
        ):
            return

        was_acquiring = bool(self.is_acquiring)
        try:
            if self.auto_save_enabled:
                self._auto_save_all_clients(force=True, blocking=True)
        except Exception as e:
            self.log("Auto-save before clear failed: %s" % e, "WARNING")

        self.reset_plots()
        self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
        self.client_data = {}
        self.client_time_series = {}
        self.client_spectrum_data = {}
        if hasattr(self, "client_archive_time_series"):
            self.client_archive_time_series = {}
        if hasattr(self, "client_segment_spectrum"):
            self.client_segment_spectrum = {}
        self.primary_client_id = None
        self.total_count_rate = 0
        self.last_auto_save_time = time.time()

        if self.data_updated_callback is not None:
            self.data_updated_callback(self.current_stat, 0, {})

        self.overview_page.radiation_card.update_data("0 cps", "")
        self.overview_page.status_card.update_data("0" + chr(176) + "C", "0 V")
        if hasattr(self, "home_page"):
            self.home_page.total_cps_label.setText("0")
            self.home_page.update_probe_tiles_from_master(None, False)

        if was_acquiring:
            self.log("Current accumulation cleared; acquisition continues", "INFO")
        else:
            self.log("Current display and accumulation cleared", "INFO")
    
    def save_data(self, auto_save=False, auto_save_path=""):
        """Save current data to file"""
        # 如果是自动保存，跳过权限检查（自动保存对所有用户级别都生效）
        if not auto_save:
            # 手动保存需要检查权限
            if not self.check_permission_before_action("action_save_data", Permission.SAVE_DATA):
                return
            
            # 更新操作时间（重置超时计时器）
            self.update_operate_time()
        
        # 调用父类方法，传递参数
        super().save_data(auto_save=auto_save, auto_save_path=auto_save_path)
    
    def data_updated(self, data, total_count_rate=None, client_data=None):
        """Update original overview cards; home probe CPS always from probe spectrum."""
        hv, rates, temp = data['hv'], data['rates'], data['temp']
        self.overview_page.radiation_card.update_data(f'{int(rates)} cps', "")
        self.overview_page.status_card.update_data(
            f'{round(temp,1)} ' + chr(176) + 'C',
            f'{round(hv,1)} V'
        )
        cd = client_data if client_data is not None else self.client_data
        # 各探头计数率：始终用探头 TCP 谱包（与能谱同源）
        self._apply_home_probe_cps(cd)
        # 主控在线：用最新 L2 刷新报警区（探头已无超阈时可软消 0x01）
        if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
            lang = "zh"
            try:
                from core.translation import TranslationManager
                lang = TranslationManager().current_lang
            except Exception:
                pass
            self._update_home_alarm_from_master(self.latest_master_summary, lang=lang)
            return
        # 主控无效：硬报警区显示离线（不跟探头拼通道报警）
        lang = "zh"
        try:
            from core.translation import TranslationManager
            lang = TranslationManager().current_lang
        except Exception:
            pass
        link_only = bool(getattr(self, "master_client_id", None))
        self.home_page.set_master_link_status(
            False,
            lang=lang,
            link_only=link_only,
            never_seen=self._master_never_seen(),
        )
        self.home_page.master_relay_label.setText("--")
        self._update_home_alarm_from_master(None, lang=lang, master_offline=True)
        self._update_home_occupancy(None, lang=lang, master_offline=True)

    def _collect_home_probe_entries(self, client_data=None):
        """Build home tile entries from probe TCP client_data (exclude master)."""
        from core.translation import _t

        data = client_data if client_data is not None else getattr(self, "client_data", {}) or {}
        master_cid = getattr(self, "master_client_id", None)
        items = []
        for cid, d in data.items():
            if master_cid and cid == master_cid:
                continue
            items.append((cid, d))

        def _sort_key(pair):
            cid, d = pair
            pid = d.get("product_id")
            try:
                if pid is not None and int(pid) > 0:
                    return (0, int(pid), cid)
            except (TypeError, ValueError):
                pass
            return (1, cid)

        items.sort(key=_sort_key)
        if not items and hasattr(self, "get_online_probe_client_ids"):
            for cid in self.get_online_probe_client_ids():
                items.append((cid, {"rates": 0, "alarm": False}))

        # Apply saved display order (drag-reorder on home)
        order = list(getattr(self.config, "probe_display_order", None) or [])
        if order and items:
            rank = {cid: i for i, cid in enumerate(order)}
            items.sort(key=lambda pair: (rank.get(pair[0], 10_000),) + _sort_key(pair))

        entries = []
        total = 0
        for i, (cid, d) in enumerate(items):
            cps = int(d.get("rates", 0) or 0)
            total += cps
            hit = bool(d.get("alarm", False))
            if hasattr(self, "get_probe_label"):
                name = self.get_probe_label(cid)
            else:
                name = _t("probe_slot_name", n=i + 1)
            entries.append({
                "name": name,
                "cps": cps,
                "online": True,
                "hit": hit,
                "client_id": cid,
            })
        return entries, total

    def open_probe_overview(self, client_id=None, slot_index=None):
        """主页点探头卡：选中该探头并跳到实时概览。"""
        if not client_id:
            entries, _ = self._collect_home_probe_entries(self.client_data)
            if slot_index is not None and 0 <= int(slot_index) < len(entries):
                client_id = entries[int(slot_index)].get("client_id")
        if not client_id:
            self.log("No probe selected for overview navigation", "WARNING")
            self.switch_page(1)
            return

        if hasattr(self, "set_primary_client"):
            try:
                self.set_primary_client(client_id)
            except Exception as e:
                self.log("Failed to select probe %s: %s" % (client_id, e), "WARNING")
        else:
            self.primary_client_id = client_id

        if hasattr(self, "client_selection_combo"):
            combo = self.client_selection_combo
            for i in range(combo.count()):
                if combo.itemData(i) == client_id:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break

        self.log("Home probe tile → overview: %s" % client_id, "INFO")
        self.switch_page(1)

    def _apply_home_probe_cps(self, client_data=None):
        """Home page per-probe CPS + total — from probe spectrum only."""
        from core.translation import TranslationManager

        lang = TranslationManager().current_lang
        page = self.home_page
        entries, total = self._collect_home_probe_entries(client_data)
        if not entries:
            # 保留上一帧，避免闪灰
            page.update_probe_tiles_from_probe_list([], lang=lang)
            if not getattr(page, "_had_tile_data", False):
                page.total_cps_label.setText("0")
                self._sync_control_room_probes([], 0)
            else:
                # still refresh CR from last home entries if any
                self._sync_control_room_from_home()
            return
        page.total_cps_label.setText("%d" % total)
        # master_online=True：CPS 已是正式显示源，不再标「(探头)」后缀
        page.update_probe_tiles_from_probe_list(entries, lang=lang, show_as_primary=True)
        self._sync_control_room_probes(entries, total)

    def _sync_control_room_probes(self, entries, total_cps=0):
        if not getattr(self, "control_room_mode", False):
            return
        cr = getattr(self, "control_room_page", None)
        if cr is None:
            return
        from core.translation import _t
        enriched = []
        for i, e in enumerate(entries or []):
            row = dict(e)
            if hasattr(self, "home_page"):
                try:
                    row["location"] = self.home_page._slot_location(i)
                except Exception:
                    row["location"] = row.get("location") or ""
            cid = row.get("client_id")
            live_name = ""
            if cid and hasattr(self, "get_probe_label"):
                try:
                    live_name = str(self.get_probe_label(cid) or "").strip()
                except Exception:
                    live_name = ""
            if live_name:
                row["name"] = live_name
            elif not row.get("name"):
                row["name"] = _t("probe_slot_name", n=i + 1)
            enriched.append(row)
        if not enriched and hasattr(self, "home_page"):
            # placeholders
            try:
                n = self.home_page._expected_placeholder_count()
            except Exception:
                n = 2
            from core.translation import _t
            for i in range(n):
                enriched.append({
                    "name": _t("probe_slot_name", n=i + 1),
                    "location": self.home_page._slot_location(i),
                    "cps": 0, "online": False, "hit": False, "client_id": None,
                })
        cr.update_probes(enriched, total_cps=total_cps)

    def _sync_control_room_from_home(self):
        if not getattr(self, "control_room_mode", False):
            return
        page = getattr(self, "home_page", None)
        cr = getattr(self, "control_room_page", None)
        if page is None or cr is None:
            return
        entries = list(getattr(page, "_probe_entries", None) or [])
        try:
            total = int(str(page.total_cps_label.text()).split()[0])
        except Exception:
            total = sum(int(e.get("cps", 0) or 0) for e in entries)
        self._sync_control_room_probes(entries, total)

    def _refresh_control_room_snapshot(self):
        """Push master link / alarm / occupancy / probes into control-room page."""
        if not getattr(self, "control_room_mode", False):
            return
        cr = getattr(self, "control_room_page", None)
        if cr is None:
            return
        page = getattr(self, "home_page", None)
        if page is not None:
            # master link：按 level 用当前语种生成，避免拷贝 home 旧中文
            level = "ok"
            try:
                level = page._link_level()
            except Exception:
                text0 = page.master_link_label.text() if hasattr(page, "master_link_label") else ""
                if "离线" in text0 or "Offline" in text0 or "未接入" in text0 or "No Master" in text0:
                    level = "offline"
                elif "等待数据" in text0 or "awaiting" in text0.lower() or "无L2" in text0 or "Linked" in text0:
                    level = "warn"
            try:
                from core.translation import TranslationManager
                lang = TranslationManager().get_language()
            except Exception:
                lang = "zh"
            if level == "ok":
                text = "Master Online" if lang == "en" else "主控在线"
            elif level == "warn":
                text = "Master Linked (awaiting data)" if lang == "en" else "主控已连接(等待数据)"
            else:
                never = False
                try:
                    never = self._master_never_seen()
                except Exception:
                    never = False
                if never:
                    text = "No Master Link" if lang == "en" else "未接入主控"
                else:
                    text = "Master Offline" if lang == "en" else "主控离线"
            cr.set_master_link(text, level)
            # channel alarm
            active = bool(getattr(page, "_reset_alarm_active", False))
            latch = ""
            try:
                latch = page.alarm_status_label.text()
            except Exception:
                pass
            cr.set_channel_alarm(
                active,
                latch,
                getattr(page, "_alarm_web_kind", lambda: "normal")(),
            )
            # occupancy
            occ_kind = getattr(page, "_occupancy_kind", None) or (
                "passing" if bool(getattr(page, "_passage_busy", False)) else "vacant"
            )
            st = page.occupancy_status_label.text() if hasattr(page, "occupancy_status_label") else "--"
            desc = page.occupancy_desc_label.text() if hasattr(page, "occupancy_desc_label") else ""
            cr.set_occupancy(occ_kind, st, desc)
            cr.set_health_summary(
                getattr(page, "health_status_label", None) and page.health_status_label.text() or "",
                getattr(page, "_health_rows", None) or {},
                bool(getattr(page, "health_status_label", None) and (
                    "故障" in page.health_status_label.text()
                    or "降级" in page.health_status_label.text()
                    or "FAULT" in page.health_status_label.text().upper()
                    or "DEGRAD" in page.health_status_label.text().upper()
                )),
            )
            cr.set_fault_summary(
                getattr(page, "fault_status_label", None) and page.fault_status_label.text() or "",
                (getattr(page, "_fault_rows", None) or {}).get("lastFault")
                or (getattr(page, "fault_desc_label", None) and page.fault_desc_label.text())
                or "",
                bool((getattr(page, "_fault_rows", None) or {}).get("lastTone")),
            )
        self._sync_control_room_from_home()
        cr.refresh_alarm_sidebar()
        cr.set_login_visible(not self.is_logged_in())
        cr.set_reorder_enabled(self.is_logged_in())

    def _apply_control_room_ops_chrome(self):
        """主控室操作条用桌面字号/高度，避免登录后样式被改回触控 44px。"""
        if not getattr(self, "control_room_mode", False):
            return
        from core.ui_tokens import CR_CHROME_H, CR_CHROME_FONT_PX
        bar_h = CR_CHROME_H + 4
        for btn in (
            getattr(self, "acquisition_btn", None),
            getattr(self, "start_acq_btn", None),
            getattr(self, "stop_acq_btn", None),
            getattr(self, "save_data_btn", None),
            getattr(self, "user_management_btn", None),
            getattr(self, "logout_btn", None),
        ):
            if btn is None:
                continue
            btn.setFixedHeight(bar_h)
            qss = btn.styleSheet() or ""
            qss = re.sub(r"font-size:\s*\d+px", "font-size: %dpx" % CR_CHROME_FONT_PX, qss)
            if "min-height:" in qss:
                qss = re.sub(r"min-height:\s*\d+px", "min-height: %dpx" % bar_h, qss)
            else:
                qss = qss.replace("QPushButton {", "QPushButton { min-height: %dpx;" % bar_h, 1)
            btn.setStyleSheet(qss)

    def _sync_acq_action_buttons(self):
        """概览/能谱页：仅检修用户显示开始/停止；总览不显示。"""
        from core.translation import _t
        start_btn = getattr(self, "start_acq_btn", None)
        stop_btn = getattr(self, "stop_acq_btn", None)
        if start_btn is None or stop_btn is None:
            return
        page = 0
        if hasattr(self, "stacked_widget") and self.stacked_widget is not None:
            page = int(self.stacked_widget.currentIndex())
        can = False
        try:
            can = bool(
                self.is_logged_in()
                and page in (1, 2)
                and self.user_manager.has_permission(Permission.START_STOP_ACQUISITION)
            )
        except Exception:
            can = False
        start_btn.setText(_t("btn_acq_start"))
        stop_btn.setText(_t("btn_acq_stop"))
        start_btn.setVisible(can)
        stop_btn.setVisible(can)
        if not can:
            return
        acquiring = bool(self.is_acquiring)
        start_btn.setEnabled(not acquiring)
        stop_btn.setEnabled(acquiring)

    def _sync_control_room_action_bar(self):
        """实时概览/能谱分析保留运行快捷；账户类动作统一收进设置页。"""
        if not hasattr(self, "button_container"):
            return
        self._sync_acq_action_buttons()
        logged = self.is_logged_in()
        cr = bool(getattr(self, "control_room_mode", False))
        page = 0
        if hasattr(self, "stacked_widget") and self.stacked_widget is not None:
            page = int(self.stacked_widget.currentIndex())

        def _btn_shown(name):
            btn = getattr(self, name, None)
            return btn is not None and not btn.isHidden()

        show_runtime_shortcut = bool(
            logged
            and page in (1, 2)
            and (
                _btn_shown("acquisition_btn")
                or _btn_shown("save_data_btn")
                or _btn_shown("start_acq_btn")
                or _btn_shown("stop_acq_btn")
            )
        )
        if cr:
            self.button_container.setVisible(show_runtime_shortcut)
            if logged:
                self._apply_control_room_ops_chrome()
            if hasattr(self, "status_bar") and hasattr(self.status_bar, "set_ops_buttons"):
                self.status_bar.set_ops_buttons(False, False, False)
        elif logged:
            self.button_container.setVisible(show_runtime_shortcut)
            if hasattr(self, "status_bar") and hasattr(self.status_bar, "set_ops_buttons"):
                self.status_bar.set_ops_buttons(False, False, False)
        else:
            self.button_container.setVisible(False)
            if hasattr(self, "status_bar") and hasattr(self.status_bar, "set_ops_buttons"):
                self.status_bar.set_ops_buttons(False, False, False)
        if hasattr(self, "bottom_nav") and self.bottom_nav is not None:
            self.bottom_nav.refresh_hit_areas()
            self.bottom_nav.updateGeometry()

    def _on_control_room_session_btn(self):
        if self.is_logged_in():
            self.logout()
        else:
            self.login(preferred_page=0)

    def _on_control_room_reorder(self, from_index, to_index):
        page = getattr(self, "home_page", None)
        if page is None or not hasattr(page, "reorder_probes"):
            return
        if not self.is_logged_in():
            if not self.login(preferred_page=0, required_for_page=True):
                return
        page.reorder_probes(from_index, to_index)
        self._sync_control_room_from_home()

    def _on_control_room_probe(self, client_id):
        if not self.is_logged_in():
            return
        self.open_probe_overview(client_id)

    def _apply_control_room_nav_labels(self):
        if not getattr(self, "control_room_mode", False):
            return
        if not hasattr(self, "bottom_nav") or not self.bottom_nav.button_widgets:
            return
        from core.translation import _t
        widget = self.bottom_nav.button_widgets[0]
        widget.text_label.setText(_t("nav_control_room"))
        if getattr(self.bottom_nav, "_active_index", -1) == 0:
            self.bottom_nav._apply_active_style(widget, widget.icon_tag, widget.theme_color)
        else:
            self.bottom_nav._apply_inactive_style(widget, widget.icon_tag)

    def _set_home_aux_card_border(self, card, bar, color=None):
        page = self.home_page
        if hasattr(page, "apply_aux_card_style"):
            page.apply_aux_card_style(card, bar, color)
            return
        if color:
            card.setStyleSheet("""
                QFrame {
                    background-color: #141519; border-radius: 8px;
                    border: 2px solid %s;
                }
            """ % color)
            bar.setStyleSheet("QFrame { background-color: %s; border-radius: 1px; }" % color)
        else:
            card.setStyleSheet("""
                QFrame {
                    background-color: #141519; border-radius: 8px;
                    border: 1px solid #252730;
                }
            """)
            bar.setStyleSheet("QFrame { background-color: #10B981; border-radius: 1px; }")

    def _master_fault_entries(self):
        faults = []
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None:
            return faults
        for code in (FaultCode.M101, FaultCode.M102, FaultCode.M103, FaultCode.M104):
            if code in (dm.active_faults.get(_MASTER_FAULT_CLIENT_ID, {}) or {}):
                faults.append(code)
        return faults

    def _sync_master_fault_logs(self):
        """主控故障边沿日志：进入/恢复都记。"""
        current = set(self._master_fault_entries())
        previous = set(getattr(self, "_prev_master_fault_codes", set()) or set())
        if current == previous:
            return

        latest = getattr(self, "latest_master_summary", None)
        # 系统/通信事件不写峰值 CPS（断线前末帧会误导成「测到辐射」）
        mid = int(getattr(latest, "master_id", 0) or 0) if latest is not None else 0

        try:
            from core.alarm_logger import get_alarm_logger
            alarm_logger = get_alarm_logger()
        except Exception:
            alarm_logger = None

        for code in sorted(current - previous):
            name, desc, severity, _ = FaultCode.get_info(code)
            desc_text = desc
            alarm_message = "%s %s" % (code, name)
            if code == FaultCode.M102:
                timeout_note = self._describe_last_tcp_timeout()
                if timeout_note:
                    desc_text = "%s | %s" % (desc, timeout_note)
                    alarm_message = "%s %s | %s" % (code, name, timeout_note)
            self.log(
                "[MASTER FAULT DETECTED] Code: %s | %s: %s" % (code, name, desc_text),
                severity,
            )
            if alarm_logger is not None:
                try:
                    alarm_logger.log_alarm_event(
                        client_id="master_fault_" + code,
                        alarm_status=True,
                        count_rate=0.0,
                        temperature=0.0,
                        hv=0.0,
                        product_id=mid,
                        sensitivity=0,
                        alarm_type="MasterFault",
                        message=alarm_message,
                    )
                except Exception:
                    pass

        for code in sorted(previous - current):
            name, _, _, _ = FaultCode.get_info(code)
            self.log(
                "[MASTER FAULT CLEARED] Code: %s | %s resolved" % (code, name),
                "INFO",
            )
            if alarm_logger is not None:
                try:
                    alarm_logger.log_alarm_event(
                        client_id="master_fault_" + code,
                        alarm_status=False,
                        count_rate=0.0,
                        temperature=0.0,
                        hv=0.0,
                        product_id=mid,
                        sensitivity=0,
                        alarm_type="MasterFault",
                        message="%s %s cleared" % (code, name),
                    )
                except Exception:
                    pass

        self._prev_master_fault_codes = current

    def _is_probe_comm_fault(self, client_id, code) -> bool:
        cid = str(client_id or "")
        if cid == _MASTER_FAULT_CLIENT_ID:
            return False
        master_cid = str(getattr(self, "master_client_id", "") or "")
        if master_cid and cid == master_cid:
            return False
        return str(code) in _PROBE_COMM_CODES

    def _probe_comm_entries(self):
        """当前活动的探头通信码（去重），供主控室「当前」行补全。"""
        codes = []
        seen = set()
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not hasattr(dm, "get_all_active_faults"):
            return codes
        try:
            for client_id, code, *_rest in dm.get_all_active_faults() or []:
                if not self._is_probe_comm_fault(client_id, code):
                    continue
                if code in seen:
                    continue
                seen.add(code)
                codes.append(code)
        except Exception:
            return codes
        return codes

    def _probe_comm_log_label(self, client_id: str, code: str) -> str:
        from core.translation import _t
        cid = str(client_id or "")
        if cid in ("system", "") or str(code) == FaultCode.E103:
            try:
                online, expected = self.probe_online_and_target()
                return _t("health_probe_online", online=online, expected=expected)
            except Exception:
                return _t("log_channel_device")
        parts = []
        try:
            lab = str(self.get_probe_label(cid) or "").strip()
            if lab:
                parts.append(lab)
        except Exception:
            pass
        try:
            loc = str(self._export_probe_location(cid) or "").strip()
            if loc:
                parts.append(loc)
        except Exception:
            pass
        if parts:
            return " ".join(parts)
        try:
            ip = str(self._extract_client_ip(cid) or "").strip()
            if ip:
                return ip
        except Exception:
            pass
        return cid or _t("log_channel_device")

    def _comm_standby(self) -> bool:
        """未接主控且无 TCP 客户端：开通待机，不算通信恢复。"""
        try:
            return bool(self._master_never_seen()) and int(self._tcp_client_count()) == 0
        except Exception:
            return False

    def _probe_comm_snapshot(self):
        keys = set()
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not hasattr(dm, "get_all_active_faults"):
            return keys
        try:
            for client_id, code, *_rest in dm.get_all_active_faults() or []:
                if self._is_probe_comm_fault(client_id, code):
                    keys.add((str(client_id), str(code)))
        except Exception:
            return keys
        return keys

    def _reset_probe_comm_logger(self, client_id, code):
        try:
            from core.alarm_logger import get_alarm_logger, probe_fault_log_id
            get_alarm_logger().reset_client_state(
                probe_fault_log_id(str(code), str(client_id))
            )
        except Exception:
            pass

    def _log_probe_comm_edge(self, client_id, code, active: bool):
        """探头 E101/E102/E103 边沿写入系统/通信历史，不进辐射统计。"""
        try:
            if not self._is_probe_comm_fault(client_id, code):
                return
            name, _, _, _ = FaultCode.get_info(code)
            label = self._probe_comm_log_label(client_id, code)
            alarm_message = "%s %s | %s" % (code, name, label)
            from core.alarm_logger import get_alarm_logger, probe_fault_log_id
            get_alarm_logger().log_alarm_event(
                client_id=probe_fault_log_id(str(code), str(client_id)),
                alarm_status=bool(active),
                count_rate=0.0,
                temperature=None,
                hv=None,
                product_id=None,
                sensitivity=None,
                alarm_type="ProbeFault",
                message=alarm_message,
            )
        except Exception:
            pass

    def _sync_probe_comm_logs(self):
        """按诊断表边沿落盘；不跟概览冷启动过滤，避免 E103 误记「已恢复」。"""
        try:
            if hasattr(self, "_sync_probe_count_fault"):
                self._sync_probe_count_fault()
        except Exception:
            pass
        try:
            current = self._probe_comm_snapshot()
            previous = set(getattr(self, "_prev_probe_comm_keys", set()) or set())
            if self._comm_standby():
                # 待机撤掉 E103：不是修好，不写恢复行
                e103 = ("system", str(FaultCode.E103))
                if e103 in previous and e103 not in current:
                    previous = set(previous)
                    previous.discard(e103)
                    self._reset_probe_comm_logger("system", FaultCode.E103)
            if current != previous:
                for cid, code in sorted(current - previous):
                    self._log_probe_comm_edge(cid, code, True)
                for cid, code in sorted(previous - current):
                    self._log_probe_comm_edge(cid, code, False)
            self._prev_probe_comm_keys = current
        except Exception:
            pass

    def _reset_fault_log_edges_on_start(self):
        """开采集会清空诊断表；边沿快照也要清，否则会把「表被清空」误记成链路已恢复。"""
        self._prev_master_fault_codes = set()
        self._prev_probe_comm_keys = set()
        try:
            from core.alarm_logger import get_alarm_logger, is_system_event_client
            logger = get_alarm_logger()
            for cid, active in list(logger.get_active_alarms().items()):
                if not active:
                    continue
                if is_system_event_client(cid):
                    logger.reset_client_state(cid)
        except Exception:
            pass

    def _settle_channel_hard_alarm_on_stop(self):
        """停采后不再有 L2，须结束通道硬报边沿，避免 KPI/角标长期假活动。"""
        if not bool(getattr(self, "_channel_hard_alarm_active", False)):
            return
        packet = getattr(self, "latest_master_summary", None)
        try:
            self._sync_channel_hard_alarm_log(False, packet)
        except Exception as e:
            self.log("Settle channel hard-alarm on stop failed: %s" % e, "WARNING")
            try:
                from core.alarm_logger import get_alarm_logger
                get_alarm_logger().reset_client_state("master_channel")
            except Exception:
                pass
            self._channel_hard_alarm_active = False

    def _release_probe_radiation_logs_for_master(self):
        """主控接管后不再写探头辐射位；清掉接管前卡住的探头 ACTIVE。"""
        try:
            if not self._skip_probe_radiation_log("probe"):
                return
            from core.alarm_logger import get_alarm_logger, is_system_event_client
            logger = get_alarm_logger()
            for cid, active in list(logger.get_active_alarms().items()):
                if not active:
                    continue
                if is_system_event_client(cid) or cid == "master_channel":
                    continue
                logger.reset_client_state(cid)
        except Exception:
            pass

    def start_acquisition(self, from_auto=False):
        ok = super().start_acquisition(from_auto=from_auto)
        if ok:
            self._reset_fault_log_edges_on_start()
        return ok

    def stop_acquisition(self, hold=False, clear_memory=None):
        self._settle_channel_hard_alarm_on_stop()
        return super().stop_acquisition(hold=hold, clear_memory=clear_memory)

    def _tcp_client_count(self) -> int:
        w = getattr(self, "worker", None)
        if w is None:
            return 0
        try:
            return len(getattr(w, "client_sockets", None) or {})
        except Exception:
            return 0

    def _update_master_diagnostics(self):
        """Inject master-related faults into the shared diagnostics table."""
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not getattr(dm, "is_acquiring", False) or not dm.acquisition_start_time:
            return
        now = time.time()
        startup_age = now - float(dm.acquisition_start_time or now)
        last_any = float(getattr(self, "_last_any_master_at", 0) or 0)
        last_sane = float(getattr(self, "_last_sane_master_at", 0) or 0)
        latest = getattr(self, "latest_master_summary", None)
        never_seen = last_any <= 0
        master_timeout_sec = float(
            getattr(dm, "MASTER_COMM_TIMEOUT_SEC", None) or dm.COMM_TIMEOUT_SEC
        )
        master_debounce_sec = float(
            getattr(dm, "MASTER_COMM_TIMEOUT_DEBOUNCE_SEC", None)
            or dm.COMM_TIMEOUT_DEBOUNCE_SEC
        )
        master_startup_grace_sec = float(
            getattr(dm, "MASTER_COMM_STARTUP_GRACE_SEC", 20.0) or 0.0
        )
        link_timeout = (not never_seen) and ((now - last_any) > master_timeout_sec)
        timeout_pending_since = float(getattr(self, "_master_timeout_pending_since", 0.0) or 0.0)
        # 只有认出主控（或同一主控 IP 重连）才算「应有 L2」。探头先连上不算。
        master_cid = None
        if hasattr(self, "_get_master_client_id"):
            master_cid = self._get_master_client_id()
        else:
            master_cid = getattr(self, "master_client_id", None)
        expect_master = bool(master_cid)
        if not expect_master:
            last_ip = str(getattr(self, "_last_master_ip", "") or "")
            infos = {}
            worker = getattr(self, "worker", None)
            if worker is not None:
                infos = getattr(worker, "client_infos", None) or {}
            if last_ip:
                for info in infos.values():
                    if str(getattr(info, "ip_address", "") or "") == last_ip:
                        expect_master = True
                        break
        # 开采集前 20s 不报 M101/M102，给主控上电和首包 L2 留时间
        master_startup_grace = startup_age < master_startup_grace_sec

        # M101/M102 互斥：从未收到过 → 只 M101；曾经有过再超时 → 只 M102
        if (
            never_seen
            and expect_master
            and not master_startup_grace
            and startup_age > dm.NO_DATA_STARTUP_SEC
        ):
            dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M101)
        else:
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M101)

        if (
            link_timeout
            and not master_startup_grace
            and not dm.comm_timeouts_suppressed(now)
        ):
            if timeout_pending_since <= 0:
                self._master_timeout_pending_since = now
                dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)
            elif (now - timeout_pending_since) >= master_debounce_sec:
                dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)
            else:
                dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)
        else:
            self._master_timeout_pending_since = 0.0
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)

        if last_any > 0 and (now - last_any) <= master_timeout_sec:
            if last_sane <= 0 or (now - last_sane) > master_timeout_sec:
                dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M103)
            else:
                dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M103)
        else:
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M103)

        if latest is not None and self.is_master_online() and int(latest.decision_result) == 0xFF:
            dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M104)
        else:
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M104)
        self._sync_master_fault_logs()

    def _update_home_health_and_faults(self):
        from core.translation import _t, TranslationManager

        if not hasattr(self, "home_page"):
            return
        lang = TranslationManager().current_lang
        page = self.home_page
        pkt = getattr(self, "latest_master_summary", None)
        master_online = bool(pkt is not None and self.is_master_online())
        never_seen = self._master_never_seen()
        n_clients = self._tcp_client_count()
        cold_standby = bool(never_seen and n_clients == 0 and not master_online)
        master_faults = self._master_fault_entries()
        probe_online, target = self.probe_online_and_target()
        ir_degraded_raw = bool(pkt is not None and getattr(pkt, "ir_degraded", False))
        sensor_unconfigured = False
        if pkt is not None and master_online:
            # 主控在线：传感器状态跟 L2 bit3/bit4/bit0
            from core.master_summary import (
                format_sensor_mode_brief,
                MASTER_SENSOR_MODE_UNCONFIGURED,
            )
            code = int(pkt.sensor_mode_code())
            pending_age = time.time() - float(getattr(self, "_pending_sensor_mode_at", 0) or 0)
            pending = 0 < pending_age <= 5.0
            acked = self._committed_sensor_mode(code)
            if acked not in (0, 1, 2):
                acked = code
            hold = bool(self._sensor_mode_hold_active())
            if not pending:
                if hold and acked != code:
                    # 0x19 已确认，但当前 L2 仍报旧模式：不要把下拉框刷回去
                    pass
                else:
                    self._master_sensor_mode = code
                    if hold and acked == code:
                        self._sensor_mode_ack_hold = False
                    if getattr(self, "_sensor_mode_dirty", False):
                        if self._selected_sensor_mode() == code:
                            self._sensor_mode_dirty = False
            ir_status = format_sensor_mode_brief(pkt, lang=lang)
            sensor_unconfigured = code == MASTER_SENSOR_MODE_UNCONFIGURED
            if self._occupancy_gate_suppressed() and code != 0:
                sensor_unconfigured = True
                ir_status = format_sensor_mode_brief(
                    pkt, lang=lang, mode_override=MASTER_SENSOR_MODE_UNCONFIGURED
                )
            if code == 0:
                from core.master_summary import format_ir_beam_states
                beams = format_ir_beam_states(pkt, lang=lang, only_blocked=True)
                if beams:
                    sep = "\u3001" if lang != "en" else ", "
                    ir_status = "%s %s" % (ir_status, sep.join(beams))
            if hold and acked != code:
                keys = {
                    0: "sensor_mode_ir",
                    1: "sensor_mode_radar",
                    2: "sensor_mode_unconfigured",
                }
                ir_status = _t(
                    "commission_status_l2_mismatch",
                    mode=_t(keys.get(acked, "sensor_mode_unconfigured")),
                    l2=_t(keys.get(code, "sensor_mode_unconfigured")),
                    io=int(getattr(pkt, "io_status", 0) or 0),
                    sys=int(getattr(pkt, "sys_mode", 0) or 0),
                )
                now_log = time.time()
                last_log = float(getattr(self, "_sensor_mode_mismatch_log_at", 0) or 0)
                if now_log - last_log >= 5.0:
                    self._sensor_mode_mismatch_log_at = now_log
                    self.log(
                        "Sensor mode L2 mismatch: ack=%s l2=%s io=0x%02X sys=0x%02X"
                        % (
                            acked,
                            code,
                            int(getattr(pkt, "io_status", 0) or 0),
                            int(getattr(pkt, "sys_mode", 0) or 0),
                        ),
                        "WARNING",
                    )
            if sensor_unconfigured or ir_degraded_raw or not bool(pkt.occ_gate_enabled):
                ir_tone = "amber"
            else:
                ir_tone = "green"
            ir_degraded = bool(ir_degraded_raw or sensor_unconfigured)
            self._sync_sensor_mode_ui(int(getattr(self, "_master_sensor_mode", code)))
            self._update_sensor_mode_status_label(pkt, lang=lang)
        elif never_seen:
            # 从未接入：健康卡与中间门口一致，勿写「离线」
            ir_status, ir_tone = _t("health_not_linked"), "muted"
            ir_degraded = False
        elif not master_online:
            ir_status, ir_tone = _t("master_offline"), "amber"
            ir_degraded = False
        elif ir_degraded_raw:
            ir_status, ir_tone = _t("health_ir_degraded"), "amber"
            ir_degraded = True
        else:
            ir_status, ir_tone = _t("health_ir_ok"), "green"
            ir_degraded = False

        self._sync_probe_count_fault()

        active_faults = getattr(self.diagnostics_manager, "get_all_active_faults", lambda: [])()
        unique_msgs = []
        probe_comm_fault = bool(target > 0 and probe_online < target)
        # 冷启动零探头：不算探头通信故障
        if never_seen and probe_online == 0:
            probe_comm_fault = False
        probe_hw_msgs = []
        _probe_comm_codes = (FaultCode.E101, FaultCode.E102, FaultCode.E103)
        for client_id, code, _, _, _, _ in active_faults:
            if cold_standby and (
                client_id == _MASTER_FAULT_CLIENT_ID
                or (client_id == "system" and code in _probe_comm_codes)
            ):
                continue
            msg = self.format_fault_home_message(client_id, code)
            if msg and msg not in unique_msgs:
                unique_msgs.append(msg)
            if client_id == _MASTER_FAULT_CLIENT_ID:
                continue
            if code in _probe_comm_codes:
                if not (never_seen and probe_online == 0):
                    probe_comm_fault = True
            elif msg and msg not in probe_hw_msgs:
                probe_hw_msgs.append(msg)

        # --- structured health KV rows for Web HMI ---
        if never_seen and probe_online == 0:
            probe_tone = "muted"
            probe_comm = _t("health_probe_await", online=probe_online, expected=target)
        else:
            probe_tone = "green" if (not probe_comm_fault and probe_online >= target and target > 0) else "amber"
            probe_comm = _t("health_probe_online", online=probe_online, expected=target)

        # 从未接入主控：健康总状态用「待接入」，不要「主控离线 / 探头通信故障」
        if never_seen and not master_online:
            page.health_indicator.load(get_icon_svg('occupancy_inactive'))
            page.health_status_label.setText(_t("status_health_await"))
            self._set_home_status_style(
                page.health_status_label, "#9e9e9e",
                "rgba(158, 158, 158, 0.12)", "rgba(158, 158, 158, 0.35)"
            )
            page.health_desc_label.setText(_t("desc_health_await"))
            master_hw, master_tone = _t("health_not_linked"), "muted"
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, None)
        elif master_faults:
            page.health_indicator.load(get_icon_svg('alarm_inactive'))
            offline_mf = FaultCode.M101 in master_faults or FaultCode.M102 in master_faults
            page.health_status_label.setText(
                _t("status_health_offline") if offline_mf else _t("status_health_fault")
            )
            reason = " / ".join(
                self.format_fault_home_message(_MASTER_FAULT_CLIENT_ID, code)
                for code in master_faults
            )
            if offline_mf:
                # Offline alone: no yellow card/tag — amber only on Master HW row.
                self._set_home_status_style(
                    page.health_status_label, "#4caf50",
                    "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
                )
                page.health_desc_label.setText(_t("desc_health_master_offline"))
                master_hw, master_tone = _t("health_master_offline"), "amber"
                self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, None)
            else:
                self._set_home_status_style(
                    page.health_status_label, "#ff9800",
                    "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
                )
                page.health_desc_label.setText(_t("desc_health_master_fault", reason=reason))
                master_hw, master_tone = _t("health_master_fault"), "amber"
                self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, "#ff9800")
        elif probe_comm_fault:
            page.health_indicator.load(get_icon_svg('alarm_inactive'))
            page.health_status_label.setText(_t("status_health_probe_comm"))
            self._set_home_status_style(
                page.health_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.health_desc_label.setText(
                _t("desc_health_probe_comm", online=probe_online, expected=target)
            )
            master_hw, master_tone = (
                (_t("health_master_ok"), "green") if master_online
                else (_t("health_master_offline"), "amber")
            )
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, "#ff9800")
        elif probe_hw_msgs:
            page.health_indicator.load(get_icon_svg('alarm_inactive'))
            page.health_status_label.setText(_t("status_health_fault"))
            self._set_home_status_style(
                page.health_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.health_desc_label.setText(
                _t("desc_health_probe_hw", reason=" / ".join(probe_hw_msgs[:2]))
            )
            master_hw, master_tone = _t("health_master_ok"), "green"
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, "#ff9800")
        elif ir_degraded:
            page.health_indicator.load(get_icon_svg('occupancy_active'))
            if sensor_unconfigured:
                page.health_status_label.setText(_t("status_health_sensor_cfg"))
                page.health_desc_label.setText(_t("desc_health_sensor_unconfigured"))
            else:
                page.health_status_label.setText(_t("status_health_degraded"))
                page.health_desc_label.setText(
                    _t("desc_health_master_degraded", online=probe_online, expected=target)
                )
            self._set_home_status_style(
                page.health_status_label, "#ffb74d",
                "rgba(255, 183, 77, 0.12)", "rgba(255, 183, 77, 0.35)"
            )
            master_hw, master_tone = _t("health_master_ok"), "green"
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, "#ffb74d")
        elif self.is_acq_hold_locked():
            page.health_indicator.load(get_icon_svg('occupancy_inactive'))
            page.health_status_label.setText(_t("status_acq_hold"))
            page.health_desc_label.setText(_t("desc_acq_hold"))
            self._set_home_status_style(
                page.health_status_label, "#ffb74d",
                "rgba(255, 183, 77, 0.12)", "rgba(255, 183, 77, 0.35)"
            )
            if master_online:
                master_hw, master_tone = _t("health_master_ok"), "green"
            elif never_seen:
                master_hw, master_tone = _t("health_not_linked"), "muted"
            else:
                master_hw, master_tone = _t("health_master_offline"), "amber"
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, "#ffb74d")
        else:
            page.health_indicator.load(get_icon_svg('occupancy_inactive'))
            page.health_status_label.setText(_t("status_health_ok"))
            self._set_home_status_style(
                page.health_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            page.health_desc_label.setText(
                _t("desc_health_master_ok", online=probe_online, expected=target)
            )
            if not master_online:
                master_hw, master_tone = _t("health_master_offline"), "amber"
            else:
                master_hw, master_tone = _t("health_master_ok"), "green"
            self._set_home_aux_card_border(page.health_card, page.health_indicator_bar, None)

        page._health_rows = {
            "probeComm": probe_comm,
            "probeTone": probe_tone,
            "irStatus": ir_status,
            "irTone": ir_tone,
            "masterHw": master_hw,
            "masterTone": master_tone,
        }

        n_fault = len(unique_msgs)

        if unique_msgs:
            text, tooltip = _format_fault_description(unique_msgs)
            page.fault_indicator.load(get_icon_svg('alarm_inactive'))
            page.fault_status_label.setText(_t("status_fault_count", n=n_fault))
            self._set_home_status_style(
                page.fault_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.fault_desc_label.setText(text)
            page.fault_desc_scroll.setToolTip(tooltip)
            self._set_home_aux_card_border(page.fault_card, page.fault_indicator_bar, "#ff9800")
            last_fault, last_tone = text, "amber"
        else:
            page.fault_indicator.load(get_icon_svg('occupancy_inactive'))
            page.fault_status_label.setText(_t("status_fault_count", n=0))
            self._set_home_status_style(
                page.fault_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            page.fault_desc_label.setText(_t("desc_fault_summary_none"))
            page.fault_desc_scroll.setToolTip("")
            self._set_home_aux_card_border(page.fault_card, page.fault_indicator_bar, None)
            last_fault, last_tone = _t("fault_none_pending"), ""

        page._fault_rows = {
            "lastFault": last_fault,
            "lastTone": last_tone,
        }

    def _refresh_home_from_probes(self, client_data=None):
        """Master offline/invalid L2: probe CPS + suspend channel hard-alarm."""
        from core.translation import TranslationManager

        lang = TranslationManager().current_lang
        page = self.home_page
        link_only = bool(getattr(self, "master_client_id", None)) and not self.is_master_online()
        page.set_master_link_status(
            False,
            lang=lang,
            link_only=link_only,
            never_seen=self._master_never_seen(),
        )
        page.master_relay_label.setText("--")
        self._apply_home_probe_cps(client_data)
        self._update_home_alarm_from_master(None, lang=lang, master_offline=True)
        self._update_home_occupancy(None, lang=lang, master_offline=True)
        self._update_home_health_and_faults()
        if getattr(self, "control_room_mode", False):
            self._refresh_control_room_snapshot()

    def on_master_summary_ui(self, packet, client_id=None):
        """Refresh home alarm/channel from Master L2; CPS stays on probe spectrum."""
        from core.translation import _t, TranslationManager
        from core.master_summary import MASTER_OFFLINE_TIMEOUT_SEC
        import time as _time

        lang = TranslationManager().current_lang
        page = self.home_page
        now = _time.time()
        master_cid = client_id or getattr(self, "master_client_id", None)

        # 本拍已解析到的包：报警状态必须跟本拍 decision，绝不能用旧 0x01 顶住新包
        display_pkt = None
        if packet is not None:
            display_pkt = packet
            if hasattr(packet, "looks_sane") and packet.looks_sane():
                self._last_sane_master_packet = packet
                self._last_sane_master_at = now
            self._last_any_master_packet = packet
            self._last_any_master_at = now
        else:
            # 仅超时无包时短时保持上一拍；有新包时不用旧包覆盖
            last_pkt = getattr(self, "_last_any_master_packet", None) or getattr(
                self, "_last_sane_master_packet", None
            )
            last_at = float(
                getattr(self, "_last_any_master_at", 0)
                or getattr(self, "_last_sane_master_at", 0)
                or 0
            )
            if last_pkt is not None and (now - last_at) <= MASTER_OFFLINE_TIMEOUT_SEC:
                display_pkt = last_pkt

        online = display_pkt is not None and (
            packet is not None or self.is_master_online()
            or (now - float(getattr(self, "_last_any_master_at", 0) or 0)) <= MASTER_OFFLINE_TIMEOUT_SEC
        )
        sane = bool(
            display_pkt is not None
            and hasattr(display_pkt, "looks_sane")
            and display_pkt.looks_sane()
        )
        link_only = bool(master_cid) and display_pkt is not None and not sane

        page.set_master_link_status(
            online and sane,
            getattr(display_pkt, "master_id", None) if display_pkt else None,
            lang=lang,
            link_only=link_only or (bool(master_cid) and display_pkt is None),
            never_seen=(not online) and self._master_never_seen(),
        )

        # 计数率始终跟探头
        self._apply_home_probe_cps(self.client_data)

        if display_pkt is None:
            page.master_relay_label.setText("--")
            self._update_home_alarm_from_master(None, lang=lang, master_offline=True)
            self._update_home_occupancy(None, lang=lang, master_offline=True)
            self._update_overview_occupancy_from_master(None, master_offline=True)
            self._update_settings_occupancy_from_master(None, master_offline=True)
            if getattr(self, "control_room_mode", False):
                self._refresh_control_room_snapshot()
            return

        # decision 边沿日志，便于确认主控是否已离开 0x01
        prev = getattr(self, "_prev_master_decision", None)
        cur = int(display_pkt.decision_result)
        if prev is None or prev != cur:
            self._prev_master_decision = cur
            self.log(
                "Master decision 0x%02X → 0x%02X (%s) hit_mask=0x%04X relay_mask=0x%02X"
                % (
                    int(prev if prev is not None else 0xFE),
                    cur,
                    display_pkt.decision_detail_text("zh"),
                    int(display_pkt.hit_probe_mask),
                    int(getattr(display_pkt, "relay_mask", 0) or 0),
                ),
                "INFO",
            )

        # 继电器 UI 跟 L2 io_status bit4/5/6
        r0 = int(bool(display_pkt.relay0))
        r1 = int(bool(display_pkt.relay1))
        r2 = int(bool(display_pkt.relay2))
        page.master_relay_label.setText(
            "%s: 0=%s 1=%s 2=%s"
            % (
                _t("card_status_relay"),
                _t("master_relay_on") if r0 else _t("master_relay_off"),
                _t("master_relay_on") if r1 else _t("master_relay_off"),
                _t("master_relay_on") if r2 else _t("master_relay_off"),
            )
        )
        self._sync_master_relay_ui_from_l2(display_pkt)
        # 有本拍 L2 就刷新报警区（即使 looks_sane=False，decision 仍以本拍为准）
        self._update_home_alarm_from_master(display_pkt, lang=lang)
        self._update_home_occupancy(display_pkt, lang=lang)
        self._update_overview_occupancy_from_master(display_pkt)
        self._update_settings_occupancy_from_master(display_pkt)
        self._update_home_health_and_faults()
        if getattr(self, "control_room_mode", False):
            self._refresh_control_room_snapshot()

    def _sync_master_relay_ui_from_l2(self, packet):
        """设置页主控继电器勾选/状态跟 L2 bit4/5/6（有 pending 命令时跳过，避免打架）。"""
        if not hasattr(self, "master_relay_status_label"):
            return
        pending = float(getattr(self, "_pending_master_relay_cmd", 0) or 0)
        if pending > 0 and (time.time() - pending) < 2.0:
            return
        mask = int(getattr(packet, "relay_mask", 0) or 0)
        if hasattr(self, "_apply_master_relay_mask_to_ui"):
            self._apply_master_relay_mask_to_ui(mask)

    def _any_probe_tcp_alarm(self) -> bool:
        """True if any non-master probe spectrum reports alarm latch/hard bit."""
        master_cid = getattr(self, "master_client_id", None)
        for cid, d in (getattr(self, "client_data", None) or {}).items():
            if master_cid and cid == master_cid:
                continue
            if bool(d.get("alarm", False)):
                return True
        return False

    def _set_home_status_style(self, label, color, bg, border):
        page = self.home_page
        if hasattr(page, "apply_status_label_style"):
            # Web 主页：不再画胶囊描边，保持文字一体
            page.apply_status_label_style(label, color, "transparent", "transparent")
            return
        label.setStyleSheet("""
            QLabel {
                color: %s; font-size: 16px; font-weight: bold;
                margin-top: 2px; background: transparent; border: none;
            }
        """ % color)

    def _set_overview_status_text(self, label, color: str):
        """概览状态字：纯色文字，无胶囊框，避免与计数率/温度卡割裂。"""
        label.setStyleSheet("""
            QLabel {
                color: %s;
                font-size: 16px;
                font-weight: bold;
                margin-top: 2px;
                background: transparent;
                border: none;
            }
        """ % color)

    def _set_overview_card_shell(self, card, accent=None):
        card.setObjectName("overviewCard")
        if accent:
            card.setStyleSheet("""
                QFrame#overviewCard {
                    background-color: #2a2a2a;
                    border-radius: 10px;
                    border: 2px solid %s;
                }
                QFrame#overviewCard QLabel {
                    background: transparent;
                    border: none;
                }
            """ % accent)
        else:
            card.setStyleSheet("""
                QFrame#overviewCard {
                    background-color: #2a2a2a;
                    border-radius: 10px;
                    border: none;
                }
                QFrame#overviewCard QLabel {
                    background: transparent;
                    border: none;
                }
            """)

    def _set_overview_accent_bar(self, bar, color: str):
        bar.setObjectName("cardAccentBar")
        bar.setStyleSheet(
            "QFrame#cardAccentBar { background-color: %s; border: none; border-radius: 1px; }"
            % color
        )

    def _set_home_alarm_card_border(self, color=None):
        page = self.home_page
        if hasattr(page, "apply_alarm_banner_style"):
            page.apply_alarm_banner_style(color)
            return
        if color:
            page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a; border-radius: 10px;
                    border: 2px solid %s;
                }
            """ % color)
            page.status_indicator_bar.setStyleSheet(
                "QFrame { background-color: %s; border-radius: 1px; border: none; }" % color
            )
        else:
            page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a; border-radius: 10px;
                    border: none;
                }
            """)
            page.status_indicator_bar.setStyleSheet(
                "QFrame { background-color: #4caf50; border-radius: 1px; border: none; }"
            )

    def _update_home_alarm_from_master(self, packet, lang="zh", master_offline=False):
        """Home alarm follows master L2 decision.

        硬报 UI：0x02（滑动窗：未配置降级符合，或雷达占用期间符合）/
        0x03（对射窗符合，只对射）进入。
        0x01 仅黄提示（未达 N 路，不是硬报）；未配置没有 0x04。
        """
        from core.translation import _t
        from core.master_summary import (
            MASTER_DECISION_OVER_THRESHOLD,
            MASTER_DECISION_WINDOW_MATCHED,
            MASTER_DECISION_JOINT_ALARM,
        )
        import time as _time

        page = self.home_page
        current_time = datetime.now().strftime("%H:%M:%S")
        reset_btn = getattr(page, "channel_reset_btn", None)

        if master_offline or packet is None:
            self._over_thresh_probes_clear_since = None
            self._over_thresh_soft_cleared = False
            if reset_btn is not None:
                reset_btn.setEnabled(False)
            if hasattr(page, "set_alarm_kind"):
                page.set_alarm_kind("offline")
            if hasattr(page, "set_channel_reset_alarm_active"):
                page.set_channel_reset_alarm_active(False)
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_rad_offline"))
            self._set_home_status_style(
                page.alarm_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.alarm_desc_label.setText(_t("desc_master_offline"))
            self._set_home_alarm_card_border("#ff9800")
            self._apply_home_latch_status(page, hard_alarm=False, latch_mode=False, offline=True)
            if hasattr(page, "sync_side_rad_from_alarm"):
                page.sync_side_rad_from_alarm(_t("status_rad_offline"), False)
            self._sync_channel_hard_alarm_log(False, None)
            return

        kind = packet.ui_alarm_kind()
        latch_mode = bool(getattr(packet, "alarm_latch_mode", False))
        self._master_alarm_latch_mode = latch_mode
        self._sync_alarm_clear_mode_ui(latch_mode)
        hit_mask = int(getattr(packet, "hit_probe_mask", 0) or 0)
        desc = _t("desc_master_alarm", decision=packet.decision_text(lang), time=current_time)
        if packet.relay_output and kind == "channel_alarm":
            desc = "%s | %s" % (desc, _t("desc_relay_hold"))
        ir_deg = self._ir_degraded_ui(packet)
        if kind == "channel_alarm" and ir_deg:
            desc = "%s | %s" % (desc, _t("desc_ir_degraded"))

        soft_cleared = False
        # Soft-clear 0x01 only when occupancy gating is actually enabled.
        # Unconfigured stays on 0x01 until ≥N probes match → 0x02 (not 0x03).
        # Radar occupancy match is also 0x02; 0x03 is IR-window only.
        # Hiding 0x01 makes a single-probe source test look insensitive.
        probes_clear = (not self._any_probe_tcp_alarm()) and (hit_mask == 0)
        ungated = False
        try:
            ungated = (
                int(packet.sensor_mode_code()) == 2
                or bool(getattr(packet, "ir_degraded", False))
                or (not bool(getattr(packet, "occ_gate_enabled", False)))
            )
        except Exception:
            ungated = False
        if (
            kind == "over_threshold"
            and int(packet.decision_result) == MASTER_DECISION_OVER_THRESHOLD
            and probes_clear
            and not ungated
        ):
            t0 = getattr(self, "_over_thresh_probes_clear_since", None)
            now = _time.time()
            if t0 is None:
                self._over_thresh_probes_clear_since = now
            elif (now - float(t0)) >= 2.0:
                if not getattr(self, "_over_thresh_soft_cleared", False):
                    self._over_thresh_soft_cleared = True
                    self.log(
                        "Soft-clear over-threshold UI: decision still 0x01, "
                        "probes clear and hit_mask=0",
                        "INFO",
                    )
                # 不伪装成 normal：保留超阈语义，仅弱化显示
                kind = "soft_cleared"
                desc = _t("desc_over_thresh_soft_clear")
        else:
            self._over_thresh_probes_clear_since = None
            self._over_thresh_soft_cleared = False

        # 先写 kind，避免中途 web flush 出现「● 离线 + 系统正常」
        if hasattr(page, "set_alarm_kind"):
            if kind == "channel_alarm":
                page.set_alarm_kind("channel_alarm")
            elif kind in ("over_threshold", "soft_cleared", "fault", "acked"):
                page.set_alarm_kind(kind)
            else:
                page.set_alarm_kind("normal")

        pending_reset = (
            float(getattr(self, "_pending_channel_reset_at", 0) or 0) > 0
            or bool(getattr(self, "_awaiting_l2_acked", False))
        )
        # 仅硬报时可点复位；等待应答 / 等 L2=0x05 期间保持禁用
        if reset_btn is not None:
            reset_btn.setEnabled(kind == "channel_alarm" and not pending_reset)
        if hasattr(page, "set_channel_reset_alarm_active"):
            page.set_channel_reset_alarm_active(kind == "channel_alarm")
        self._apply_home_latch_status(
            page, hard_alarm=(kind == "channel_alarm"), latch_mode=latch_mode
        )

        if kind == "channel_alarm":
            page.alarm_title_icon.load(get_icon_svg('alarm_active'))
            page.alarm_indicator.load(get_icon_svg('alarm_active'))
            d = int(getattr(packet, "decision_result", 0) or 0)
            if d == MASTER_DECISION_WINDOW_MATCHED:
                page.alarm_status_label.setText(_t("status_channel_alarm_window"))
            elif d == MASTER_DECISION_JOINT_ALARM:
                page.alarm_status_label.setText(_t("status_channel_alarm_ir"))
            elif ir_deg:
                page.alarm_status_label.setText(_t("status_channel_alarm_degraded"))
            else:
                page.alarm_status_label.setText(_t("status_channel_alarm"))
            self._set_home_status_style(
                page.alarm_status_label, "#ff4444",
                "rgba(255, 68, 68, 0.15)", "rgba(255, 68, 68, 0.4)"
            )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#ff4444")
            if hasattr(page, "sync_side_rad_from_alarm"):
                page.sync_side_rad_from_alarm(page.alarm_status_label.text(), True)
            self._sync_channel_hard_alarm_log(True, packet)
            probes = self._format_hit_probes_for_log(
                packet, mask=int(getattr(self, "_channel_hard_alarm_hit_mask", 0) or 0)
            )
            if probes:
                page.alarm_desc_label.setText("%s | %s" % (desc, probes))
        elif kind == "acked":
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_acked"))
            self._set_home_status_style(
                page.alarm_status_label, "#7e57c2",
                "rgba(126, 87, 194, 0.15)", "rgba(126, 87, 194, 0.4)"
            )
            if hit_mask != 0:
                page.alarm_desc_label.setText(_t("desc_acked_still_hot", mask=hit_mask))
            else:
                page.alarm_desc_label.setText(
                    "%s | %s" % (_t("desc_acked"), desc)
                )
            self._set_home_alarm_card_border("#7e57c2")
            self._sync_channel_hard_alarm_log(False, packet)
            # 收到 0x05：关硬报 + 写审计
            if getattr(self, "_awaiting_l2_acked", False) or getattr(
                self, "_channel_reset_audit_snap", None
            ):
                self._write_channel_reset_audit(packet, source="l2_0x05")
            self._awaiting_l2_acked = False
            self._awaiting_l2_acked_at = 0.0
            self._pending_channel_reset_at = 0.0
        elif kind == "passing":
            self._release_channel_reset_await_if_cleared(packet, source="l2_passing")
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('occupancy_active'))
            page.alarm_status_label.setText(_t("status_passing"))
            self._set_home_status_style(
                page.alarm_status_label, "#2196f3",
                "rgba(33, 150, 243, 0.15)", "rgba(33, 150, 243, 0.4)"
            )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#2196f3")
            self._sync_channel_hard_alarm_log(False, packet)
        elif kind == "over_threshold":
            self._release_channel_reset_await_if_cleared(packet, source="l2_over_threshold")
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_over_threshold"))
            self._set_home_status_style(
                page.alarm_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            try:
                need_n = int(getattr(packet, "match_threshold_n", 0) or 0)
            except (TypeError, ValueError):
                need_n = 0
            hit_n = bin(hit_mask & 0xFFFF).count("1")
            if need_n > 0:
                desc = "%s | %s" % (
                    desc,
                    _t("desc_over_thresh_need_n", hit=hit_n, n=need_n),
                )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#ff9800")
            self._sync_channel_hard_alarm_log(False, packet)
        elif kind == "soft_cleared":
            self._release_channel_reset_await_if_cleared(packet, source="l2_soft_cleared")
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_over_thresh_soft"))
            self._set_home_status_style(
                page.alarm_status_label, "#ffb74d",
                "rgba(255, 183, 77, 0.14)", "rgba(255, 183, 77, 0.4)"
            )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#ffb74d")
            self._sync_channel_hard_alarm_log(False, packet)
        elif kind == "fault":
            self._release_channel_reset_await_if_cleared(packet, source="l2_fault")
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_sys_fault"))
            self._set_home_status_style(
                page.alarm_status_label, "#9e9e9e",
                "rgba(158, 158, 158, 0.15)", "rgba(158, 158, 158, 0.4)"
            )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#9e9e9e")
            self._sync_channel_hard_alarm_log(False, packet)
        else:
            self._release_channel_reset_await_if_cleared(packet, source="l2_normal")
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_normal"))
            self._set_home_status_style(
                page.alarm_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            page.alarm_desc_label.setText(self._io_brief(packet, lang))
            self._set_home_alarm_card_border(None)
            self._sync_channel_hard_alarm_log(False, packet)

        if hasattr(page, "sync_side_rad_from_alarm") and kind != "channel_alarm":
            page.sync_side_rad_from_alarm(
                page.alarm_status_label.text(),
                kind in ("over_threshold", "soft_cleared", "fault"),
            )

    def _probe_slot_label(self, index: int) -> str:
        try:
            loc = str(self.home_page._slot_location(index) or "").strip()
        except Exception:
            loc = ""
        if loc:
            return loc
        from core.translation import _t
        return _t("probe_slot_name", n=index + 1)

    def _format_probe_parts(self, indices, packet=None) -> str:
        parts = []
        probe_cps = []
        try:
            probe_cps = list(getattr(packet, "probe_cps", None) or []) if packet is not None else []
        except Exception:
            probe_cps = []
        seen = set()
        for i in indices:
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if i < 0 or i > 15 or i in seen:
                continue
            seen.add(i)
            cps = 0
            if i < len(probe_cps):
                try:
                    cps = int(probe_cps[i] or 0)
                except (TypeError, ValueError):
                    cps = 0
            label = self._probe_slot_label(i)
            if cps > 0:
                parts.append("%s %d cps" % (label, cps))
            else:
                parts.append(label)
        return "、".join(parts)

    def _infer_hit_indices(self, packet=None, mask=0):
        """hit_mask 优先；0 时用首页 hit 标记，再退到在线且有计数的槽位。"""
        mask = int(mask or 0)
        if mask:
            return [i for i in range(16) if mask & (1 << i)]
        hits = []
        try:
            for i, e in enumerate(getattr(self.home_page, "_probe_entries", None) or []):
                if e.get("hit"):
                    hits.append(i)
        except Exception:
            hits = []
        if hits:
            return hits
        if packet is None:
            return []
        probe_cps = list(getattr(packet, "probe_cps", None) or [])
        online = int(getattr(packet, "online_mask", 0) or 0)
        n = 0
        try:
            n = int(packet.active_probe_count() or 0)
        except Exception:
            n = 0
        n = max(n, len(probe_cps), 2)
        n = min(n, 16)
        ranked = []
        for i in range(n):
            if online and not (online & (1 << i)):
                continue
            cps = 0
            if i < len(probe_cps):
                try:
                    cps = int(probe_cps[i] or 0)
                except (TypeError, ValueError):
                    cps = 0
            if cps > 0:
                ranked.append((cps, i))
        ranked.sort(reverse=True)
        if not ranked:
            return []
        top = ranked[0][0]
        # 窗符合/降级时常不带 hit_mask：把明显偏高的几路写进设备列
        return [i for cps, i in ranked if cps >= max(1, int(top * 0.35))][:4]

    def _reuse_active_channel_probes(self) -> str:
        try:
            from core.alarm_logger import get_alarm_logger
            for ev in reversed(get_alarm_logger().get_recent_events(20) or []):
                if getattr(ev, "client_id", "") != "master_channel":
                    continue
                if not getattr(ev, "alarm_status", False):
                    continue
                msg = str(getattr(ev, "message", "") or "")
                if " | " in msg:
                    probes = msg.split(" | ", 1)[0].strip()
                    if probes:
                        return probes
                break
        except Exception:
            pass
        return ""

    def _format_hit_probes_for_log(self, packet=None, mask=None) -> str:
        """主控 hit_mask 槽位 bit → 名称。bit0=第1路。mask=0 不写「未标明」，改推断或写通道。"""
        if mask is None:
            mask = int(getattr(packet, "hit_probe_mask", 0) or 0) if packet is not None else 0
        indices = self._infer_hit_indices(packet, mask=int(mask or 0))
        text = self._format_probe_parts(indices, packet)
        if text:
            return text
        cached = str(getattr(self, "_channel_hard_alarm_probes_text", "") or "").strip()
        if cached:
            return cached
        reused = self._reuse_active_channel_probes()
        if reused:
            return reused
        from core.translation import _t
        total = 0
        if packet is not None:
            try:
                total = int(getattr(packet, "total_cps", 0) or 0)
            except (TypeError, ValueError):
                total = 0
        if total > 0:
            return "%s %d cps" % (_t("log_channel_device"), total)
        return _t("log_channel_device")

    def _latch_hard_alarm_hit_mask(self, active: bool, packet=None) -> int:
        """硬报期间锁存 hit_mask：升起时拍照，之后只或上新出现的 bit，恢复后清掉。"""
        latched = int(getattr(self, "_channel_hard_alarm_hit_mask", 0) or 0)
        if not active:
            return latched
        cur = int(getattr(packet, "hit_probe_mask", 0) or 0) if packet is not None else 0
        if not bool(getattr(self, "_channel_hard_alarm_active", False)):
            self._channel_hard_alarm_hit_mask = cur
        elif cur:
            self._channel_hard_alarm_hit_mask = latched | cur
        return int(getattr(self, "_channel_hard_alarm_hit_mask", 0) or 0)

    def _hard_alarm_decision_text(self, packet) -> str:
        """只取 0x02/0x03 硬报判决；0x01 超阈等退出态不能当历史原因。"""
        from core.master_summary import (
            MASTER_DECISION_WINDOW_MATCHED,
            MASTER_DECISION_JOINT_ALARM,
        )
        if packet is None:
            return ""
        try:
            d = int(getattr(packet, "decision_result", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if d not in (MASTER_DECISION_WINDOW_MATCHED, MASTER_DECISION_JOINT_ALARM):
            return ""
        lang = "zh"
        try:
            from core.translation import TranslationManager
            lang = TranslationManager().current_lang
        except Exception:
            pass
        try:
            return packet.decision_text(lang)
        except Exception:
            return "0x%02X" % d

    def _channel_hard_alarm_log_message(self, packet, mask=None, latch_decision=False) -> str:
        cached_probes = str(getattr(self, "_channel_hard_alarm_probes_text", "") or "").strip()
        if latch_decision:
            probes = self._format_hit_probes_for_log(packet, mask=mask)
            if probes:
                self._channel_hard_alarm_probes_text = probes
            else:
                probes = cached_probes
            text = self._hard_alarm_decision_text(packet)
            if text:
                self._channel_hard_alarm_decision_text = text
        else:
            # 恢复行不要用退出包的 CPS/0x01 文案覆盖锁存值
            probes = cached_probes
            if not probes:
                probes = self._format_hit_probes_for_log(packet, mask=mask)
        decision = str(getattr(self, "_channel_hard_alarm_decision_text", "") or "").strip()
        if not decision:
            decision = self._hard_alarm_decision_text(packet)
        return "%s | %s" % (probes, decision)

    def _sync_channel_hard_alarm_log(self, active: bool, packet=None):
        """边沿写入通道符合硬报。设备列与判决文案用升起时锁存值，不用恢复那一包。"""
        prev = bool(getattr(self, "_channel_hard_alarm_active", False))
        mask = self._latch_hard_alarm_hit_mask(bool(active), packet)
        msg = self._channel_hard_alarm_log_message(
            packet, mask=mask, latch_decision=bool(active)
        )
        if prev == bool(active):
            if active and packet is not None:
                try:
                    from core.alarm_logger import get_alarm_logger
                    get_alarm_logger().log_alarm_event(
                        client_id="master_channel",
                        alarm_status=True,
                        count_rate=float(getattr(packet, "total_cps", 0) or 0),
                        temperature=None,
                        hv=None,
                        product_id=None,
                        sensitivity=None,
                        alarm_type="ChannelMatch",
                        message=msg,
                    )
                except Exception:
                    pass
            self._refresh_alarm_log_nav_badge(radiation_alarm=bool(active))
            return
        self._channel_hard_alarm_active = bool(active)
        try:
            from core.alarm_logger import get_alarm_logger
            cps = float(getattr(packet, "total_cps", 0) or 0) if packet else 0.0
            decision = int(getattr(packet, "decision_result", 0) or 0) if packet else 0
            get_alarm_logger().log_alarm_event(
                client_id="master_channel",
                alarm_status=bool(active),
                count_rate=cps,
                temperature=None,
                hv=None,
                product_id=None,
                sensitivity=None,
                alarm_type="ChannelMatch",
                message=msg,
            )
            self.log(
                "Channel hard-alarm %s (decision=0x%02X hit_mask=0x%04X cps=%d probes=%s)"
                % ("ACTIVE" if active else "CLEAR", decision, mask, int(cps), msg),
                "WARNING" if active else "INFO",
            )
        except Exception as e:
            self.log("Channel hard-alarm log failed: %s" % e, "ERROR")
        if not active:
            self._channel_hard_alarm_hit_mask = 0
            self._channel_hard_alarm_probes_text = ""
            self._channel_hard_alarm_decision_text = ""
        self._refresh_alarm_log_nav_badge(radiation_alarm=bool(active))

    def _apply_home_latch_status(self, page, hard_alarm=False, latch_mode=False, offline=False):
        """Home「报警锁存」文案：跟 L2 sys_mode.bit2 + 是否硬报。"""
        from core.translation import _t

        if offline:
            text = _t("latch_none")
            color = "#DDD"
        elif hard_alarm and latch_mode:
            text = _t("latch_pending", n=1)
            color = "#FF4D4D"
        elif hard_alarm and not latch_mode:
            text = _t("latch_auto_hold")
            color = "#F59E0B"
        elif latch_mode:
            text = _t("latch_mode_latch")
            color = "#DDD"
        else:
            text = _t("latch_mode_auto")
            color = "#DDD"
        if hasattr(page, "alarm_latch_status"):
            page.alarm_latch_status.setText(text)
            try:
                page.alarm_latch_status.setStyleSheet("color: %s;" % color)
            except Exception:
                pass
        page._alarm_latch_text = text
        page._alarm_clear_mode_latch = bool(latch_mode)
        if hasattr(page, "schedule_web_flush"):
            page.schedule_web_flush()

    def _sync_alarm_clear_mode_ui(self, latch_mode: bool):
        """Keep settings combo aligned with L2 sys_mode.bit2."""
        combo = getattr(self, "alarm_clear_mode_combo", None)
        if combo is None:
            return
        want = 1 if latch_mode else 0
        if int(combo.currentData()) == want:
            return
        combo.blockSignals(True)
        idx = combo.findData(want)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def on_alarm_clear_mode_combo_changed(self, _index=None):
        """Settings: switch master alarm clear mode via 0x16."""
        combo = getattr(self, "alarm_clear_mode_combo", None)
        if combo is None:
            return
        mode = int(combo.currentData())
        if not self.check_permission_before_action(
            "Set alarm clear mode", Permission.MODIFY_DETECTOR_SETTINGS
        ):
            # revert to last known L2 mode
            self._sync_alarm_clear_mode_ui(
                bool(getattr(self, "_master_alarm_latch_mode", False))
            )
            return
        self.set_master_alarm_clear_mode(latch=(mode == 1))

    def set_master_alarm_clear_mode(self, latch: bool):
        """PC → 主控 0x16 切换消警模式（0=自动，1=锁存）。"""
        from core.translation import _t

        if not bool(getattr(self.config, "tcp_enabled", False)):
            show_warn(self, _t("msg_clear_mode_title"), _t("msg_clear_mode_need_master"))
            return False
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if not master_cid or not hasattr(self, "worker") or self.worker is None:
            show_warn(self, _t("msg_clear_mode_title"), _t("msg_clear_mode_need_master"))
            return False
        if not hasattr(self.worker, "send_command_to_client"):
            return False
        mode = 1 if latch else 0
        ok = self.worker.send_command_to_client(
            master_cid,
            "channel_alarm_clear_mode",
            mode,
            description="Set alarm clear mode %s (0x16)" % ("LATCH" if latch else "AUTO"),
        )
        if ok:
            self._pending_alarm_clear_mode_at = time.time()
            self.log(
                "Alarm clear mode 0x16 set → %s" % ("LATCH" if latch else "AUTO"),
                "INFO",
            )
        return bool(ok)

    def read_master_alarm_clear_mode(self):
        """PC → 主控 0x16 FF 读消警模式。"""
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if not master_cid or not hasattr(self, "worker") or self.worker is None:
            return False
        if not hasattr(self.worker, "send_command_to_client"):
            return False
        return bool(
            self.worker.send_command_to_client(
                master_cid,
                "channel_alarm_clear_mode",
                0xFF,
                description="Read alarm clear mode (0x16)",
            )
        )

    def on_alarm_clear_mode_feedback(self, packet):
        """主控 CmdFeedback control_code=0x16。"""
        from core.translation import _t

        self._pending_alarm_clear_mode_at = 0.0
        if int(getattr(packet, "status", 0) or 0) != 1:
            self.log("Alarm clear mode 0x16 rejected", "WARNING")
            show_warn(self, _t("msg_clear_mode_title"), _t("msg_clear_mode_fail"))
            return
        mode = int(getattr(packet, "value", 0) or 0) & 0xFF
        latch = mode == 1
        self._master_alarm_latch_mode = latch
        self._sync_alarm_clear_mode_ui(latch)
        page = getattr(self, "home_page", None)
        if page is not None:
            hard = bool(getattr(page, "_reset_alarm_active", False))
            self._apply_home_latch_status(page, hard_alarm=hard, latch_mode=latch)
        self.log(
            "Alarm clear mode ack → %s (value=%d)" % ("LATCH" if latch else "AUTO", mode),
            "INFO",
        )

    def _sensor_mode_hold_active(self) -> bool:
        """0x19 应答后锁住下拉，直到 L2 跟上。未配置不能超时后用旧对射 L2 把空闲否决画回来。"""
        if not bool(getattr(self, "_sensor_mode_ack_hold", False)):
            return False
        acked = self._committed_sensor_mode(2)
        if acked == 2:
            return True
        until = float(getattr(self, "_sensor_mode_ack_hold_until", 0) or 0)
        if until > 0 and time.time() >= until:
            self._sensor_mode_ack_hold = False
            return False
        return True

    def _occupancy_gate_suppressed(self) -> bool:
        """本次会话已确认未配置：丢掉上一轮对射/雷达的空闲否决画面。

        上位机不写探头 0x0078。未配置后若仍按旧 L2 bit4 去画占用，会看起来像
        空闲否决还在生效。关软件再开等于清掉这条缓存。
        """
        if bool(getattr(self, "_sensor_mode_ack_unconfigured", False)):
            return True
        pkt = getattr(self, "latest_master_summary", None)
        if pkt is None:
            return False
        try:
            return int(pkt.sensor_mode_code()) == 2
        except Exception:
            return False

    def _sync_sensor_mode_ui(self, mode_code: int):
        """Keep settings combo aligned with L2 推断 / 0x19 应答。"""
        combo = getattr(self, "sensor_mode_combo", None)
        if combo is None:
            return
        if getattr(self, "_sensor_mode_dirty", False):
            return
        pending_age = time.time() - float(getattr(self, "_pending_sensor_mode_at", 0) or 0)
        if 0 < pending_age <= 5.0:
            return
        try:
            want = int(mode_code)
        except (TypeError, ValueError):
            want = 2
        if want not in (0, 1, 2):
            want = 2
        if combo.currentData() is not None and int(combo.currentData()) == want:
            return
        combo.blockSignals(True)
        idx = combo.findData(want)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _committed_sensor_mode(self, fallback: int = 2) -> int:
        """当前已确认的传感器模式。对射=0，不能用 `or` 回退。"""
        try:
            mode = int(getattr(self, "_master_sensor_mode", fallback))
        except (TypeError, ValueError):
            return fallback
        return mode if mode in (0, 1, 2) else fallback

    def _selected_sensor_mode(self) -> int:
        combo = getattr(self, "sensor_mode_combo", None)
        if combo is None or combo.currentData() is None:
            return 2
        try:
            mode = int(combo.currentData())
        except (TypeError, ValueError):
            return 2
        return mode if mode in (0, 1, 2) else 2

    def _refresh_commissioning_status(self, packet=None, lang="zh"):
        from core.translation import _t

        label = getattr(self, "commission_status_label", None)
        if label is None:
            return
        keys = {
            0: "sensor_mode_ir",
            1: "sensor_mode_radar",
            2: "sensor_mode_unconfigured",
        }
        selected = self._selected_sensor_mode()
        pending_age = time.time() - float(getattr(self, "_pending_sensor_mode_at", 0) or 0)
        pending = 0 < pending_age <= 5.0
        master_online = False
        try:
            master_online = bool(self.is_master_online() and packet is not None)
        except Exception:
            master_online = False

        if pending:
            label.setText(_t("commission_status_pending"))
            label.setStyleSheet("color: #888888; font-size: 12px; font-weight: bold;")
            return
        if getattr(self, "_sensor_mode_dirty", False):
            label.setText(_t("commission_status_dirty", mode=_t(keys[selected])))
            label.setStyleSheet("color: #ffb74d; font-size: 12px; font-weight: bold;")
            return
        if not master_online:
            label.setText(_t("commission_status_need_master"))
            label.setStyleSheet("color: #888888; font-size: 12px; font-weight: bold;")
            return
        try:
            code = int(packet.sensor_mode_code())
        except Exception:
            code = 2
        gate_ok = bool(getattr(packet, "occ_gate_enabled", False))
        acked = self._committed_sensor_mode(code)
        if (
            self._sensor_mode_hold_active()
            and acked in (0, 1, 2)
            and acked != code
        ):
            label.setText(
                _t(
                    "commission_status_l2_mismatch",
                    mode=_t(keys.get(acked, "sensor_mode_unconfigured")),
                    l2=_t(keys.get(code, "sensor_mode_unconfigured")),
                    io=int(getattr(packet, "io_status", 0) or 0),
                    sys=int(getattr(packet, "sys_mode", 0) or 0),
                )
            )
            label.setStyleSheet("color: #ff9800; font-size: 12px; font-weight: bold;")
            return
        if code == 0 and gate_ok:
            label.setText(_t("commission_status_done_ir"))
            label.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold;")
        elif code == 1:
            label.setText(_t("commission_status_done_radar"))
            label.setStyleSheet("color: #4caf50; font-size: 12px; font-weight: bold;")
        elif code == 2:
            label.setText(_t("commission_status_done_none"))
            label.setStyleSheet("color: #ffb74d; font-size: 12px; font-weight: bold;")
        else:
            label.setText(_t("commission_status_incomplete"))
            label.setStyleSheet("color: #ffb74d; font-size: 12px; font-weight: bold;")

    def _update_sensor_mode_status_label(self, packet=None, lang="zh"):
        from core.translation import _t
        from core.master_summary import format_sensor_mode_brief

        label = getattr(self, "sensor_mode_status_label", None)
        if label is None:
            return
        if packet is None:
            label.setText(_t("tip_sensor_mode"))
            label.setStyleSheet("color: #888888; font-size: 11px;")
            self._refresh_commissioning_status(None, lang=lang)
            return
        override = 2 if self._occupancy_gate_suppressed() else None
        text = format_sensor_mode_brief(packet, lang=lang, mode_override=override)
        uncfg = int(packet.sensor_mode_code()) == 2 or override == 2
        warn = uncfg or bool(packet.ir_degraded) or (not packet.occ_gate_enabled)
        label.setText(text)
        label.setStyleSheet(
            "color: %s; font-size: 11px;" % ("#ffb74d" if warn else "#4caf50")
        )
        self._refresh_commissioning_status(packet, lang=lang)

    def on_sensor_mode_combo_changed(self, _index=None):
        """下拉只选型，不发 0x19。"""
        committed = self._committed_sensor_mode(2)
        if committed not in (0, 1, 2):
            committed = 2
        self._sensor_mode_dirty = self._selected_sensor_mode() != committed
        self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))

    def write_master_sensor_mode(self):
        """确认后把当前下拉的传感器模式写入主控 0x19。"""
        from core.translation import _t

        mode = self._selected_sensor_mode()
        if not self.check_permission_before_action(
            "Set sensor mode", Permission.MODIFY_DETECTOR_SETTINGS
        ):
            self._sensor_mode_dirty = False
            self._sync_sensor_mode_ui(self._committed_sensor_mode(2))
            self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))
            return
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if not bool(getattr(self.config, "tcp_enabled", False)) or not master_cid:
            show_warn(self, _t("msg_sensor_mode_title"), _t("msg_sensor_mode_need_master"))
            return
        keys = {
            0: "sensor_mode_ir",
            1: "sensor_mode_radar",
            2: "sensor_mode_unconfigured",
        }
        if not ask_confirm(
            self,
            _t("msg_sensor_mode_title"),
            _t("msg_sensor_mode_write_text", mode=_t(keys[mode])),
            danger=False,
        ):
            self._sensor_mode_dirty = False
            self._sync_sensor_mode_ui(self._committed_sensor_mode(2))
            self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))
            return
        self.set_master_sensor_mode(mode)
        self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))

    def set_master_sensor_mode(self, mode: int):
        """PC → 主控 0x19 设置传感器模式（0=对射，1=雷达，2=未配置）。"""
        from core.translation import _t

        try:
            mode = int(mode)
        except (TypeError, ValueError):
            mode = 2
        if mode not in (0, 1, 2):
            mode = 2
        if not bool(getattr(self.config, "tcp_enabled", False)):
            show_warn(self, _t("msg_sensor_mode_title"), _t("msg_sensor_mode_need_master"))
            return False
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if not master_cid or not hasattr(self, "worker") or self.worker is None:
            show_warn(self, _t("msg_sensor_mode_title"), _t("msg_sensor_mode_need_master"))
            return False
        if not hasattr(self.worker, "send_command_to_client"):
            return False
        names = {0: "IR", 1: "RADAR", 2: "UNCONFIGURED"}
        ok = self.worker.send_command_to_client(
            master_cid,
            "channel_sensor_mode",
            mode,
            description="Set sensor mode %s (0x19)" % names.get(mode, str(mode)),
        )
        if ok:
            self._pending_sensor_mode_at = time.time()
            self.log("Sensor mode 0x19 set → %s" % names.get(mode, str(mode)), "INFO")
        return bool(ok)

    def read_master_sensor_mode(self):
        """PC → 主控 0x19 FF 读传感器模式。"""
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if not master_cid or not hasattr(self, "worker") or self.worker is None:
            return False
        if not hasattr(self.worker, "send_command_to_client"):
            return False
        ok = bool(
            self.worker.send_command_to_client(
                master_cid,
                "channel_sensor_mode",
                0xFF,
                description="Read sensor mode (0x19)",
            )
        )
        if ok:
            self._pending_sensor_mode_at = time.time()
        return ok

    def on_sensor_mode_feedback(self, packet):
        """主控 CmdFeedback control_code=0x19。"""
        from core.translation import _t

        self._pending_sensor_mode_at = 0.0
        if int(getattr(packet, "status", 0) or 0) != 1:
            self.log("Sensor mode 0x19 rejected", "WARNING")
            show_warn(self, _t("msg_sensor_mode_title"), _t("msg_sensor_mode_fail"))
            self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))
            return
        try:
            mode = int(getattr(packet, "value", 0)) & 0xFF
        except (TypeError, ValueError):
            mode = 2
        if mode not in (0, 1, 2):
            mode = 2
        self._master_sensor_mode = mode
        self._sensor_mode_dirty = False
        self._sensor_mode_ack_hold = True
        self._sensor_mode_ack_hold_until = time.time() + 8.0
        self._sensor_mode_ack_unconfigured = mode == 2
        self._sync_sensor_mode_ui(mode)
        names = {0: "IR", 1: "RADAR", 2: "UNCONFIGURED"}
        label = getattr(self, "sensor_mode_status_label", None)
        if label is not None:
            mode_key = {
                0: "sensor_mode_ir",
                1: "sensor_mode_radar",
                2: "sensor_mode_unconfigured",
            }.get(mode, "sensor_mode_unconfigured")
            label.setText(_t("sensor_mode_ack", mode=_t(mode_key)))
            label.setStyleSheet(
                "color: %s; font-size: 11px;" % ("#ffb74d" if mode == 2 else "#4caf50")
            )
        self.log(
            "Sensor mode ack → %s (value=%d)" % (names.get(mode, str(mode)), mode),
            "INFO",
        )
        if mode == 2:
            self.log(
                "Unconfigured ack: occupancy-gate UI forced off "
                "(PC does not write probe 0x0078)",
                "INFO",
            )
        self._refresh_commissioning_status(getattr(self, "latest_master_summary", None))
        pkt = getattr(self, "latest_master_summary", None)
        offline = not (pkt is not None and self.is_master_online())
        if hasattr(self, "_update_home_occupancy"):
            self._update_home_occupancy(pkt, master_offline=offline)
        if hasattr(self, "_update_overview_occupancy_from_master"):
            self._update_overview_occupancy_from_master(pkt, master_offline=offline)
        if hasattr(self, "_update_settings_occupancy_from_master"):
            self._update_settings_occupancy_from_master(pkt, master_offline=offline)
        # L2 下一帧会刷新 bit3/bit4；先用应答刷新健康行
        if hasattr(self, "_update_home_health_and_faults"):
            self._update_home_health_and_faults()

    def request_channel_alarm_reset(self):
        """用户点「通道报警复位」→ 登录审计 → 管理员校验 → 二次确认 → 主控 0x15。"""
        from core.translation import _t
        import time as _time

        master_cid = getattr(self, "master_client_id", None)
        if not master_cid or not getattr(self, "worker", None):
            show_warn(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_no_master"))
            return

        # 公共监视模式不可直接发复位：先登录以便审计落人
        if not self.is_logged_in():
            show_info(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_need_login"))
            if not self.login(preferred_page=0, required_for_page=False):
                return
            if not self.is_logged_in():
                return

        # 危险操作：仅管理员（VIEWER 登录后也不能发 0x15）
        role = None
        if isinstance(getattr(self, "current_user", None), dict):
            role = self.current_user.get("role")
        if role not in (UserRole.ADMIN, UserRole.MAINTAINER):
            show_warn(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_need_admin"))
            return

        if not ask_confirm(
            self,
            _t("msg_channel_reset_title"),
            _t("msg_channel_reset_text"),
            danger=True,
        ):
            return

        pkt = getattr(self, "latest_master_summary", None) or getattr(
            self, "_last_any_master_packet", None
        )
        user = None
        if isinstance(getattr(self, "current_user", None), dict):
            user = self.current_user.get("username") or self.current_user.get("role")
        self._channel_reset_audit_snap = {
            "user": user or "public",
            "at": _time.time(),
            "hit_mask": int(getattr(pkt, "hit_probe_mask", 0) or 0) if pkt else 0,
            "total_cps": int(getattr(pkt, "total_cps", 0) or 0) if pkt else 0,
            "decision": int(getattr(pkt, "decision_result", 0) or 0) if pkt else 0,
            "relay": int(getattr(pkt, "relay_mask", 0) or 0) if pkt else 0,
        }

        ok = self.worker.send_command_to_client(
            master_cid,
            "channel_alarm_reset",
            0,
            description="Channel alarm manual reset (0x15)",
        )
        if not ok:
            self._channel_reset_audit_snap = None
            self._pending_channel_reset_at = 0.0
            self._awaiting_l2_acked = False
            show_error(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_fail"))
            return

        self._pending_channel_reset_at = _time.time()
        self._awaiting_l2_acked = False
        btn = getattr(self.home_page, "channel_reset_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        self.log(
            "Channel alarm reset 0x15 sent by %s (hit_mask=0x%04X cps=%d decision=0x%02X)"
            % (
                self._channel_reset_audit_snap["user"],
                self._channel_reset_audit_snap["hit_mask"],
                self._channel_reset_audit_snap["total_cps"],
                self._channel_reset_audit_snap["decision"],
            ),
            "INFO",
        )
        QTimer.singleShot(5000, self._channel_reset_timeout_check)

    def _channel_reset_timeout_check(self):
        from core.translation import _t
        import time as _time

        pending = float(getattr(self, "_pending_channel_reset_at", 0) or 0)
        if pending <= 0:
            return
        if (_time.time() - pending) < 4.5:
            return
        self._pending_channel_reset_at = 0.0
        self.log("Channel alarm reset 0x15 ack timeout", "WARNING")
        # 若仍硬报则重新启用按钮
        pkt = getattr(self, "latest_master_summary", None) or getattr(
            self, "_last_any_master_packet", None
        )
        btn = getattr(self.home_page, "channel_reset_btn", None)
        if btn is not None and pkt is not None and getattr(pkt, "is_channel_alarm", lambda: False)():
            btn.setEnabled(True)
        show_warn(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_timeout"))

    def _channel_reset_l2_timeout_check(self):
        """CmdFeedback 成功后若长时间等不到 L2=0x05，释放复位按钮避免卡死。"""
        import time as _time
        from core.translation import _t

        if not getattr(self, "_awaiting_l2_acked", False):
            return
        t0 = float(getattr(self, "_awaiting_l2_acked_at", 0) or 0)
        if t0 <= 0 or (_time.time() - t0) < 7.5:
            return

        self._awaiting_l2_acked = False
        self._awaiting_l2_acked_at = 0.0
        pkt = getattr(self, "latest_master_summary", None) or getattr(
            self, "_last_any_master_packet", None
        )
        # 主控已非硬报：视为跳过 0x05 的消警，补写审计
        if pkt is not None and not pkt.is_channel_alarm():
            if getattr(self, "_channel_reset_audit_snap", None):
                self._write_channel_reset_audit(pkt, source="l2_cleared_without_0x05")
            self.log(
                "Channel reset: L2 left hard-alarm without 0x05; released await",
                "INFO",
            )
        else:
            self.log(
                "Channel reset: wait L2=0x05 timeout; re-enable reset if still alarming",
                "WARNING",
            )
            if getattr(self, "_channel_reset_audit_snap", None):
                self._channel_reset_audit_snap = None
            btn = getattr(self.home_page, "channel_reset_btn", None)
            if btn is not None and pkt is not None and pkt.is_channel_alarm():
                btn.setEnabled(True)

    def on_channel_alarm_reset_feedback(self, packet):
        """主控 CmdFeedback control_code=0x15。"""
        from core.translation import _t
        import time as _time

        pending = float(getattr(self, "_pending_channel_reset_at", 0) or 0)
        if pending <= 0 and not getattr(self, "_channel_reset_audit_snap", None):
            # 非本机发起也可记日志
            pass

        if not packet.status:
            self._pending_channel_reset_at = 0.0
            self._awaiting_l2_acked = False
            self._awaiting_l2_acked_at = 0.0
            self._channel_reset_audit_snap = None
            self.log(
                "Channel alarm reset rejected (status=0 value=0x%04X)"
                % (int(packet.value) & 0xFFFF),
                "WARNING",
            )
            btn = getattr(self.home_page, "channel_reset_btn", None)
            pkt = getattr(self, "latest_master_summary", None)
            if btn is not None and pkt is not None and pkt.is_channel_alarm():
                btn.setEnabled(True)
            show_warn(self, _t("msg_channel_reset_title"), _t("msg_channel_reset_cmd_fail"))
            return

        # 成功：value 期望 0xA55A；硬报 UI 等下一拍 L2=0x05 再清
        val = int(packet.value) & 0xFFFF
        self._pending_channel_reset_at = 0.0
        self._awaiting_l2_acked = True
        self._awaiting_l2_acked_at = _time.time()
        self.log(
            "Channel alarm reset CmdFeedback OK value=0x%04X (expect 0xA55A)"
            % val,
            "INFO" if val == 0xA55A else "WARNING",
        )
        QTimer.singleShot(8000, self._channel_reset_l2_timeout_check)
        # 成功不弹框：硬报 UI 等下一拍 L2=0x05 自动清除

    def _write_channel_reset_audit(self, packet, source="l2_0x05"):
        """操作审计：谁、何时、当时 mask/cps。"""
        snap = getattr(self, "_channel_reset_audit_snap", None) or {}
        user = snap.get("user", "public")
        hit = int(getattr(packet, "hit_probe_mask", 0) or 0) if packet else int(snap.get("hit_mask", 0))
        cps = int(getattr(packet, "total_cps", 0) or 0) if packet else int(snap.get("total_cps", 0))
        relay = int(getattr(packet, "relay_mask", 0) or 0) if packet else int(snap.get("relay", 0))
        self.log(
            "AUDIT channel_reset %s by=%s hit_mask=0x%04X cps=%d relay_mask=0x%02X"
            % (source, user, hit, cps, relay),
            "INFO",
        )
        self._channel_reset_audit_snap = None

    def _release_channel_reset_await_if_cleared(self, packet, source="l2_cleared_without_0x05"):
        """复位后主控未走 0x05 已离开硬报：补审计并释放 awaiting，避免按钮卡死。"""
        if not getattr(self, "_awaiting_l2_acked", False):
            return
        if getattr(self, "_channel_reset_audit_snap", None):
            self._write_channel_reset_audit(packet, source=source)
        self._awaiting_l2_acked = False
        self._awaiting_l2_acked_at = 0.0
        self._pending_channel_reset_at = 0.0

    def _master_never_seen(self) -> bool:
        """本次运行从未收到过主控 L2，且当前也没有主控 TCP 客户端。"""
        if float(getattr(self, "_last_any_master_at", 0) or 0) > 0:
            return False
        if getattr(self, "latest_master_summary", None) is not None:
            return False
        if getattr(self, "master_client_id", None):
            return False
        return True

    def _ir_installed(self) -> bool:
        """是否把 L2 0x04 当「人员经过」。挡光明细另走 _io_brief。

        对射(0)=是；雷达(1)/未配置(2)=否。主控离线时用最近一次模式或配置兜底。
        未配置不把 0x04 当经过。现固件未配置也不上报 PG14/PG15。
        """
        if self._occupancy_gate_suppressed():
            return False
        pkt = getattr(self, "latest_master_summary", None)
        try:
            online = bool(pkt is not None and self.is_master_online())
        except Exception:
            online = False
        if online:
            return int(pkt.sensor_mode_code()) == 0
        mode = getattr(self, "_master_sensor_mode", None)
        if mode is not None:
            try:
                return int(mode) == 0
            except (TypeError, ValueError):
                pass
        return bool(getattr(self.config, "ir_installed", True))

    def _ir_degraded_ui(self, packet) -> bool:
        """门控未生效/降级态跟 L2 bit0；不依赖本机勾选。"""
        if self._occupancy_gate_suppressed():
            return True
        return bool(packet is not None and getattr(packet, "ir_degraded", False))

    def _io_brief(self, packet, lang="zh", beam_detail: str = "exception") -> str:
        from core.master_summary import format_io_brief
        # 占用判定可按未配置压掉；挡光跟 L2。只有 L2 已是对射时才有 PG14/PG15。
        override = None
        if self._occupancy_gate_suppressed():
            try:
                l2 = int(packet.sensor_mode_code())
            except Exception:
                l2 = 2
            if l2 != 0:
                override = 2 if l2 != 1 else 1
        show = bool(getattr(self.config, "ir_installed", True))
        return format_io_brief(
            packet,
            lang=lang,
            ir_installed=show,
            mode_override=override,
            beam_detail=beam_detail,
        )

    def _blocked_beam_text(self, packet, lang="zh") -> str:
        from core.master_summary import format_ir_beam_states
        if packet is None or not bool(getattr(self.config, "ir_installed", True)):
            return ""
        try:
            if int(packet.sensor_mode_code()) != 0:
                return ""
        except Exception:
            return ""
        beams = format_ir_beam_states(packet, lang=lang, only_blocked=True)
        if not beams:
            return ""
        return ("\u3001" if lang != "en" else ", ").join(beams)

    def _operator_occupancy_desc(self, kind: str, packet, lang="zh") -> str:
        """首页/总览：通道态为主，挡光只在挡住时点一下。"""
        from core.translation import _t
        if kind == "ungated":
            return _t("desc_occ_ungated")
        if kind == "alarm":
            base = _t("desc_traffic_detected")
        elif kind == "passing":
            base = _t("desc_traffic_detected")
        else:
            base = _t("desc_no_traffic")
        blocked = self._blocked_beam_text(packet, lang)
        if blocked:
            return "%s %s" % (base, blocked)
        return base

    def _ungated_occupancy_desc(self, brief: str, lang="zh") -> str:
        from core.translation import _t
        base = _t("desc_occ_ungated")
        text = (brief or "").strip()
        if text:
            return "%s %s" % (base, text)
        return base

    def _occupancy_kind_from_packet(self, packet, master_offline=False) -> str:
        """vacant | passing | alarm | offline | ungated

        ungated：传感器未配置或门控未生效时，不要显示绿色「通道空闲」
        （没接传感器时出厂常见 bit4=0，decision=0x00 会被误读成空闲）。
        """
        if master_offline or packet is None:
            return "offline"
        if bool(getattr(packet, "is_channel_alarm", lambda: False)()):
            return "alarm"
        if self._occupancy_gate_suppressed():
            return "ungated"
        try:
            code = int(packet.sensor_mode_code())
        except Exception:
            code = 2
        gate_ok = bool(getattr(packet, "occ_gate_enabled", False))
        degraded = bool(getattr(packet, "ir_degraded", False))
        if code == 2 or (not gate_ok) or degraded:
            return "ungated"
        if int(getattr(packet, "decision_result", 0) or 0) == 0x04 and code == 0:
            return "passing"
        return "vacant"

    def _set_home_occupancy_kind(self, kind: str):
        page = getattr(self, "home_page", None)
        if page is None:
            return
        page._occupancy_kind = str(kind or "vacant")
        page._passage_busy = page._occupancy_kind in ("passing", "alarm")

    def _update_home_occupancy_probe(self, busy, lang="zh"):
        """无有效主控 L2：区分「从未接入」与「曾经在线后掉线」。"""
        from core.translation import _t
        page = self.home_page
        page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
        page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
        never = self._master_never_seen()
        link_only = bool(getattr(self, "master_client_id", None)) and not self.is_master_online()
        if never:
            # 只开软件、什么设备都没接：不要写成「通道占用/主控离线」故障感
            page.occupancy_status_label.setText(_t("status_occ_no_master"))
            page.occupancy_desc_label.setText(_t("desc_occ_no_master"))
            kind = "noconn"
        elif link_only:
            page.occupancy_status_label.setText(_t("status_occ_wait_l2"))
            page.occupancy_desc_label.setText(_t("desc_occ_wait_l2"))
            kind = "offline"
        else:
            page.occupancy_status_label.setText(_t("status_occ_master_offline"))
            page.occupancy_desc_label.setText(_t("desc_master_offline"))
            kind = "offline"
        self._set_home_status_style(
            page.occupancy_status_label, "#ff9800",
            "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
        )
        page.occupancy_indicator_bar.setStyleSheet(
            "QFrame { background-color: #ff9800; border-radius: 1px; }"
        )
        self._set_home_occupancy_kind(kind)

    def _update_home_occupancy(self, packet, lang="zh", master_offline=False):
        from core.translation import _t
        page = self.home_page
        if master_offline or packet is None:
            self._update_home_occupancy_probe(False, lang=lang)
            return

        kind = self._occupancy_kind_from_packet(packet, master_offline=False)
        brief = self._io_brief(packet, lang)
        desc = self._operator_occupancy_desc(kind, packet, lang)
        if kind == "alarm":
            page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_active'))
            page.occupancy_status_label.setText(_t("status_occupied_alarm"))
            self._set_home_status_style(
                page.occupancy_status_label, "#ff4444",
                "rgba(255, 68, 68, 0.15)", "rgba(255, 68, 68, 0.4)"
            )
            page.occupancy_desc_label.setText(desc)
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #ff4444; border-radius: 1px; }"
            )
        elif kind == "passing":
            page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_active'))
            page.occupancy_status_label.setText(_t("status_passing"))
            self._set_home_status_style(
                page.occupancy_status_label, "#2196f3",
                "rgba(33, 150, 243, 0.15)", "rgba(33, 150, 243, 0.4)"
            )
            page.occupancy_desc_label.setText(desc)
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #2196f3; border-radius: 1px; }"
            )
        elif kind == "ungated":
            # 没接/未配置传感器：黄提示，禁止绿色「通道空闲」
            page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            try:
                code = int(packet.sensor_mode_code())
            except Exception:
                code = 2
            if self._occupancy_gate_suppressed():
                code = 2
            if code == 2 or not bool(getattr(packet, "occ_gate_enabled", False)):
                page.occupancy_status_label.setText(_t("status_occ_ungated"))
                page.occupancy_desc_label.setText(desc)
            else:
                page.occupancy_status_label.setText(_t("status_occ_gate_inactive"))
                page.occupancy_desc_label.setText(brief or _t("desc_occ_gate_inactive"))
            self._set_home_status_style(
                page.occupancy_status_label, "#ffb74d",
                "rgba(255, 183, 77, 0.12)", "rgba(255, 183, 77, 0.35)"
            )
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #ffb74d; border-radius: 1px; }"
            )
        else:
            page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            page.occupancy_status_label.setText(_t("status_vacant"))
            self._set_home_status_style(
                page.occupancy_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            page.occupancy_desc_label.setText(desc)
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #4caf50; border-radius: 1px; }"
            )
        self._set_home_occupancy_kind(kind)

    def _refresh_alarm_log_nav_badge(self, radiation_alarm=None, has_faults=None):
        """底栏报警日志：仅活动硬报/辐射报警时亮红点（设备故障不算）。"""
        if not hasattr(self, "bottom_nav") or self.bottom_nav is None:
            return
        if radiation_alarm is None:
            pkt = getattr(self, "latest_master_summary", None)
            radiation_alarm = bool(
                pkt is not None and self.is_master_online() and pkt.is_channel_alarm()
            )
        active_count = 0
        try:
            from core.alarm_logger import get_alarm_logger
            # 底栏红点只跟辐射/通道硬报，不含 M101/M102 系统事件
            active_count = get_alarm_logger().get_active_radiation_count()
        except Exception:
            active_count = 0
        show = bool(radiation_alarm) or active_count > 0
        self.bottom_nav.set_alarm_log_badge(show)
    
    def update_alarm_status(self, is_alarm_active: bool):
        """探头报警位回调：仅刷新日志相关；概览通道硬报强制跟主控 L2。"""
        self.update_system_status(None)

    def update_system_status(self, is_alarm_active: Optional[bool] = None):
        """Update system status indicator on overview page, combining radiation alarms and device faults."""
        current_time = datetime.now().strftime("%H:%M:%S")
        master_pkt = getattr(self, "latest_master_summary", None)
        master_online = bool(self.is_master_online() and master_pkt is not None)
        master_hard_alarm = bool(master_online and master_pkt.is_channel_alarm())

        # 主控在线：概览硬报只跟 L2；离线：不跟探头拼通道红闪
        is_alarm_active = master_hard_alarm if master_online else False

        # Get all active faults from diagnostics manager
        active_faults = list(self.diagnostics_manager.get_all_active_faults())
        # 冷启动未接设备：不把 E101/E103/M101 当「系统异常」刷概览
        try:
            cold = (
                self._master_never_seen()
                and self._tcp_client_count() == 0
                and not master_online
            )
        except Exception:
            cold = False
        if cold:
            _probe_comm = {FaultCode.E101, FaultCode.E102, FaultCode.E103}
            active_faults = [
                row for row in active_faults
                if not (
                    row[0] == _MASTER_FAULT_CLIENT_ID
                    or (row[0] == "system" and row[1] in _probe_comm)
                )
            ]
        current_fault_keys = set((client_id, code) for client_id, code, _, _, _, _ in active_faults)
        
        # Log newly added faults
        for client_id, code in current_fault_keys - self.prev_fault_keys:
            name, desc, severity, _ = FaultCode.get_info(code)
            self.log(f"[FAULT DETECTED] Client: {client_id} | Code: {code} | {name}: {desc}", severity)
            
        # Log cleared faults
        for client_id, code in self.prev_fault_keys - current_fault_keys:
            name, _, _, _ = FaultCode.get_info(code)
            self.log(f"[FAULT CLEARED] Client: {client_id} | Code: {code} | {name} has been resolved", "INFO")
            
        self.prev_fault_keys = current_fault_keys
        self._sync_probe_comm_logs()
        # 底栏角标：主控硬报 或 日志器仍有活动辐射边沿
        self._refresh_alarm_log_nav_badge(radiation_alarm=bool(master_hard_alarm))
        
        if is_alarm_active:
            # 1. Radiation alarm active (Highest priority: Flashing Red)
            self.start_alarm_flashing()
            
            # Update title icon
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_active'))
            
            # Update status label with red active styling
            from core.translation import _t
            self.overview_page.alarm_status_label.setText(_t("status_alarm"))
            self._set_overview_status_text(self.overview_page.alarm_status_label, "#ff4444")
            
            # Update description with timestamp
            self.overview_page.alarm_desc_label.setText(_t("desc_alarm_at", time=current_time))
            self.overview_page.alarm_desc_scroll.setToolTip("")
            self.overview_page.alarm_desc_label.setStyleSheet("""
                QLabel {
                    color: #ff8888;
                    font-size: 11px;
                    font-weight: bold;
                    margin-top: 0px;
                }
            """)
            
            # Update status indicator bar to red
            self._set_overview_accent_bar(self.overview_page.status_indicator_bar, "#ff4444")
            
            # Update card border color (subtle red border)
            self._set_overview_card_shell(self.overview_page.alarm_card, "#ff4444")
        elif active_faults:
            # 2. System has active faults (Medium priority: Orange)
            self.stop_alarm_flashing()
            
            # Update title icon and main indicator to inactive
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            
            # Format fault messages for display (per-client probe number)
            from core.translation import _t
            unique_op_msgs = []
            for client_id, code, _, _, _, _ in active_faults:
                if hasattr(self, "format_fault_home_message"):
                    translated_msg = self.format_fault_home_message(client_id, code)
                elif hasattr(self, "format_fault_operator_message"):
                    translated_msg = self.format_fault_operator_message(client_id, code)
                else:
                    # 勿直接 _t(fault_op_*)：旧文案含 {probe} 会原样显示成 “probe...”
                    translated_msg = _t(f"fault_op_{code}", probe="")
                    translated_msg = translated_msg.replace("{probe}", "").lstrip()
                if translated_msg not in unique_op_msgs:
                    unique_op_msgs.append(translated_msg)
            
            display_text, tooltip_text = _format_fault_description(unique_op_msgs)
            
            # Update status label with orange styling
            self.overview_page.alarm_status_label.setText(_t("status_fault"))
            self._set_overview_status_text(self.overview_page.alarm_status_label, "#ff9800")
            
            # 卡片内限高滚动；完整故障列表放 tooltip
            self.overview_page.alarm_desc_label.setText(display_text)
            self.overview_page.alarm_desc_scroll.setToolTip(tooltip_text)
            self.overview_page.alarm_desc_label.setStyleSheet("""
                QLabel {
                    color: #ffb74d;
                    font-size: 11px;
                    font-weight: bold;
                    margin-top: 0px;
                }
            """)
            
            # Update status indicator bar to orange
            self._set_overview_accent_bar(self.overview_page.status_indicator_bar, "#ff9800")
            
            # Update card border color (subtle orange border)
            self._set_overview_card_shell(self.overview_page.alarm_card, "#ff9800")
        else:
            # 3. System completely normal (Green)
            self.stop_alarm_flashing()
            
            # Update title icon and main indicator to inactive
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            
            # Update status label with green styling
            from core.translation import _t
            self.overview_page.alarm_status_label.setText(_t("status_normal"))
            self._set_overview_status_text(self.overview_page.alarm_status_label, "#4caf50")
            
            # Update description with timestamp
            self.overview_page.alarm_desc_label.setText(_t("desc_checked_at", time=current_time))
            self.overview_page.alarm_desc_scroll.setToolTip("")
            self.overview_page.alarm_desc_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 11px;
                    font-weight: normal;
                    margin-top: 0px;
                }
            """)
            
            # Update status indicator bar to green
            self._set_overview_accent_bar(self.overview_page.status_indicator_bar, "#4caf50")
            
            # Reset card border color (no border like other cards)
            self._set_overview_card_shell(self.overview_page.alarm_card, "#444444")

        # 4. Update Occupancy Status on Overview Page — 跟主控 L2，不跟探头 bit5
        self._update_overview_occupancy_from_master()
    
    def _update_settings_occupancy_from_master(self, packet=None, master_offline=False):
        """设置页「通道占用」显示主控 L2 通道忙闲。"""
        from core.translation import _t
        if not hasattr(self, "occupancy_status_label"):
            return
        if packet is None and not master_offline:
            if self.is_master_online():
                packet = getattr(self, "latest_master_summary", None)
        if master_offline or packet is None:
            if self._master_never_seen():
                self.occupancy_status_label.setText(_t("status_occ_no_master"))
            elif bool(getattr(self, "master_client_id", None)) and not self.is_master_online():
                self.occupancy_status_label.setText(_t("status_occ_wait_l2"))
            else:
                self.occupancy_status_label.setText(_t("status_occ_master_offline"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ffe0b2; color: #000000;"
            )
            return
        kind = self._occupancy_kind_from_packet(packet, master_offline=False)
        if kind == "alarm":
            self.occupancy_status_label.setText(_t("status_occupied_alarm"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ffcdd2; color: #000000;"
            )
        elif kind == "passing":
            self.occupancy_status_label.setText(_t("status_passing"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #bbdefb; color: #000000;"
            )
        elif kind == "ungated":
            try:
                code = int(packet.sensor_mode_code())
            except Exception:
                code = 2
            if self._occupancy_gate_suppressed():
                code = 2
            if code == 2 or not bool(getattr(packet, "occ_gate_enabled", False)):
                self.occupancy_status_label.setText(_t("status_occ_ungated"))
            else:
                self.occupancy_status_label.setText(_t("status_occ_gate_inactive"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ffe0b2; color: #000000;"
            )
        else:
            self.occupancy_status_label.setText(_t("status_vacant"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ccffcc; color: #000000;"
            )
        # 设置页给开通对线：对射时一直列出通/挡
        try:
            if int(packet.sensor_mode_code()) == 0:
                from core.master_summary import format_ir_beam_states
                beams = format_ir_beam_states(packet, only_blocked=False)
                if beams:
                    self.occupancy_status_label.setText(
                        "%s  %s" % (self.occupancy_status_label.text(), "  ".join(beams))
                    )
        except Exception:
            pass

    def _update_overview_occupancy_from_master(self, packet=None, master_offline=False):
        """概览占用卡：跟首页同一套操作员语义。通光不写对射，挡住才点入口/出口。"""
        from core.translation import _t

        if not hasattr(self, "overview_page"):
            return

        if packet is None and not master_offline:
            if hasattr(self, "is_master_online") and self.is_master_online():
                packet = getattr(self, "latest_master_summary", None)

        if master_offline or packet is None:
            self.stop_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            link_only = bool(getattr(self, "master_client_id", None)) and not self.is_master_online()
            if self._master_never_seen():
                self.overview_page.occupancy_status_label.setText(_t("status_occ_no_master"))
                self.overview_page.occupancy_desc_label.setText(_t("desc_occ_no_master"))
            elif link_only:
                self.overview_page.occupancy_status_label.setText(_t("status_occ_wait_l2"))
                self.overview_page.occupancy_desc_label.setText(_t("desc_occ_wait_l2"))
            else:
                self.overview_page.occupancy_status_label.setText(_t("status_occ_master_offline"))
                self.overview_page.occupancy_desc_label.setText(_t("desc_master_offline"))
            self._set_overview_status_text(self.overview_page.occupancy_status_label, "#ff9800")
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel { color: #888888; font-size: 11px; background: transparent; border: none; }
            """)
            self._set_overview_accent_bar(self.overview_page.occupancy_indicator_bar, "#ff9800")
            self._set_overview_card_shell(self.overview_page.occupancy_card, "#444444")
            return

        kind = self._occupancy_kind_from_packet(packet, master_offline=False)
        try:
            from core.translation import TranslationManager
            lang = TranslationManager().current_lang
        except Exception:
            lang = "zh"
        brief = self._io_brief(packet, lang=lang)
        desc = self._operator_occupancy_desc(kind, packet, lang)

        if kind == "alarm":
            self.start_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            self.overview_page.occupancy_status_label.setText(_t("status_occupied_alarm"))
            self._set_overview_status_text(self.overview_page.occupancy_status_label, "#ff4444")
            self.overview_page.occupancy_desc_label.setText(desc)
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #ff8888;
                    font-size: 11px;
                    font-weight: bold;
                    margin-top: 0px;
                    background: transparent;
                    border: none;
                }
            """)
            self._set_overview_accent_bar(self.overview_page.occupancy_indicator_bar, "#ff4444")
            self._set_overview_card_shell(self.overview_page.occupancy_card, "#ff4444")
        elif kind == "passing":
            self.start_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            self.overview_page.occupancy_status_label.setText(_t("status_passing"))
            self._set_overview_status_text(self.overview_page.occupancy_status_label, "#2196F3")
            self.overview_page.occupancy_desc_label.setText(desc)
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #90caf9;
                    font-size: 11px;
                    font-weight: bold;
                    margin-top: 0px;
                    background: transparent;
                    border: none;
                }
            """)
            self._set_overview_accent_bar(self.overview_page.occupancy_indicator_bar, "#2196F3")
            self._set_overview_card_shell(self.overview_page.occupancy_card, "#2196F3")
        elif kind == "ungated":
            self.stop_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            try:
                code = int(packet.sensor_mode_code())
            except Exception:
                code = 2
            if self._occupancy_gate_suppressed():
                code = 2
            if code == 2 or not bool(getattr(packet, "occ_gate_enabled", False)):
                self.overview_page.occupancy_status_label.setText(_t("status_occ_ungated"))
                desc = self._operator_occupancy_desc("ungated", packet, lang)
            else:
                self.overview_page.occupancy_status_label.setText(_t("status_occ_gate_inactive"))
                desc = brief or _t("desc_occ_gate_inactive")
            self._set_overview_status_text(self.overview_page.occupancy_status_label, "#ffb74d")
            self.overview_page.occupancy_desc_label.setText(desc)
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #ffb74d;
                    font-size: 11px;
                    font-weight: bold;
                    margin-top: 0px;
                    background: transparent;
                    border: none;
                }
            """)
            self._set_overview_accent_bar(self.overview_page.occupancy_indicator_bar, "#ffb74d")
            self._set_overview_card_shell(self.overview_page.occupancy_card, "#ffb74d")
        else:
            self.stop_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_status_label.setText(_t("status_vacant"))
            self._set_overview_status_text(self.overview_page.occupancy_status_label, "#4caf50")
            self.overview_page.occupancy_desc_label.setText(desc)
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 11px;
                    font-weight: normal;
                    margin-top: 0px;
                    background: transparent;
                    border: none;
                }
            """)
            self._set_overview_accent_bar(self.overview_page.occupancy_indicator_bar, "#4caf50")
            self._set_overview_card_shell(self.overview_page.occupancy_card, "#444444")
    
    def start_alarm_flashing(self):
        """Start flashing the alarm indicator"""
        if not hasattr(self, 'alarm_flash_timer'):
            self.alarm_flash_timer = QTimer()
            self.alarm_flash_timer.timeout.connect(self.toggle_alarm_icon)
            self.alarm_flash_state = True
        
        if not self.alarm_flash_timer.isActive():
            self.alarm_flash_timer.start(500)  # Flash every 500ms
            self.alarm_flash_state = True
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_active'))
    
    def stop_alarm_flashing(self):
        """Stop flashing the alarm indicator"""
        if hasattr(self, 'alarm_flash_timer') and self.alarm_flash_timer.isActive():
            self.alarm_flash_timer.stop()
    
    def toggle_alarm_icon(self):
        """Toggle between alarm_active and alarm_flashing icons"""
        if self.alarm_flash_state:
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_flashing'))
        else:
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_active'))
        
        self.alarm_flash_state = not self.alarm_flash_state
    
    def start_occupancy_flashing(self):
        """Start flashing the occupancy indicator"""
        if not hasattr(self, 'occ_flash_timer'):
            self.occ_flash_timer = QTimer()
            self.occ_flash_timer.timeout.connect(self.toggle_occupancy_icon)
            self.occ_flash_state = True
        
        if not self.occ_flash_timer.isActive():
            self.occ_flash_timer.start(500)  # Flash every 500ms
            self.occ_flash_state = True
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_active'))

    def stop_occupancy_flashing(self):
        """Stop flashing the occupancy indicator"""
        if hasattr(self, 'occ_flash_timer') and self.occ_flash_timer.isActive():
            self.occ_flash_timer.stop()

    def toggle_occupancy_icon(self):
        """Toggle between occupancy_active and occupancy_flashing icons"""
        if self.occ_flash_state:
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_flashing'))
        else:
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_active'))
        
        self.occ_flash_state = not self.occ_flash_state
    
    def enter_public_mode(self):
        """Exit login session -> public home monitor only."""
        from core.translation import _t
        try:
            self.release_acq_hold_lock(resume=True)
        except Exception as e:
            self.log("Release acquisition hold on public mode failed: %s" % e, "WARNING")
        self.current_user = None
        try:
            self.user_manager.logout()
        except Exception:
            pass
        self.timeout_manager.stop_timer()
        self.status_bar.hide_timeout_display()
        self.status_bar.update_user_info(_t("status_public_mode"), None)
        if getattr(self, "control_room_mode", False):
            self.status_bar.setVisible(True)
            self.setWindowTitle(_t("control_room_title"))
            self.bottom_nav.setVisible(True)
        else:
            # 主显示：隐藏整条 Qt 状态栏，改用 Web Header 单行（含时钟/电量/EN）
            self.status_bar.setVisible(False)
            self.setWindowTitle(_t("home_title"))
            self.bottom_nav.setVisible(False)
        # 主显示保持整洁：藏顶栏按钮；底栏仅报警日志页再显示（主控室除外）
        self.button_container.setVisible(False)
        self.acquisition_btn.setVisible(False)
        if hasattr(self, "start_acq_btn"):
            self.start_acq_btn.setVisible(False)
        if hasattr(self, "stop_acq_btn"):
            self.stop_acq_btn.setVisible(False)
        self.save_data_btn.setVisible(False)
        self.user_management_btn.setVisible(False)
        self.logout_btn.setVisible(False)
        self.logout_btn.setText(_t("btn_login"))
        try:
            self.logout_btn.clicked.disconnect()
        except Exception:
            pass
        self.logout_btn.clicked.connect(self.login)
        self.logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white; border: none;
                border-radius: 8px; font-size: 14px; font-weight: bold; padding: 0 15px;
            }
            QPushButton:pressed { background-color: #45a049; }
        """)
        self._apply_page_index(0)
        if getattr(self, "control_room_mode", False):
            self._apply_control_room_nav_labels()
        if hasattr(self, "_update_home_health_and_faults"):
            try:
                self._update_home_health_and_faults()
            except Exception:
                pass
        if getattr(self, "control_room_mode", False) and hasattr(self, "_refresh_control_room_snapshot"):
            try:
                self._refresh_control_room_snapshot()
            except Exception:
                pass

    def update_ui_for_user_role(self):
        """根据用户角色更新UI"""
        from core.translation import _t
        if not self.is_logged_in():
            self.enter_public_mode()
            return
        
        role = self.current_user['role']
        self.bottom_nav.setVisible(True)
        self.acquisition_btn.setVisible(False)
        if hasattr(self, "start_acq_btn"):
            self.start_acq_btn.setVisible(False)
        if hasattr(self, "stop_acq_btn"):
            self.stop_acq_btn.setVisible(False)
        self.user_management_btn.setVisible(False)
        self.logout_btn.setVisible(False)
        self.save_data_btn.setVisible(False)
        if hasattr(self, "status_bar"):
            on_home = self.stacked_widget.currentIndex() == 0
            if getattr(self, "control_room_mode", False):
                self.status_bar.setVisible(True)
            else:
                self.status_bar.setVisible(not on_home)
            if self.status_bar.isVisible() and hasattr(self.status_bar, "set_clock_visible"):
                self.status_bar.set_clock_visible(True)
        if hasattr(self, "control_room_page"):
            self.control_room_page.set_login_visible(False)
            self.control_room_page.set_reorder_enabled(True)
        
        # 更新用户管理按钮可见性
        # 注意：这里需要检查本地角色，而不是用户管理器中的角色
            can_manage_users = self.user_manager.has_permission(Permission.MANAGE_USERS)
        
        # 更新操作按钮状态（清除数据和保存数据）
        # 注意：这里需要检查本地角色，而不是用户管理器中的角色
            can_clear_data = self.user_manager.has_permission(Permission.CLEAR_DATA)
            can_save_data = self.user_manager.has_permission(Permission.SAVE_DATA)
        self.acquisition_btn.setEnabled(can_clear_data)
        self.acquisition_btn.setVisible(can_clear_data)
        self.save_data_btn.setEnabled(can_save_data)
        self.save_data_btn.setVisible(can_save_data)
        
        # 更新logout/login按钮文本和功能
        from core.translation import _t
        if role == UserRole.VIEWER:
            self.logout_btn.setText(_t("btn_logout"))
        else:
            self.logout_btn.setText(_t("btn_logout"))
            try:
                self.logout_btn.clicked.disconnect()
            except:
                pass
            self.logout_btn.clicked.connect(self.logout)
        
        # 更新状态栏用户信息
        if 'username' in self.current_user:
            self.status_bar.update_user_info(self.current_user['username'], role)
        
        # 如果是管理员，启动超时计时器
        if self._is_privileged_user():
            self.timeout_manager.start_timer()
            self.log("管理登录已启动，3分钟无操作将自动退出", 'INFO')
        else:
            self.timeout_manager.stop_timer()
            self.status_bar.hide_timeout_display()
        
        # 更新设置页面控件状态
        self.update_settings_controls_for_role(role)
        if hasattr(self, "alarm_log_page") and hasattr(self.alarm_log_page, "update_auth_controls"):
            self.alarm_log_page.update_auth_controls()
        self._sync_control_room_action_bar()
    
    def update_settings_controls_for_role(self, role):
        """根据用户角色更新设置页面控件状态"""
        allow_viewer_settings = str(os.environ.get("ALLOW_VIEWER_SETTINGS", "0")).strip() == "1"
        can_maintain = (
            self.user_manager.has_permission(Permission.MODIFY_COMM_SETTINGS)
            or self.user_manager.has_permission(Permission.MODIFY_DETECTOR_SETTINGS)
            or self.user_manager.has_permission(Permission.MODIFY_CONTROL_SETTINGS)
            or self.user_manager.has_permission(Permission.MODIFY_DEVICE_CONTROL)
            or self.user_manager.has_permission(Permission.MODIFY_LOG_SETTINGS)
        )
        can_manage_pid = self.user_manager.has_permission(Permission.MANAGE_PRODUCT_ID)
        can_runtime = self.user_manager.has_permission(Permission.SAVE_DATA)
        if allow_viewer_settings:
            can_maintain = True
            can_manage_pid = True
            can_runtime = True
        can_clear_data = self.user_manager.has_permission(Permission.CLEAR_DATA) or allow_viewer_settings
        can_manage_users = self.user_manager.has_permission(Permission.MANAGE_USERS) or allow_viewer_settings

        for group_name in (
            'comm_group',
            'det_group',
            'ctrl_group',
            'keyboard_group',
            'device_group',
            'master_relay_group',
            'channel_gate_group',
            'log_group',
        ):
            group = getattr(self, group_name, None)
            if group is not None:
                group.setVisible(can_maintain)
        if hasattr(self, 'auto_save_group'):
            self.auto_save_group.setVisible(can_runtime)
        if hasattr(self, 'admin_ops_group'):
            self.admin_ops_group.setVisible(self.is_logged_in())
        
        # 禁用或启用设置控件
        if hasattr(self, 'tcp_enable_checkbox'):
            self.tcp_enable_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'tcp_host_input'):
            self.tcp_host_input.setEnabled(can_maintain)
        
        if hasattr(self, 'tcp_port_spin'):
            self.tcp_port_spin.setEnabled(can_maintain)
        
        if hasattr(self, 'serial_port_combo'):
            self.serial_port_combo.setEnabled(can_maintain)
        
        if hasattr(self, 'baudrate_combo'):
            self.baudrate_combo.setEnabled(can_maintain)
        if hasattr(self, 'refresh_serial_btn'):
            self.refresh_serial_btn.setEnabled(can_maintain)
        if hasattr(self, 'reconnect_serial_btn'):
            self.reconnect_serial_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'hv_spin'):
            self.hv_spin.setEnabled(can_maintain)
        if hasattr(self, 'hv_set_btn'):
            self.hv_set_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'threshold_spin'):
            self.threshold_spin.setEnabled(can_maintain)
        if hasattr(self, 'threshold_set_btn'):
            self.threshold_set_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'gain_stabilizer_btn'):
            self.gain_stabilizer_btn.setEnabled(can_maintain)
        if hasattr(self, 'ui_mode_combo'):
            self.ui_mode_combo.setEnabled(can_maintain)
        
        if hasattr(self, 'sensitivity_spin'):
            self.sensitivity_spin.setEnabled(can_maintain)
        
        if hasattr(self, 'sensitivity_set_btn'):
            self.sensitivity_set_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'sensitivity_read_btn'):
            self.sensitivity_read_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'relay0_checkbox'):
            self.relay0_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'relay1_checkbox'):
            self.relay1_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'relay2_checkbox'):
            self.relay2_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'relay_read_btn'):
            self.relay_read_btn.setEnabled(can_maintain)

        if hasattr(self, 'master_relay0_checkbox'):
            self.master_relay0_checkbox.setEnabled(can_maintain)
        if hasattr(self, 'master_relay1_checkbox'):
            self.master_relay1_checkbox.setEnabled(can_maintain)
        if hasattr(self, 'master_relay2_checkbox'):
            self.master_relay2_checkbox.setEnabled(can_maintain)
        if getattr(self, 'master_relay_r1_btn', None) is not None:
            self.master_relay_r1_btn.setEnabled(can_maintain)
        if getattr(self, 'master_relay_r2_btn', None) is not None:
            self.master_relay_r2_btn.setEnabled(can_maintain)
        if getattr(self, 'master_relay_apply_btn', None) is not None:
            self.master_relay_apply_btn.setEnabled(can_maintain)
        if hasattr(self, 'master_relay_read_btn') and self.master_relay_read_btn is not None:
            self.master_relay_read_btn.setEnabled(can_maintain)
        if getattr(self, 'master_force_gate_btn', None) is not None:
            self.master_force_gate_btn.setEnabled(can_maintain)
        if getattr(self, 'alarm_clear_mode_combo', None) is not None:
            self.alarm_clear_mode_combo.setEnabled(can_maintain)
        if getattr(self, 'alarm_clear_mode_read_btn', None) is not None:
            self.alarm_clear_mode_read_btn.setEnabled(can_maintain)
        if getattr(self, 'sensor_mode_combo', None) is not None:
            self.sensor_mode_combo.setEnabled(can_maintain)
        if getattr(self, 'sensor_mode_read_btn', None) is not None:
            self.sensor_mode_read_btn.setEnabled(can_maintain)
        if getattr(self, 'sensor_mode_write_btn', None) is not None:
            self.sensor_mode_write_btn.setEnabled(can_maintain)
        
        if hasattr(self, 'alarm_read_btn'):
            self.alarm_read_btn.setEnabled(can_maintain)

        if hasattr(self, 'expected_probe_spin'):
            self.expected_probe_spin.setEnabled(can_maintain)
        if hasattr(self, 'adopt_probe_count_btn'):
            self.adopt_probe_count_btn.setEnabled(can_maintain)
        if getattr(self, 'ir_installed_checkbox', None) is not None:
            self.ir_installed_checkbox.setEnabled(can_maintain)
        if hasattr(self, 'probe_location_edits'):
            for edit in self.probe_location_edits:
                edit.setEnabled(can_maintain)
        if hasattr(self, 'keyboard_enable_checkbox'):
            self.keyboard_enable_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'telemetry_checkbox'):
            self.telemetry_checkbox.setEnabled(can_maintain)
        
        if hasattr(self, 'log_path_input'):
            self.log_path_input.setEnabled(can_maintain and self.telemetry_checkbox.isChecked())
        
        if hasattr(self, 'select_path_btn'):
            self.select_path_btn.setEnabled(can_maintain and self.telemetry_checkbox.isChecked())
        
        # 自动保存控件权限控制
        if hasattr(self, 'auto_save_checkbox'):
            self.auto_save_checkbox.setEnabled(can_runtime)
        
        if hasattr(self, 'auto_save_interval_spin'):
            self.auto_save_interval_spin.setEnabled(can_runtime)
        
        if hasattr(self, 'auto_save_path_input'):
            self.auto_save_path_input.setEnabled(can_runtime and self.auto_save_enabled)
        
        if hasattr(self, 'auto_save_path_btn'):
            self.auto_save_path_btn.setEnabled(can_runtime and self.auto_save_enabled)

        for name in (
            'identity_maintenance_label',
            'product_id_spin',
            'product_id_read_btn',
            'product_id_write_btn',
            'product_id_unlock_btn',
            'product_id_lock_label',
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(can_manage_pid)
        if hasattr(self, "product_id_read_btn"):
            self.product_id_read_btn.setEnabled(can_manage_pid)
        if can_manage_pid and hasattr(self, "_refresh_product_id_lock_ui"):
            self._refresh_product_id_lock_ui()

        if hasattr(self, "settings_users_btn"):
            self.settings_users_btn.setVisible(can_manage_users)
            self.settings_users_btn.setEnabled(can_manage_users)
        if hasattr(self, "settings_clear_btn"):
            self.settings_clear_btn.setVisible(can_clear_data)
            self.settings_clear_btn.setEnabled(can_clear_data)
        if hasattr(self, "settings_save_btn"):
            self.settings_save_btn.setVisible(can_runtime)
            self.settings_save_btn.setEnabled(can_runtime)
        if hasattr(self, "settings_logout_btn"):
            self.settings_logout_btn.setVisible(self.is_logged_in())
            self.settings_logout_btn.setEnabled(self.is_logged_in())
        
        # 更新按钮文本提示
        if not can_maintain and not can_runtime:
            self.log("Current user is regular user, settings functions are disabled", 'INFO')
    
    def show_user_management(self):
        """显示用户管理对话框"""
        from core.translation import _t
        if not self.check_permission_before_action(_t("btn_user_mgmt"), Permission.MANAGE_USERS):
            return
        self.update_operate_time()

        from core.user_management_dialog import UserManagementDialog

        dialog = UserManagementDialog(self)
        dialog.exec_()
    
    def check_permission_before_action(self, action_name, permission_required):
        """在执行操作前检查权限。action_name 可为翻译键(action_*)或已翻译文案。"""
        from core.translation import _t
        # 若传入的是翻译键则翻译，否则原样显示
        action_text = _t(action_name) if action_name.startswith("action_") else action_name
        user_name = self.current_user['username'] if self.current_user else "Unknown"
        perm_str = str(permission_required)

        if not self.is_logged_in():
            show_warn(
                self,
                _t("msg_login_required_title"),
                _t("msg_login_required_text"),
            )
            return False

        if str(os.environ.get("ALLOW_VIEWER_SETTINGS", "0")).strip() == "1":
            if not getattr(self, "_warned_viewer_settings_bypass", False):
                self._warned_viewer_settings_bypass = True
                self.log("ALLOW_VIEWER_SETTINGS=1: all action permissions bypassed", "WARNING")
            return True
        # 首先检查当前用户的本地角色
        if self.current_user and self.current_user['role'] == UserRole.VIEWER:
            if not self.user_manager.has_permission(permission_required):
                show_warn(
                    self, 
                    _t("msg_perm_title"),
                    _t("msg_perm_denied", action=action_text, perm=perm_str, user=user_name)
                )
                return False
            from core.user_manager import Permission as Perm
            viewer_permissions = Perm.get_permissions_for_role(UserRole.VIEWER)
            if permission_required not in viewer_permissions:
                show_warn(
                    self, 
                    _t("msg_perm_title"),
                    _t("msg_perm_viewer", action=action_text, perm=perm_str)
                )
                return False
            return True
        else:
            if not self.user_manager.has_permission(permission_required):
                show_warn(
                    self, 
                    _t("msg_perm_title"),
                    _t("msg_perm_denied_user", action=action_text, perm=perm_str, user=user_name)
                )
                return False
            return True

    def unlock_product_id_edit(self):
        from core.translation import _t

        if not self.check_permission_before_action("Product ID maintenance", Permission.MANAGE_PRODUCT_ID):
            return False
        if not getattr(self, "primary_client_id", None):
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_need_target"))
            return False
        if not ask_confirm(
            self,
            _t("msg_product_id_title"),
            _t("msg_product_id_unlock_text"),
            danger=True,
        ):
            return False
        return super().unlock_product_id_edit()

    def read_product_id(self):
        from core.translation import _t

        if not self.check_permission_before_action("Read product ID", Permission.MANAGE_PRODUCT_ID):
            return False
        if not self.ensure_connection_ready():
            return False
        if getattr(self.config, "tcp_enabled", False):
            cid = getattr(self, "primary_client_id", None)
            if not cid:
                show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_need_target"))
                return False
            if not getattr(self, "worker", None) or not hasattr(self.worker, "send_command_to_client"):
                return False
            ok = self.worker.send_command_to_client(
                cid,
                "read_product_id",
                0x01,
                description="Read product ID (0x0D)",
            )
            if ok:
                self.log("Read product ID command sent", "INFO")
            return bool(ok)
        return super().read_product_id()

    def set_product_id(self):
        from core.translation import _t

        if not self.check_permission_before_action("Product ID maintenance", Permission.MANAGE_PRODUCT_ID):
            return False
        cid = getattr(self, "primary_client_id", None) if getattr(self.config, "tcp_enabled", False) else "serial_client"
        if not cid:
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_need_target"))
            return False
        key = self._current_probe_key(cid)
        live_pid = self._current_probe_live_product_id(cid)
        state = self.config.get_product_id_state(key, live_product_id=live_pid) if key else {"locked": True, "unlocked": False}
        if state.get("locked") and not state.get("unlocked"):
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_locked"))
            return False
        pid = int(self.product_id_spin.value())
        if pid > 0 and hasattr(self, "_product_id_is_unique") and not self._product_id_is_unique(pid, cid):
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_duplicate", pid=pid))
            return False
        if not ask_confirm(
            self,
            _t("msg_product_id_title"),
            _t("msg_product_id_write_text", pid=pid),
            danger=True,
        ):
            self._refresh_product_id_lock_ui(cid)
            return False
        ok = super().set_product_id()
        if ok:
            QTimer.singleShot(180, self.read_product_id)
            show_info(self, _t("msg_product_id_title"), _t("msg_product_id_readback_wait"))
        else:
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_set_fail"))
        return bool(ok)

    def on_product_id_feedback(self, packet):
        from core.translation import _t

        if int(getattr(packet, "status", 0) or 0) != 1:
            self._pending_product_id_write = None
            self._refresh_product_id_lock_ui(getattr(packet, "source_client_id", None))
            show_warn(self, _t("msg_product_id_title"), _t("msg_product_id_set_fail"))
            return
        self.log(
            "Product ID ack accepted (value=%d)" % (int(getattr(packet, "value", 0) or 0)),
            "INFO",
        )
    
    def set_high_voltage(self):
        """Set high voltage - with permission check"""
        if not self.check_permission_before_action("Set high voltage", Permission.MODIFY_DETECTOR_SETTINGS):
            return
        
        # 调用父类方法
        super().set_high_voltage()
    
    def set_threshold(self):
        """设置阈值 - 添加权限检查"""
        if not self.check_permission_before_action("Set threshold", Permission.MODIFY_DETECTOR_SETTINGS):
            return
        
        # 调用父类方法
        super().set_threshold()
    
    def toggle_gain_stabilizer(self):
        """切换增益稳定器 - 添加权限检查"""
        if not self.check_permission_before_action("Toggle gain stabilizer", Permission.MODIFY_CONTROL_SETTINGS):
            return
        
        # 调用父类方法
        super().toggle_gain_stabilizer()
    
    def set_sensitivity_coefficient(self):
        """设置灵敏度系数 - 添加权限检查"""
        if not self.check_permission_before_action("Set sensitivity coefficient", Permission.MODIFY_DEVICE_CONTROL):
            return
        
        # 调用父类方法
        super().set_sensitivity_coefficient()

    def reset_factory_defaults(self, all_probes: bool = False):
        """一键参数复位 — 需探测器设置权限"""
        if not self.check_permission_before_action("Factory reset", Permission.MODIFY_DETECTOR_SETTINGS):
            return False
        return super().reset_factory_defaults(all_probes=all_probes)
    
    def control_single_relay(self, relay_num, state):
        """控制单个继电器 - 添加权限检查"""
        if not self.check_permission_before_action("Control relay", Permission.MODIFY_DEVICE_CONTROL):
            cbs = (
                getattr(self, "relay0_checkbox", None),
                getattr(self, "relay1_checkbox", None),
                getattr(self, "relay2_checkbox", None),
            )
            if 0 <= int(relay_num) <= 2 and cbs[int(relay_num)] is not None:
                cb = cbs[int(relay_num)]
                cb.blockSignals(True)
                cb.setChecked(not bool(state))
                cb.blockSignals(False)
            return
        
        # 调用父类方法
        super().control_single_relay(relay_num, state)

    def control_master_relay(self, relay_num, state):
        """主控单路继电器 - 权限检查；关路0=复位全清；报警中关1/2=强行开闸。"""
        from core.translation import _t

        if not self.check_permission_before_action("Control master relay", Permission.MODIFY_DEVICE_CONTROL):
            cbs = (
                getattr(self, "master_relay0_checkbox", None),
                getattr(self, "master_relay1_checkbox", None),
                getattr(self, "master_relay2_checkbox", None),
            )
            if 0 <= int(relay_num) <= 2 and cbs[int(relay_num)] is not None:
                cb = cbs[int(relay_num)]
                cb.blockSignals(True)
                cb.setChecked(not bool(state))
                cb.blockSignals(False)
            return

        def _revert():
            cbs = (
                getattr(self, "master_relay0_checkbox", None),
                getattr(self, "master_relay1_checkbox", None),
                getattr(self, "master_relay2_checkbox", None),
            )
            if 0 <= int(relay_num) <= 2 and cbs[int(relay_num)] is not None:
                cb = cbs[int(relay_num)]
                cb.blockSignals(True)
                cb.setChecked(not bool(state))
                cb.blockSignals(False)

        # 关继电器 0 ≡ 通道复位全清（三路清 + decision→0x05）
        if int(relay_num) == 0 and not bool(state):
            if not ask_confirm(
                self,
                _t("msg_relay0_off_title"),
                _t("msg_relay0_off_text"),
                danger=True,
            ):
                _revert()
                return False

        # 报警中关 1/2：强行开闸（≠ 复位，decision 可能仍为 0x02/0x03）
        if int(relay_num) in (1, 2) and not bool(state):
            pkt = getattr(self, "latest_master_summary", None) or getattr(
                self, "_last_any_master_packet", None
            )
            if pkt is not None and pkt.is_channel_alarm():
                self.log(
                    "Force-open gate: closing master relay %d while decision=0x%02X"
                    % (int(relay_num), int(pkt.decision_result)),
                    "INFO",
                )

        return super().control_master_relay(relay_num, state)

    def force_open_master_gate(self):
        """强行开闸：报警中关继电器 1+2（不发 0x15，硬报可不解除）。"""
        from core.translation import _t

        if not self.check_permission_before_action(
            "Force open master gate", Permission.MODIFY_DEVICE_CONTROL
        ):
            return False
        if not ask_confirm(
            self,
            _t("msg_force_gate_title"),
            _t("msg_force_gate_text"),
            danger=True,
        ):
            return False
        ok1 = super().control_master_relay(1, False)
        ok2 = super().control_master_relay(2, False)
        return bool(ok1 or ok2)

    def apply_master_relay_mask(self):
        """主控批量继电器 - 权限检查"""
        if not self.check_permission_before_action("Control master relay mask", Permission.MODIFY_DEVICE_CONTROL):
            return False
        return super().apply_master_relay_mask()

    def read_master_relay_status(self):
        """主控读继电器状态 - 权限检查"""
        if not self.check_permission_before_action("Read master relay", Permission.MODIFY_DEVICE_CONTROL):
            return False
        return super().read_master_relay_status()
    
    def on_tcp_enable_changed(self, state):
        """TCP启用状态改变 - 添加权限检查"""
        if not self.check_permission_before_action("Modify TCP settings", Permission.MODIFY_COMM_SETTINGS):
            # 恢复原始状态
            self.tcp_enable_checkbox.blockSignals(True)
            self.tcp_enable_checkbox.setChecked(not state)
            self.tcp_enable_checkbox.blockSignals(False)
            return
        
        # 调用父类方法
        super().on_tcp_enable_changed(state)
    
    def on_tcp_host_changed(self, host):
        """TCP主机改变 - 添加权限检查"""
        if not self.check_permission_before_action("Modify TCP settings", Permission.MODIFY_COMM_SETTINGS):
            # 恢复原始值
            self.tcp_host_input.blockSignals(True)
            self.tcp_host_input.setText(self.config.tcp_host)
            self.tcp_host_input.blockSignals(False)
            return
        
        self._tcp_reconnect_backoff_sec = 0
        self._tcp_reconnect_key = None
        # 调用父类方法
        super().on_tcp_host_changed(host)
    
    def on_tcp_port_changed(self, port):
        """TCP端口改变 - 添加权限检查"""
        if not self.check_permission_before_action("Modify TCP settings", Permission.MODIFY_COMM_SETTINGS):
            # 恢复原始值
            self.tcp_port_spin.blockSignals(True)
            self.tcp_port_spin.setValue(self.config.tcp_port)
            self.tcp_port_spin.blockSignals(False)
            return
        
        self._tcp_reconnect_backoff_sec = 0
        self._tcp_reconnect_key = None
        # 调用父类方法
        super().on_tcp_port_changed(port)
    
    def on_serial_port_changed(self, port):
        """串口改变 - 添加权限检查"""
        if not self.check_permission_before_action("Modify serial port settings", Permission.MODIFY_COMM_SETTINGS):
            # 恢复原始值
            self.serial_port_combo.blockSignals(True)
            self.serial_port_combo.setCurrentText(self.config.device)
            self.serial_port_combo.blockSignals(False)
            return
        
        # 调用父类方法
        super().on_serial_port_changed(port)
    
    def on_baudrate_changed(self, baudrate_text):
        """波特率改变 - 添加权限检查"""
        if not self.check_permission_before_action("Modify serial port settings", Permission.MODIFY_COMM_SETTINGS):
            # 恢复原始值
            self.baudrate_combo.blockSignals(True)
            self.baudrate_combo.setCurrentText(str(self.config.baudrate))
            self.baudrate_combo.blockSignals(False)
            return
        
        # 调用父类方法
        super().on_baudrate_changed(baudrate_text)
    
    def toggle_raw_packet_logging(self, state):
        """切换原始数据包记录 - 添加权限检查"""
        if not self.check_permission_before_action("action_modify_log", Permission.MODIFY_LOG_SETTINGS):
            # 恢复原始状态
            self.telemetry_checkbox.blockSignals(True)
            self.telemetry_checkbox.setChecked(not state)
            self.telemetry_checkbox.blockSignals(False)
            return
        
        # 调用父类方法
        super().toggle_raw_packet_logging(state)
    
    def select_log_path(self):
        """选择日志路径 - 添加权限检查"""
        if not self.check_permission_before_action("action_modify_log", Permission.MODIFY_LOG_SETTINGS):
            return
        
        # 调用父类方法
        super().select_log_path()
    
    def toggle_auto_save(self, state):
        """切换自动保存开关 - 添加权限检查"""
        if not self.check_permission_before_action("action_modify_autosave", Permission.SAVE_DATA):
            # 恢复原始状态
            self.auto_save_checkbox.blockSignals(True)
            self.auto_save_checkbox.setChecked(not state)
            self.auto_save_checkbox.blockSignals(False)
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        # 调用父类方法
        super().toggle_auto_save(state)
    
    def set_auto_save_interval(self, interval):
        """设置自动保存间隔 - 添加权限检查"""
        if not self.check_permission_before_action("action_modify_autosave", Permission.SAVE_DATA):
            # 恢复原始值
            self.auto_save_interval_spin.blockSignals(True)
            self.auto_save_interval_spin.setValue(self.auto_save_interval)
            self.auto_save_interval_spin.blockSignals(False)
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        # 调用父类方法
        super().set_auto_save_interval(interval)
    
    def select_auto_save_path(self):
        """选择自动保存路径 - 添加权限检查"""
        if not self.check_permission_before_action("action_modify_autosave", Permission.SAVE_DATA):
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        # 调用父类方法
        super().select_auto_save_path()
    
    def logout(self):
        """退出登录，回到免登录主显示"""
        from core.translation import _t
        
        if not ask_confirm(
            self,
            _t("msg_logout_title"),
            _t("msg_logout_confirm"),
            danger=False,
        ):
            return

        self.timeout_manager.stop_timer()
        self.timeout_manager.last_operate_time = 0
        self.timeout_manager.save_state()
        old = self.current_user.get("username") if self.current_user else "?"
        self.enter_public_mode()
        self.log(f"Logged out ({old}) -> public home monitor", 'INFO')
    
    def _delayed_relogin(self):
        """延迟重新登录，确保旧的窗口完全关闭"""
        # 重新显示登录对话框
        from core.login_dialog import LoginDialog
        from PyQt5.QtWidgets import QApplication
        
        app = QApplication.instance()
        login_dialog = LoginDialog()
        if login_dialog.exec_() == LoginDialog.Accepted:
            try:
                from core.software_keyboard import get_keyboard_manager
                get_keyboard_manager().hide_keyboard()
            except Exception:
                pass
            # 重新创建主窗口
            from core.main_window import MainWindow
            current_user = login_dialog.get_current_user_info()
            
            # 重要：确保用户角色正确（从用户管理器获取真实角色）
            user_manager = self.user_manager
            if current_user and 'username' in current_user:
                actual_user = user_manager.get_current_user()
                if actual_user:
                    # 使用用户管理器中的真实角色，而不是登录对话框中的可能不正确的角色
                    current_user['role'] = actual_user.role
                    print(f"DEBUG: Logout后重新登录，设置用户角色为: {actual_user.role.value}")
            
            main_window = MainWindow(current_user)
            main_window.show()
    
    def closeEvent(self, event):
        """关闭事件 - 添加用户登出"""
        # 停止超时计时器
        self.timeout_manager.stop_timer()
        timer = getattr(self, "_idle_home_timer", None)
        if timer is not None:
            timer.stop()

        # 先停读/落盘（父类），再停报警写线程，避免关窗过程中的末包进不了 Excel
        super().closeEvent(event)

        try:
            from core.alarm_logger import get_alarm_logger
            get_alarm_logger().shutdown(timeout=10.0)
        except Exception as e:
            print(f"Alarm Excel shutdown: {e}")
        
        # 只有在不是从logout()方法调用时才执行用户登出
        # 因为logout()方法已经处理了用户登出
        if not hasattr(self, '_logout_called') or not self._logout_called:
            # 用户登出
            self.user_manager.logout()
    
    def eventFilter(self, obj, event):
        """事件过滤器：超时计时 + 左上角隐藏入口长按（兼容树莓派触摸）。"""
        # 鼠标/键盘/触摸均刷新空闲计时（部分板子 Touch 不合成 Mouse）
        # TouchUpdate 不计入回总览：电容屏幽灵移动会把人一直钉在子页
        if event.type() in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonDblClick,
            QEvent.KeyPress,
            QEvent.Wheel,
            QEvent.TouchBegin,
        ):
            self._note_ui_activity()
            self.update_operate_time()
            if event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin):
                home = getattr(self, "home_page", None)
                if home is not None and hasattr(home, "note_user_input"):
                    home.note_user_input()
        elif event.type() in (QEvent.TouchUpdate,):
            self.update_operate_time()

        self._handle_secret_corner_event(obj, event)

        return super().eventFilter(obj, event)

    def _widget_belongs_to_self(self, obj):
        """判断事件源是否属于本主窗口（含子控件）。"""
        w = obj if isinstance(obj, QWidget) else None
        while w is not None:
            if w is self:
                return True
            w = w.parentWidget()
        return False

    def _map_event_pos_to_self(self, event):
        """把鼠标/触摸事件坐标映射到主窗口客户区。失败返回 None。"""
        et = event.type()
        if et in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove):
            return self.mapFromGlobal(event.globalPos())
        if et in (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel):
            points = event.touchPoints()
            if not points:
                return None
            return self.mapFromGlobal(points[0].screenPos().toPoint())
        return None

    def _in_secret_corner(self, pos):
        if pos is None:
            return False
        s = self._SECRET_CORNER_SIZE
        return 0 <= pos.x() < s and 0 <= pos.y() < s

    def _handle_secret_corner_event(self, obj, event):
        """左上角长按约 1.5s → 回桌面。不依赖透明控件，避免 Ubuntu 点穿。"""
        if not self._widget_belongs_to_self(obj):
            return
        et = event.type()
        if et in (QEvent.MouseButtonPress, QEvent.TouchBegin):
            pos = self._map_event_pos_to_self(event)
            if self._in_secret_corner(pos):
                if not self._secret_hold_timer.isActive():
                    self._secret_hold_timer.start()
            else:
                self._secret_hold_timer.stop()
        elif et == QEvent.TouchUpdate:
            pos = self._map_event_pos_to_self(event)
            if not self._in_secret_corner(pos):
                self._secret_hold_timer.stop()
        elif et in (QEvent.MouseButtonRelease, QEvent.TouchEnd, QEvent.TouchCancel):
            self._secret_hold_timer.stop()

    def _note_ui_activity(self):
        self._last_ui_activity_at = time.time()

    def _idle_return_seconds(self):
        if self.is_logged_in():
            return int(self._IDLE_RETURN_LOGGED_IN_SEC)
        return int(self._IDLE_RETURN_PUBLIC_SEC)

    def _check_idle_return_home(self):
        """Leave overview unattended → come back. Duty wall must not stay on a subpage."""
        try:
            sw = getattr(self, "stacked_widget", None)
            if sw is None:
                return
            try:
                idx = int(sw.currentIndex())
            except Exception:
                return
            if idx == 0:
                return
            app = QApplication.instance()
            if app is not None:
                if app.activeModalWidget() is not None:
                    return
                if app.activePopupWidget() is not None:
                    return
            last = float(getattr(self, "_last_ui_activity_at", 0.0) or 0.0)
            if last <= 0:
                self._last_ui_activity_at = time.time()
                return
            if (time.time() - last) < self._idle_return_seconds():
                return
            self._return_home_after_idle()
        except Exception:
            return

    def _return_home_after_idle(self):
        from core.translation import _t
        try:
            from core.software_keyboard import get_keyboard_manager
            get_keyboard_manager().hide_keyboard()
        except Exception:
            pass
        try:
            self._apply_page_index(0)
            self._note_ui_activity()
            self._show_transient_notice(_t("msg_idle_return_home"), msec=2500)
            self.log("Idle on subpage -> returned to home/overview", "INFO")
        except Exception:
            return

    def update_operate_time(self):
        """更新操作时间（重置超时计时器）"""
        if self._is_privileged_user():
            self.timeout_manager.update_operate_time()
    
    def on_admin_timeout(self):
        """Admin idle timeout -> return to public home monitor."""
        from core.translation import _t
        if self._is_privileged_user():
            try:
                from core.software_keyboard import get_keyboard_manager
                get_keyboard_manager().hide_keyboard()
            except Exception:
                pass

            self.timeout_manager.last_operate_time = 0
            self.timeout_manager.save_state()
            self.enter_public_mode()
            self._show_transient_notice(_t("msg_admin_timeout_notice"), msec=4000)
            self.log("Privileged login timed out -> public home monitor", 'INFO')

    def _show_transient_notice(self, text, msec=3500):
        """顶栏短时提示，不挡监测主区（非模态）。"""
        from core.translation import _t
        bar = getattr(self, "status_bar", None)
        if bar is None or not hasattr(bar, "user_label"):
            return
        try:
            on_home = int(self.stacked_widget.currentIndex()) == 0
        except Exception:
            on_home = False
        # 平板总览藏 Qt 状态栏；强行显示会把 Web 顶栏顶乱，只写日志
        if on_home and not getattr(self, "control_room_mode", False):
            self.log(text, "INFO")
            return
        bar.setVisible(True)
        bar.user_label.setVisible(True)
        bar.user_label.setText(text)
        bar.user_label.setStyleSheet("""
            QLabel {
                margin-left: 10px;
                padding: 3px 10px;
                border-radius: 4px;
                background-color: #5d4037;
                color: #ffe0b2;
                font-weight: bold;
            }
        """)

        def _restore():
            on_home = self.stacked_widget.currentIndex() == 0
            if self.is_logged_in() and isinstance(getattr(self, "current_user", None), dict):
                user = self.current_user
                if getattr(self, "control_room_mode", False):
                    bar.setVisible(True)
                else:
                    bar.setVisible(not on_home)
                if bar.isVisible():
                    bar.update_user_info(user.get("username"), user.get("role"))
            else:
                if getattr(self, "control_room_mode", False):
                    bar.setVisible(True)
                    bar.update_user_info(_t("status_public_mode"), None)
                else:
                    bar.user_label.setVisible(False)
                    bar.setVisible(not on_home)

        QTimer.singleShot(int(msec), _restore)
    
    def login(self, preferred_page: int = None, required_for_page: bool = False):
        """Login from public/viewer mode. Returns True on success."""
        from core.login_dialog import LoginDialog
        from core.translation import _t
        
        login_dialog = LoginDialog()
        if login_dialog.exec_() != LoginDialog.Accepted:
            return False
        try:
            from core.software_keyboard import get_keyboard_manager
            get_keyboard_manager().hide_keyboard()
        except Exception:
            pass

        current_user = login_dialog.get_current_user_info()
        if not current_user:
            show_warn(self, _t("msg_login_failed_title"), _t("msg_login_failed_dialog"))
            return False

        actual_user = self.user_manager.get_current_user()
        if not actual_user:
            show_warn(self, _t("msg_login_failed_title"), _t("msg_login_failed_user_manager"))
            return False

        current_user['role'] = actual_user.role
        self.current_user = current_user
        self.update_ui_for_user_role()

        role_name = self._window_role_name(current_user['role'])
        username = current_user.get('username', '')
        self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")

        target = preferred_page if preferred_page is not None else 1
        self._apply_page_index(target)
        self.update_operate_time()
        self._note_ui_activity()

        # 登录成功不弹框：界面切到管理页/顶栏模式变化即反馈
        self.log(f"Logged in: {username} ({actual_user.role.value})", 'INFO')
        return True
    
    def on_timeout_timer_updated(self, remaining_seconds: int):
        """超时计时器更新回调"""
        if self._is_privileged_user():
            self.status_bar.update_timeout_display(remaining_seconds)
            
            # 最后30秒显示警告
            if remaining_seconds == 30:
                self.log("Admin mode will auto logout in 30 seconds", 'WARNING')
            elif remaining_seconds == 10:
                self.log("Admin mode will auto logout in 10 seconds", 'WARNING')
    
    def return_to_desktop(self, silent=False):
        """回到 Ubuntu 桌面（仅管理员）：最小化并保留 Dock 图标。

        不用 hide()：隐藏后 Dock 上可能找不到，再点图标又会被单实例直接退出。
        从 Dock 点回后自动全屏，无需再按 F11。
        限管理员使用，避免普通操作员误触退出监测界面。

        silent=True 时（隐藏入口：长按角/快捷键触发），非管理员静默忽略，不弹提示，
        以免暴露该隐藏功能的存在。
        """
        from core.translation import _t
        if not self._is_privileged_user():
            if not silent:
                show_info(
                    self,
                    _t("msg_login_required_title"),
                    _t("msg_desktop_need_admin"),
                )
            return
        self._restore_fullscreen_on_show = True
        # 先把“正常尺寸”设成当前屏幕几何，避免 showNormal 缩回启动时的 1024x600，
        # 导致再全屏时布局/底栏按小窗比例算乱。
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        if self.isFullScreen():
            self.showNormal()
            if screen is not None:
                self.setGeometry(screen.geometry())
            QTimer.singleShot(80, self._apply_minimize_to_desktop)
        else:
            self._apply_minimize_to_desktop()
        self.log("已回到桌面（后台继续运行；Dock 点回自动全屏）", 'INFO')

    def _apply_minimize_to_desktop(self):
        self.showMinimized()

    def restore_from_desktop(self):
        """从最小化/隐藏状态唤回，并按屏幕尺寸干净全屏。"""
        self._restore_fullscreen_on_show = False
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self._enter_fullscreen_clean()

    def _enter_fullscreen_clean(self):
        """按当前屏幕几何进入全屏，并刷新底部导航尺寸。"""
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._refresh_layout_after_fullscreen)
        QTimer.singleShot(100, self._refresh_layout_after_fullscreen)

    def _refresh_layout_after_fullscreen(self):
        """全屏生效后强制刷新底栏等布局，避免残留小窗尺寸。"""
        if hasattr(self, 'bottom_nav') and self.bottom_nav is not None:
            bar_h = int(getattr(self.bottom_nav, "_bar_height", 70) or 70)
            self.bottom_nav.setFixedHeight(bar_h)
            self.bottom_nav.refresh_hit_areas()
            self.bottom_nav.updateGeometry()
        cw = self.centralWidget()
        if cw is not None:
            cw.updateGeometry()
            lay = cw.layout()
            if lay is not None:
                lay.activate()

    def _setup_instance_activation_server(self):
        """监听二次启动请求，把已运行窗口唤回前台。"""
        try:
            from PyQt5.QtNetwork import QLocalServer
            QLocalServer.removeServer(INSTANCE_ACTIVATE_SERVER)
            self._activate_server = QLocalServer(self)
            if self._activate_server.listen(INSTANCE_ACTIVATE_SERVER):
                self._activate_server.newConnection.connect(self._on_second_instance_activate)
            else:
                self.log(
                    f"二次启动唤起服务监听失败: {self._activate_server.errorString()}",
                    'WARNING'
                )
        except Exception as e:
            self.log(f"二次启动唤起服务初始化失败: {e}", 'WARNING')

    def _on_second_instance_activate(self):
        while self._activate_server.hasPendingConnections():
            sock = self._activate_server.nextPendingConnection()
            if sock is not None:
                sock.close()
        self.restore_from_desktop()
        self.log("已由二次启动唤回窗口", 'INFO')

    def showEvent(self, event):
        """窗口显示时：必要时自动全屏。"""
        super().showEvent(event)
        if getattr(self, '_restore_fullscreen_on_show', False) and not self.isMinimized():
            self._restore_fullscreen_on_show = False
            QTimer.singleShot(0, self._enter_fullscreen_clean)

    def changeEvent(self, event):
        """从 Dock 恢复（取消最小化）时自动全屏。"""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if getattr(self, '_restore_fullscreen_on_show', False):
                if self.isVisible() and not (self.windowState() & Qt.WindowMinimized):
                    self._restore_fullscreen_on_show = False
                    QTimer.singleShot(50, self._enter_fullscreen_clean)

    def keyPressEvent(self, event):
        """按键事件处理 - 添加ESC键退出全屏和F11键切换全屏功能"""
        # 隐藏快捷键 Ctrl+Alt+D：回到 Ubuntu 桌面（仅管理员，静默）
        if event.key() == Qt.Key_D and \
           (event.modifiers() & Qt.ControlModifier) and (event.modifiers() & Qt.AltModifier):
            self.return_to_desktop(silent=True)
            return

        # ESC键退出全屏
        if event.key() == Qt.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
                self.log("退出全屏模式", 'INFO')
                return
        
        # F11键切换全屏/窗口模式
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
                self.log("退出全屏模式", 'INFO')
            else:
                self.showFullScreen()
                self.log("进入全屏模式", 'INFO')
            return
        
        # 调用父类的按键事件处理
        super().keyPressEvent(event)

    def on_language_changed(self, lang: str):
        """Handle language changed signal from status bar"""
        # Save to configuration
        self.config.update_settings(language=lang)
        self.config.save_settings()
        
        # Re-translate main window elements
        from core.translation import _t
        if self.current_user and 'username' in self.current_user:
            username = self.current_user['username']
            role_name = self._window_role_name(self.current_user['role'])
            self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
        else:
            self.setWindowTitle(
                _t("control_room_title") if getattr(self, "control_room_mode", False) else _t("sys_title")
            )
            
        self.save_data_btn.setText(_t("btn_save"))
        self.user_management_btn.setText(_t("btn_user_mgmt"))
        if hasattr(self, "status_bar") and hasattr(self.status_bar, "_retranslate_ops_buttons"):
            self.status_bar._retranslate_ops_buttons()
        # Viewer shows Login; Admin shows Logout
        if self.current_user and self.current_user.get('role') == UserRole.VIEWER:
            self.logout_btn.setText(_t("btn_login"))
        else:
            self.logout_btn.setText(_t("btn_logout"))
        
        if hasattr(self, "admin_ops_group"):
            self.admin_ops_group.setTitle(_t("set_admin_ops"))
            if hasattr(self, "admin_ops_hint"):
                self.admin_ops_hint.setText(_t("tip_admin_ops"))
            if hasattr(self, "settings_users_btn"):
                self.settings_users_btn.setText(_t("btn_user_mgmt"))
            if hasattr(self, "settings_clear_btn"):
                self.settings_clear_btn.setText(_t("btn_clear"))
            if hasattr(self, "settings_save_btn"):
                self.settings_save_btn.setText(_t("btn_save"))
            if hasattr(self, "settings_logout_btn"):
                self.settings_logout_btn.setText(_t("btn_logout"))

        # Retranslate settings page group boxes dynamically
        if hasattr(self, 'comm_group'):
            self.comm_group.setTitle(_t("set_comm_settings"))
            self.tcp_enable_checkbox.setText(_t("set_tcp_enable"))
            self.server_host_label.setText(_t("set_server_host"))
            self.tcp_host_input.setPlaceholderText(_t("set_server_host_placeholder"))
            self.server_port_label.setText(_t("set_server_port"))
            self.serial_port_label.setText(_t("set_serial_port"))
            self.refresh_serial_btn.setText(_t("btn_refresh"))
            self.baudrate_label.setText(_t("set_baudrate"))
            self.reconnect_serial_btn.setText(_t("btn_reconnect"))
            self.client_selection_label.setText(_t("set_display_client"))
            # Update first item in client selection combo
            if self.client_selection_combo.count() > 0:
                self.client_selection_combo.setItemText(0, _t("set_display_client_auto"))
        
        if hasattr(self, 'det_group'):
            self.det_group.setTitle(_t("set_det_settings"))
            self.bias_voltage_label.setText(_t("set_bias_voltage"))
            self.threshold_label.setText(_t("set_threshold"))
            if hasattr(self, "hv_set_btn"):
                self.hv_set_btn.setText(_t("btn_set_hv"))
            if hasattr(self, "threshold_set_btn"):
                self.threshold_set_btn.setText(_t("btn_set_threshold"))
                    
        if hasattr(self, 'ctrl_group'):
            self.ctrl_group.setTitle(_t("set_control"))
            self.gain_stabilizer_title_label.setText(_t("set_gain_stabilizer"))
            if hasattr(self, 'expected_probe_label'):
                self.expected_probe_label.setText(_t("set_expected_probes"))
            if hasattr(self, 'expected_probe_spin'):
                self.expected_probe_spin.setToolTip(_t("tip_expected_probes"))
            if hasattr(self, 'adopt_probe_count_btn'):
                self.adopt_probe_count_btn.setText(_t("btn_adopt_probe_count"))
                self.adopt_probe_count_btn.setToolTip(_t("tip_adopt_probe_count"))
            if getattr(self, 'ir_installed_checkbox', None) is not None:
                self.ir_installed_checkbox.setText(_t("set_ir_installed"))
                self.ir_installed_checkbox.setToolTip(_t("tip_ir_installed"))
            if hasattr(self, "ui_mode_label"):
                self.ui_mode_label.setText(_t("set_ui_mode"))
                self.ui_mode_label.setToolTip(_t("tip_ui_mode"))
            if hasattr(self, "ui_mode_combo"):
                self.ui_mode_combo.blockSignals(True)
                cur = self.ui_mode_combo.currentData()
                self.ui_mode_combo.setItemText(0, _t("set_ui_mode_tablet"))
                self.ui_mode_combo.setItemText(1, _t("set_ui_mode_control_room"))
                idx = self.ui_mode_combo.findData(cur)
                if idx >= 0:
                    self.ui_mode_combo.setCurrentIndex(idx)
                self.ui_mode_combo.setToolTip(_t("tip_ui_mode"))
                self.ui_mode_combo.blockSignals(False)
            if hasattr(self, 'probe_locations_label'):
                self.probe_locations_label.setText(_t("set_probe_locations"))
                self.probe_locations_label.setToolTip(_t("tip_probe_locations"))
            try:
                from core.translation import stock_probe_location_index
                locs = list(getattr(self.config, "probe_slot_locations", None) or [])
                if locs and all(
                    (not str(x).strip()) or stock_probe_location_index(x) >= 0
                    for x in locs
                ):
                    self.config.set_probe_slot_locations([])
            except Exception:
                pass
            if hasattr(self, 'refresh_probe_location_edits'):
                self.refresh_probe_location_edits()
            if hasattr(self, "factory_reset_label"):
                self.factory_reset_label.setText(_t("set_factory_reset"))
            if hasattr(self, "reset_defaults_current_btn"):
                self.reset_defaults_current_btn.setText(_t("btn_reset_current"))
                self.reset_defaults_current_btn.setToolTip(_t("tip_reset_defaults"))
            if hasattr(self, "reset_defaults_all_btn"):
                self.reset_defaults_all_btn.setText(_t("btn_reset_all"))
                self.reset_defaults_all_btn.setToolTip(_t("tip_reset_defaults"))
            self.update_control_labels()
            
        if hasattr(self, 'keyboard_group'):
            self.keyboard_group.setTitle(_t("set_keyboard"))
            self.keyboard_enable_checkbox.setText(_t("set_keyboard_enable"))
            if self.keyboard_enable_checkbox.isChecked():
                self.keyboard_status_label.setText(_t("status_enabled"))
            else:
                self.keyboard_status_label.setText(_t("status_disabled"))
                
        if hasattr(self, 'device_group'):
            self.device_group.setTitle(_t("set_device_status"))
            self.product_id_title_label.setText(_t("label_product_id"))
            if hasattr(self, "identity_maintenance_label"):
                self.identity_maintenance_label.setText(_t("set_identity_maintenance"))
                self.identity_maintenance_label.setToolTip(_t("tip_identity_maintenance"))
            if hasattr(self, "product_id_spin"):
                self.product_id_spin.setToolTip(_t("tip_product_id_maintenance"))
            if hasattr(self, "product_id_read_btn"):
                self.product_id_read_btn.setText(_t("btn_read_product_id"))
                self.product_id_read_btn.setToolTip(_t("tip_product_id_maintenance"))
            if hasattr(self, "product_id_write_btn"):
                self.product_id_write_btn.setText(_t("btn_write_product_id"))
                self.product_id_write_btn.setToolTip(_t("tip_product_id_maintenance"))
            if hasattr(self, "product_id_unlock_btn"):
                self.product_id_unlock_btn.setText(_t("btn_unlock_product_id"))
                self.product_id_unlock_btn.setToolTip(_t("tip_product_id_maintenance"))
            if hasattr(self, "_refresh_product_id_lock_ui"):
                self._refresh_product_id_lock_ui()
            self.sensitivity_title_label.setText(_t("label_sensitivity"))
            self.sensitivity_set_btn.setText(_t("btn_set"))
            self.sensitivity_read_btn.setText(_t("btn_read"))
            self.relay_control_title_label.setText(_t("set_probe_relay_control"))
            self.relay_read_btn.setText(_t("btn_read_status"))
            if hasattr(self, 'probe_relay_hint_label'):
                self.probe_relay_hint_label.setText(_t("tip_probe_relay_hint"))
            
            # Retranslate relay status label dynamically
            if hasattr(self, 'relay_status_label'):
                states = getattr(self, 'relay_states', None)
                if states is not None and len(states) >= 3:
                    r0, r1, r2 = states[0], states[1], states[2]
                    self.relay_status_label.setText(_t("relay_status_format", r0=int(r0), r1=int(r1), r2=int(r2)))
                else:
                    self.relay_status_label.setText(_t("set_relay_status"))
                    
            self.alarm_status_title_label.setText(_t("card_alarm_title"))
            self.alarm_read_btn.setText(_t("btn_read_alarm"))
            self.occupancy_title_label.setText(_t("set_occupancy"))
            self.counter_title_label.setText(_t("set_counter"))

        if hasattr(self, 'master_relay_group'):
            self.master_relay_group.setTitle(_t("set_master_relay"))
            if hasattr(self, 'master_relay_control_title'):
                self.master_relay_control_title.setText(_t("set_master_relay_control"))
            self.master_relay0_checkbox.setText("Relay 0")
            self.master_relay1_checkbox.setText("Relay 1")
            self.master_relay2_checkbox.setText("Relay 2")
            if getattr(self, 'master_relay_r1_btn', None) is not None:
                self.master_relay_r1_btn.setText(_t("btn_master_relay_r1"))
                self.master_relay_r1_btn.setToolTip(_t("tip_master_relay_single"))
            if getattr(self, 'master_relay_r2_btn', None) is not None:
                self.master_relay_r2_btn.setText(_t("btn_master_relay_r2"))
                self.master_relay_r2_btn.setToolTip(_t("tip_master_relay_single"))
            if getattr(self, 'master_relay_apply_btn', None) is not None:
                self.master_relay_apply_btn.setText(_t("btn_master_relay_apply"))
                self.master_relay_apply_btn.setToolTip(_t("tip_master_relay_apply"))
            if self.master_relay_read_btn is not None:
                self.master_relay_read_btn.setText(_t("btn_read_status"))
            if hasattr(self, 'master_relay_hint_label'):
                self.master_relay_hint_label.setText(_t("tip_master_relay_hint"))
            if getattr(self, 'master_force_gate_btn', None) is not None:
                self.master_force_gate_btn.setText(_t("btn_force_open_gate"))
                self.master_force_gate_btn.setToolTip(_t("tip_force_open_gate"))
            states = getattr(self, 'master_relay_states', None)
            if states is not None and len(states) >= 3:
                r0, r1, r2 = states[0], states[1], states[2]
                mask = (int(r0) & 1) | ((int(r1) & 1) << 1) | ((int(r2) & 1) << 2)
                self.master_relay_status_label.setText(
                    _t("master_relay_status_format", r0=int(r0), r1=int(r1), r2=int(r2), mask=mask)
                )
            else:
                self.master_relay_status_label.setText(_t("set_master_relay_status"))

        if hasattr(self, 'channel_gate_group'):
            self.channel_gate_group.setTitle(_t("set_channel_gate"))
            if getattr(self, 'channel_gate_hint_label', None) is not None:
                self.channel_gate_hint_label.setText(_t("tip_channel_gate"))
            if getattr(self, 'alarm_clear_mode_label', None) is not None:
                self.alarm_clear_mode_label.setText(_t("set_alarm_clear_mode"))
            if getattr(self, 'alarm_clear_mode_combo', None) is not None:
                combo = self.alarm_clear_mode_combo
                cur = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(_t("latch_mode_auto"), 0)
                combo.addItem(_t("latch_mode_latch"), 1)
                idx = combo.findData(cur if cur is not None else 0)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                combo.setToolTip(_t("tip_alarm_clear_mode"))
                combo.blockSignals(False)
            if getattr(self, 'alarm_clear_mode_read_btn', None) is not None:
                self.alarm_clear_mode_read_btn.setText(_t("btn_read_clear_mode"))
            if getattr(self, 'sensor_mode_label', None) is not None:
                self.sensor_mode_label.setText(_t("set_sensor_mode"))
            if getattr(self, 'sensor_mode_combo', None) is not None:
                combo = self.sensor_mode_combo
                cur = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(_t("sensor_mode_ir"), 0)
                combo.addItem(_t("sensor_mode_radar"), 1)
                combo.addItem(_t("sensor_mode_unconfigured"), 2)
                idx = combo.findData(cur if cur is not None else 2)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                combo.setToolTip(_t("tip_sensor_mode"))
                combo.blockSignals(False)
            if getattr(self, 'sensor_mode_read_btn', None) is not None:
                self.sensor_mode_read_btn.setText(_t("btn_read_sensor_mode"))
            if getattr(self, 'sensor_mode_write_btn', None) is not None:
                self.sensor_mode_write_btn.setText(_t("btn_write_sensor_mode"))
                self.sensor_mode_write_btn.setToolTip(_t("tip_write_sensor_mode"))
            if getattr(self, 'sensor_mode_status_label', None) is not None:
                pkt = getattr(self, "latest_master_summary", None)
                if pkt is not None and self.is_master_online():
                    self._update_sensor_mode_status_label(pkt, lang=lang)
                else:
                    self.sensor_mode_status_label.setText(_t("tip_sensor_mode"))
                    self.sensor_mode_status_label.setStyleSheet(
                        "color: #888888; font-size: 11px;"
                    )
                    self._refresh_commissioning_status(None, lang=lang)
            
        if hasattr(self, 'log_group'):
            self.log_group.setTitle(_t("set_raw_logging"))
            self.telemetry_checkbox.setText(_t("set_logging_enable"))
            self.log_path_input.setPlaceholderText(_t("set_logging_placeholder"))
            self.select_path_btn.setText(_t("btn_browse"))
            
        if hasattr(self, 'auto_save_group'):
            self.auto_save_group.setTitle(_t("set_auto_save"))
            self.auto_save_checkbox.setText(_t("set_auto_save_enable"))
            self.save_interval_title_label.setText(_t("set_save_interval"))
            _tip_archive = _t("tip_auto_save_interval")
            self.save_interval_title_label.setToolTip(_tip_archive)
            if hasattr(self, "auto_save_interval_spin"):
                self.auto_save_interval_spin.setToolTip(_tip_archive)
            self.save_path_title_label.setText(_t("set_save_path"))
            self.auto_save_path_input.setPlaceholderText(_t("set_save_path_placeholder"))
            self.auto_save_path_btn.setText(_t("btn_browse"))
            self.update_auto_save_counter_label()
            self.update_auto_save_interval_label(self.auto_save_interval)
        
        # Re-translate child pages
        if hasattr(self, 'bottom_nav'):
            self.bottom_nav.retranslate_ui()
        if hasattr(self, 'acquisition_btn'):
            self.acquisition_btn.retranslate_ui()
        if hasattr(self, "start_acq_btn"):
            self.start_acq_btn.setText(_t("btn_acq_start"))
        if hasattr(self, "stop_acq_btn"):
            self.stop_acq_btn.setText(_t("btn_acq_stop"))
        if hasattr(self, "_sync_acq_action_buttons"):
            self._sync_acq_action_buttons()
            
        # Call retranslate_ui on each page if they support it
        for page in [
            self.home_page, self.control_room_page, self.overview_page, self.spectrum_page,
            self.clients_page, self.alarm_log_page, self.settings_page,
        ]:
            if hasattr(page, 'retranslate_ui'):
                page.retranslate_ui()
        self._apply_control_room_nav_labels()

        # Plot axis titles follow language
        if hasattr(self, 'retranslate_plot_labels'):
            self.retranslate_plot_labels()

        # Rebuild home HMI strings that were cached in Chinese/English
        try:
            if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
                self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
            else:
                self._refresh_home_from_probes(self.client_data)
        except Exception:
            pass
        try:
            if hasattr(self, "update_system_status"):
                self.update_system_status()
        except Exception:
            pass

        # 状态栏角色/公共模式文案跟语种（含维护用户 Maintainer）
        self._refresh_status_bar_user_language()

        # 主控室：snapshot 会从 home 拷贝动态文案；必须先 snapshot 再 retranslate，
        # 且延迟一拍（与「进日志再返回」同效果），避免同栈里被旧中文盖掉。
        if getattr(self, "control_room_mode", False):
            self._schedule_control_room_language_refresh()
        else:
            home = getattr(self, "home_page", None)
            if home is not None:
                if hasattr(home, "schedule_language_web_flush"):
                    home.schedule_language_web_flush()
                elif hasattr(home, "schedule_web_flush"):
                    if hasattr(home, "_last_web_payload"):
                        home._last_web_payload = None
                    home.schedule_web_flush(immediate=True)
                
        # Force a UI update
        self.update()

    def _refresh_status_bar_user_language(self):
        """换语后刷新状态栏角色文案（公共模式 / 管理员 / 维护用户 / 查看者）。"""
        if not hasattr(self, "status_bar"):
            return
        from core.translation import _t
        try:
            if self.is_logged_in() and isinstance(getattr(self, "current_user", None), dict):
                user = self.current_user
                self.status_bar.update_user_info(user.get("username"), user.get("role"))
                return
            idx = int(self.stacked_widget.currentIndex()) if hasattr(self, "stacked_widget") else 0
            if idx == 4:
                self.status_bar.update_user_info(_t("status_public_readonly_log"), None)
            else:
                self.status_bar.update_user_info(_t("status_public_mode"), None)
        except Exception:
            pass

    def _refresh_window_title_language(self):
        from core.translation import _t
        try:
            if self.current_user and "username" in self.current_user:
                username = self.current_user["username"]
                role_name = self._window_role_name(self.current_user.get("role"))
                self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
            else:
                self.setWindowTitle(
                    _t("control_room_title")
                    if getattr(self, "control_room_mode", False)
                    else _t("sys_title")
                )
        except Exception:
            pass

    def _schedule_control_room_language_refresh(self):
        """主控室总览换语：立即一次 + 事件循环后再两次（对齐切页返回）。"""
        self._refresh_control_room_language_now()
        QTimer.singleShot(0, self._refresh_control_room_language_now)
        QTimer.singleShot(80, self._refresh_control_room_language_now)

    def _refresh_control_room_language_now(self):
        if not getattr(self, "control_room_mode", False):
            return
        from core.translation import TranslationManager, _t
        # 防止中途被别的逻辑改回
        try:
            want = str(getattr(self.config, "language", "") or "")
            if want in ("zh", "en"):
                TranslationManager().set_language(want)
        except Exception:
            pass
        try:
            if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
                self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
            else:
                self._refresh_home_from_probes(self.client_data)
        except Exception:
            pass
        try:
            # 健康/故障行也按新语种重算后再拷到主控室
            self._update_home_health_and_faults()
        except Exception:
            pass
        try:
            self._refresh_control_room_snapshot()
        except Exception:
            pass
        cr = getattr(self, "control_room_page", None)
        if cr is not None and hasattr(cr, "retranslate_ui"):
            try:
                # 必须在 snapshot 之后：用 _t/kind 压过拷贝来的旧语种
                cr.retranslate_ui()
            except Exception:
                pass
            try:
                cr.update()
                cr.repaint()
            except Exception:
                pass
        self._refresh_status_bar_user_language()
        self._refresh_window_title_language()