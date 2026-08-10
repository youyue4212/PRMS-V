import sys
import glob
import time
import random
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

# 概览报警卡内说明区最多显示行数（超出部分在卡片内滚动，完整内容放 tooltip）
_FAULT_DESC_MAX_LINES = 2
_MASTER_FAULT_CLIENT_ID = "master"


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

# 导入超时管理器模块
from core.timeout_manager import get_timeout_manager

# 二次启动时通过本地套接字唤起已运行实例（hide/最小化后点图标用）
INSTANCE_ACTIVATE_SERVER = "daq_tablet_activate"


class MainWindow(QMainWindow, UIBase):
    # 左上角隐藏入口热区（相对主窗口坐标，像素）。树莓派触摸宜略大。
    _SECRET_CORNER_SIZE = 80
    """Main application window"""
    def __init__(self, current_user=None):
        super().__init__()
        
        # 存储用户信息
        self.current_user = current_user
        self.user_manager = get_user_manager()
        
        # 初始化超时管理器
        self.timeout_manager = get_timeout_manager()
        
        # Set window title based on user role
        from core.translation import _t
        if current_user and 'username' in current_user:
            username = current_user['username']
            role_name = "Admin" if current_user['role'] == UserRole.ADMIN else "User"
            self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
        else:
            self.setWindowTitle(_t("home_title"))
        
        # 设置窗口初始大小，但不固定，允许外部控制全屏或调整大小
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
        if current_user and 'username' in current_user:
            self.status_bar.update_user_info(current_user['username'], current_user['role'])
        else:
            self.status_bar.update_user_info(_t("status_public_mode"), None)
        main_layout.addWidget(self.status_bar)
        
        # Stacked widget for pages
        # 0: 主显示(免登录)  1: 原实时概览  2:能谱  3:诊断  4:报警日志  5:设置
        self.stacked_widget = QStackedWidget()

        self.home_page = HomePage(self)
        self.home_page.channel_reset_btn.clicked.connect(self.request_channel_alarm_reset)
        self.overview_page = OverviewPage(self)
        self.spectrum_page = SpectrumPage(self)
        self.clients_page = ClientsPage(self)
        self.alarm_log_page = AlarmLogPage(self)
        self.settings_page = SettingsPage(self)

        self.stacked_widget.addWidget(self.home_page)
        self.stacked_widget.addWidget(self.overview_page)
        self.stacked_widget.addWidget(self.spectrum_page)
        self.stacked_widget.addWidget(self.clients_page)
        self.stacked_widget.addWidget(self.alarm_log_page)
        self.stacked_widget.addWidget(self.settings_page)
        
        main_layout.addWidget(self.stacked_widget, 1)
        
        # Acquisition button container - 优化为小屏幕（登录后才显示）
        self.button_container = QWidget()
        self.button_container.setStyleSheet("background-color: #1a1a1a;")
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(20, 5, 20, 5)  # 大幅减少边距，适应小屏幕
        
        # 使用更小的按钮高度
        button_height = 35  # 从40减少到35
        
        self.acquisition_btn = AcquisitionButton()
        self.acquisition_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.acquisition_btn)
        
        # Add save data button
        self.save_data_btn = QPushButton(_t("btn_save"))
        self.save_data_btn.setFixedHeight(button_height)
        self.save_data_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 12px;
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
        
        # Add user management button (visible only to admin)
        self.user_management_btn = QPushButton(_t("btn_user_mgmt"))
        self.user_management_btn.setFixedHeight(button_height)
        self.user_management_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #9C27B0;
                color: white;
                border: none;
                border-radius: 12px;
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
                border-radius: 12px;
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
        main_layout.addWidget(self.button_container)
        
        # Bottom navigation
        self.bottom_nav = BottomNavBar()
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

        # 连接超时管理器信号
        self.timeout_manager.timeout_occurred.connect(self.on_admin_timeout)
        self.timeout_manager.timer_updated.connect(self.on_timeout_timer_updated)
        
        # 连接语言切换信号
        self.status_bar.language_changed.connect(self.on_language_changed)
        
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
        
        # 根据用户权限更新UI（未登录=主显示监视模式）
        self.update_ui_for_user_role()
        for page in (
            self.home_page, self.overview_page, self.spectrum_page,
            self.clients_page, self.alarm_log_page, self.settings_page,
        ):
            if hasattr(page, "retranslate_ui"):
                page.retranslate_ui()
        if hasattr(self.bottom_nav, "retranslate_ui"):
            self.bottom_nav.retranslate_ui()
        
        # 如果是管理员模式，启动超时计时器
        if self.current_user and self.current_user['role'] == UserRole.ADMIN:
            self.timeout_manager.start_timer()
            self.log("Admin mode started, will auto logout after 3 minutes of inactivity", 'INFO')






        # Simulation timer
    def check_device_connection(self):
        # 确保TCP连接已建立
        if isinstance(self.worker, TcpPacketWorker):
            tcp_ready = self.worker.is_tcp_ready()
            self.log(f"TCP ready check: {tcp_ready}", 'DEBUG')
            
            if not tcp_ready:
                # 尝试重新连接
                self.log("TCP not ready, attempting to reconnect...", 'INFO')
                if self.worker.connect_tcp(self.config.tcp_host, self.config.tcp_port, self.config.tcp_mode):
                    self.log("TCP reconnection successful", 'INFO')
                else:
                    self.log("TCP reconnection failed", 'WARNING')
        
        is_connected = self.worker.try_connection()
        self.status_bar.update_connection_status(is_connected)
        
        # 如果连接失败且是串口模式，更新串口设备下拉列表
        if not is_connected and isinstance(self.worker, SerialPacketWorker):
            self.log("Serial connection failed, updating serial port list...", 'INFO')
            self.update_serial_port_combo()
        
        # 自动开始/停止数据采集
        if is_connected and not self.is_acquiring:
            # 连接建立，自动开始采集
            self.log(f"Connection detected (is_connected={is_connected}, is_acquiring={self.is_acquiring}), starting acquisition automatically", 'INFO')
            success = self.start_acquisition()
            if success:
                self.log("Acquisition started successfully", 'INFO')
            else:
                self.log("Failed to start acquisition", 'WARNING')
        elif not is_connected and self.is_acquiring:
            # 连接断开，自动停止采集
            self.log("Connection lost, stopping acquisition automatically", 'INFO')
            self.stop_acquisition()
        else:
            # 调试信息
            self.log(f"Connection status: is_connected={is_connected}, is_acquiring={self.is_acquiring}", 'DEBUG')
            
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
        """Switch between pages. Index 0 (home) is public; others require login."""
        if index != 0 and not self.is_logged_in():
            # 需要登录；取消则静默回主显示，不再弹「需要登录」
            if self.login(preferred_page=index, required_for_page=True):
                return
            self.stacked_widget.setCurrentIndex(0)
            self.bottom_nav.set_active_button(0)
            return

        self.stacked_widget.setCurrentIndex(index)
        self.bottom_nav.set_active_button(index)
        if hasattr(self, "status_bar"):
            # 主显示用 Web 单行顶栏；其它页恢复 Qt 状态栏
            self.status_bar.setVisible(index != 0)
            if index != 0 and hasattr(self.status_bar, "set_clock_visible"):
                self.status_bar.set_clock_visible(True)
        if index == 0:
            # 切回主显示时立即按当前源刷新（主控 L2 或探头回退）
            if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
                self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
            else:
                self._refresh_home_from_probes(self.client_data)
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
    
    def clear_data(self):
        """Clear all data (spectrum, time series, etc.)"""
        from core.translation import _t
        # 检查权限
        if not self.check_permission_before_action("action_clear_data", Permission.CLEAR_DATA):
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        if self.is_acquiring:
            # 如果正在采集，询问用户是否要先停止采集
            reply = QMessageBox.question(
                self,
                _t("msg_acq_running_title"),
                _t("msg_acq_running_text"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                # 停止采集（不会断开TCP连接，只是停止数据处理）
                self.stop_acquisition()
                self.log("Acquisition stopped for data clearing (TCP connection remains)", 'INFO')
                
                # 等待一小段时间确保采集完全停止
                import time
                time.sleep(0.5)
            else:
                # 用户取消
                return
        
        # 确认清除数据
        reply = QMessageBox.question(
            self,
            _t("msg_clear_data_title"),
            _t("msg_clear_data_text"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # 重置所有数据
            self.reset_plots()
            
            # 重置当前状态数据
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.client_data = {}
            self.client_time_series = {}
            self.client_spectrum_data = {}
            self.primary_client_id = None
            self.total_count_rate = 0
            
            # 如果有数据更新回调，通知UI清零
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, {})
            
            # 更新原概览 + 主显示
            self.overview_page.radiation_card.update_data("0 cps", "")
            self.overview_page.status_card.update_data("0" + chr(176) + "C", "0 V")
            if hasattr(self, "home_page"):
                self.home_page.total_cps_label.setText("0")
                self.home_page.update_probe_tiles_from_master(None, False)
            
            self.log("All data cleared", 'INFO')
    
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
        self.home_page.set_master_link_status(False, lang=lang, link_only=link_only)
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
            return
        page.total_cps_label.setText("%d" % total)
        # master_online=True：CPS 已是正式显示源，不再标「(探头)」后缀
        page.update_probe_tiles_from_probe_list(entries, lang=lang, show_as_primary=True)

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
        cps = float(getattr(latest, "total_cps", 0) or 0) if latest is not None else 0.0
        mid = int(getattr(latest, "master_id", 0) or 0) if latest is not None else 0

        try:
            from core.alarm_logger import get_alarm_logger
            alarm_logger = get_alarm_logger()
        except Exception:
            alarm_logger = None

        for code in sorted(current - previous):
            name, desc, severity, _ = FaultCode.get_info(code)
            self.log(
                "[MASTER FAULT DETECTED] Code: %s | %s: %s" % (code, name, desc),
                severity,
            )
            if alarm_logger is not None:
                try:
                    alarm_logger.log_alarm_event(
                        client_id="master_fault_" + code,
                        alarm_status=True,
                        count_rate=cps,
                        temperature=0.0,
                        hv=0.0,
                        product_id=mid,
                        sensitivity=0,
                        alarm_type="MasterFault",
                        message="%s %s" % (code, name),
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
                        count_rate=cps,
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

    def _update_master_diagnostics(self):
        """Inject master-related faults into the shared diagnostics table."""
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not getattr(dm, "is_acquiring", False) or not dm.acquisition_start_time:
            return
        now = time.time()
        startup_age = now - float(dm.acquisition_start_time or now)
        master_cid = getattr(self, "master_client_id", None)
        last_any = float(getattr(self, "_last_any_master_at", 0) or 0)
        last_sane = float(getattr(self, "_last_sane_master_at", 0) or 0)
        latest = getattr(self, "latest_master_summary", None)

        if (not master_cid or last_any <= 0) and startup_age > dm.NO_DATA_STARTUP_SEC:
            dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M101)
        else:
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M101)

        if last_any > 0 and (now - last_any) > dm.COMM_TIMEOUT_SEC:
            dm.add_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)
        else:
            dm.remove_fault(_MASTER_FAULT_CLIENT_ID, FaultCode.M102)

        if last_any > 0 and (now - last_any) <= dm.COMM_TIMEOUT_SEC:
            if last_sane <= 0 or (now - last_sane) > dm.COMM_TIMEOUT_SEC:
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
        master_faults = self._master_fault_entries()
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        probe_online = len(self.get_online_probe_client_ids()) if hasattr(self, "get_online_probe_client_ids") else 0
        target = expected if expected > 0 else max(probe_online, int(getattr(pkt, "probe_count_cfg", 0) or 0), 1)
        ir_degraded = bool(pkt is not None and getattr(pkt, "ir_degraded", False))

        # --- structured health KV rows for Web HMI ---
        probe_tone = "green" if probe_online >= target and target > 0 else "amber"
        probe_comm = _t("health_probe_online", online=probe_online, expected=target)
        if ir_degraded:
            ir_status, ir_tone = _t("health_ir_degraded"), "amber"
        else:
            ir_status, ir_tone = _t("health_ir_ok"), "green"

        if master_faults:
            page.health_indicator.load(get_icon_svg('alarm_inactive'))
            offline_mf = FaultCode.M101 in master_faults or FaultCode.M102 in master_faults
            page.health_status_label.setText(
                _t("status_health_offline") if offline_mf else _t("status_health_fault")
            )
            reason = " / ".join(master_faults)
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
        elif ir_degraded:
            page.health_indicator.load(get_icon_svg('occupancy_active'))
            page.health_status_label.setText(_t("status_health_degraded"))
            self._set_home_status_style(
                page.health_status_label, "#ffb74d",
                "rgba(255, 183, 77, 0.12)", "rgba(255, 183, 77, 0.35)"
            )
            page.health_desc_label.setText(
                _t("desc_health_master_degraded", online=probe_online, expected=target)
            )
            master_hw, master_tone = _t("health_master_ok"), "green"
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

        active_faults = getattr(self.diagnostics_manager, "get_all_active_faults", lambda: [])()
        unique_msgs = []
        for client_id, code, _, _, _, _ in active_faults:
            msg = self.format_fault_operator_message(client_id, code)
            if msg and msg not in unique_msgs:
                unique_msgs.append(msg)

        n_fault = len(unique_msgs)
        if ir_degraded:
            # Prefer channel hint from hit_mask / probe index when available
            ch = 2
            try:
                mask = int(getattr(pkt, "hit_mask", 0) or 0)
                if mask:
                    for bit in range(16):
                        if mask & (1 << bit):
                            ch = bit + 1
                            break
            except Exception:
                ch = 2
            ir_shield, ir_shield_tone = _t("fault_ir_shield_ch", ch=ch), "amber"
        else:
            ir_shield, ir_shield_tone = _t("fault_ir_shield_none"), "green"

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
            last_fault, last_tone = text.split("\n")[0].strip() if text else _t("fault_none_pending"), "amber"
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
            "irShield": ir_shield,
            "irTone": ir_shield_tone,
        }

    def _refresh_home_from_probes(self, client_data=None):
        """Master offline/invalid L2: probe CPS + suspend channel hard-alarm."""
        from core.translation import TranslationManager

        lang = TranslationManager().current_lang
        page = self.home_page
        link_only = bool(getattr(self, "master_client_id", None)) and not self.is_master_online()
        page.set_master_link_status(False, lang=lang, link_only=link_only)
        page.master_relay_label.setText("--")
        self._apply_home_probe_cps(client_data)
        self._update_home_alarm_from_master(None, lang=lang, master_offline=True)
        self._update_home_occupancy(None, lang=lang, master_offline=True)
        self._update_home_health_and_faults()

    def on_master_summary_ui(self, packet, client_id=None):
        """Refresh home alarm/channel from Master L2; CPS stays on probe spectrum."""
        from core.translation import _t, TranslationManager
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
            if last_pkt is not None and (now - last_at) <= 2.0:
                display_pkt = last_pkt

        online = display_pkt is not None and (
            packet is not None or self.is_master_online()
            or (now - float(getattr(self, "_last_any_master_at", 0) or 0)) <= 2.0
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
        )

        # 计数率始终跟探头
        self._apply_home_probe_cps(self.client_data)

        if display_pkt is None:
            page.master_relay_label.setText("--")
            self._update_home_alarm_from_master(None, lang=lang, master_offline=True)
            self._update_home_occupancy(None, lang=lang, master_offline=True)
            self._update_overview_occupancy_from_master(None, master_offline=True)
            self._update_settings_occupancy_from_master(None, master_offline=True)
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
                    display_pkt.decision_text("zh"),
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
            page.apply_status_label_style(label, color, bg, border)
            return
        label.setStyleSheet("""
            QLabel {
                color: %s; font-size: 16px; font-weight: bold;
                padding: 2px 8px; background-color: %s;
                border-radius: 8px; border: 1px solid %s;
            }
        """ % (color, bg, border))

    def _set_home_alarm_card_border(self, color=None):
        page = self.home_page
        if hasattr(page, "apply_alarm_banner_style"):
            page.apply_alarm_banner_style(color)
            return
        if color:
            page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #141519; border-radius: 8px;
                    border: 2px solid %s;
                }
            """ % color)
            page.status_indicator_bar.setStyleSheet(
                "QFrame { background-color: %s; border-radius: 1px; }" % color
            )
        else:
            page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #141519; border-radius: 8px;
                    border: 1px solid #252730;
                }
            """)
            page.status_indicator_bar.setStyleSheet(
                "QFrame { background-color: #10B981; border-radius: 1px; }"
            )

    def _update_home_alarm_from_master(self, packet, lang="zh", master_offline=False):
        """Home alarm follows master L2 decision.

        硬报 UI：0x02/0x03 进入；0x05/0x00/0x04 退出（不靠定时猜清除）。
        0x01 仅黄提示；0x05 显示已确认（mask 仍满时提示辐射仍偏高）。
        """
        from core.translation import _t
        from core.master_summary import format_io_brief, MASTER_DECISION_OVER_THRESHOLD
        import time as _time

        page = self.home_page
        current_time = datetime.now().strftime("%H:%M:%S")
        reset_btn = getattr(page, "channel_reset_btn", None)

        if master_offline or packet is None:
            self._over_thresh_probes_clear_since = None
            self._over_thresh_soft_cleared = False
            if reset_btn is not None:
                reset_btn.setEnabled(False)
            if hasattr(page, "set_channel_reset_alarm_active"):
                page.set_channel_reset_alarm_active(False)
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("master_offline"))
            self._set_home_status_style(
                page.alarm_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.alarm_desc_label.setText(_t("desc_master_offline"))
            self._set_home_alarm_card_border("#ff9800")
            self._apply_home_latch_status(page, hard_alarm=False, latch_mode=False, offline=True)
            if hasattr(page, "sync_side_rad_from_alarm"):
                page.sync_side_rad_from_alarm(_t("master_offline"), False)
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
        if kind == "channel_alarm" and getattr(packet, "ir_degraded", False):
            desc = "%s | %s" % (desc, _t("desc_ir_degraded"))

        soft_cleared = False
        # Soft-clear 0x01 when probe TCP alarm and master hit_mask are both clear.
        probes_clear = (not self._any_probe_tcp_alarm()) and (hit_mask == 0)
        if (
            kind == "over_threshold"
            and int(packet.decision_result) == MASTER_DECISION_OVER_THRESHOLD
            and probes_clear
        ):
            t0 = getattr(self, "_over_thresh_probes_clear_since", None)
            now = _time.time()
            if t0 is None:
                self._over_thresh_probes_clear_since = now
            elif (now - float(t0)) >= 2.0:
                soft_cleared = True
                if not getattr(self, "_over_thresh_soft_cleared", False):
                    self._over_thresh_soft_cleared = True
                    self.log(
                        "Soft-clear over-threshold UI: decision still 0x01, "
                        "probes clear and hit_mask=0",
                        "INFO",
                    )
                kind = "normal"
                desc = _t("desc_over_thresh_soft_clear")
        else:
            self._over_thresh_probes_clear_since = None
            self._over_thresh_soft_cleared = False

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
            if getattr(packet, "ir_degraded", False):
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
            self._pending_channel_reset_at = 0.0
        elif kind == "passing":
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
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_over_threshold"))
            self._set_home_status_style(
                page.alarm_status_label, "#ff9800",
                "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
            )
            page.alarm_desc_label.setText(desc)
            self._set_home_alarm_card_border("#ff9800")
            self._sync_channel_hard_alarm_log(False, packet)
        elif kind == "fault":
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
            page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            page.alarm_status_label.setText(_t("status_normal"))
            self._set_home_status_style(
                page.alarm_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            if soft_cleared:
                page.alarm_desc_label.setText(desc)
            else:
                page.alarm_desc_label.setText(format_io_brief(packet, lang=lang))
            self._set_home_alarm_card_border(None)
            self._sync_channel_hard_alarm_log(False, packet)

        if hasattr(page, "sync_side_rad_from_alarm") and kind != "channel_alarm":
            page.sync_side_rad_from_alarm(
                page.alarm_status_label.text(),
                kind in ("over_threshold", "fault"),
            )

    def _sync_channel_hard_alarm_log(self, active: bool, packet=None):
        """边沿写入通道符合硬报事件（alarm_logger client=master_channel）。"""
        prev = bool(getattr(self, "_channel_hard_alarm_active", False))
        if prev == bool(active):
            if active and packet is not None:
                # 持续硬报时刷新峰值 CPS
                try:
                    from core.alarm_logger import get_alarm_logger
                    get_alarm_logger().log_alarm_event(
                        client_id="master_channel",
                        alarm_status=True,
                        count_rate=float(getattr(packet, "total_cps", 0) or 0),
                        temperature=0.0,
                        hv=0.0,
                        product_id=int(getattr(packet, "master_id", 0) or 0),
                        sensitivity=0,
                        alarm_type="ChannelMatch",
                        message="hit_mask=0x%04X decision=0x%02X"
                        % (
                            int(getattr(packet, "hit_probe_mask", 0) or 0),
                            int(getattr(packet, "decision_result", 0) or 0),
                        ),
                    )
                except Exception:
                    pass
            self._refresh_alarm_log_nav_badge(radiation_alarm=bool(active))
            return
        self._channel_hard_alarm_active = bool(active)
        try:
            from core.alarm_logger import get_alarm_logger
            cps = float(getattr(packet, "total_cps", 0) or 0) if packet else 0.0
            mask = int(getattr(packet, "hit_probe_mask", 0) or 0) if packet else 0
            decision = int(getattr(packet, "decision_result", 0) or 0) if packet else 0
            get_alarm_logger().log_alarm_event(
                client_id="master_channel",
                alarm_status=bool(active),
                count_rate=cps,
                temperature=0.0,
                hv=0.0,
                product_id=int(getattr(packet, "master_id", 0) or 0) if packet else 0,
                sensitivity=0,
                alarm_type="ChannelMatch",
                message="hit_mask=0x%04X decision=0x%02X" % (mask, decision),
            )
            self.log(
                "Channel hard-alarm %s (decision=0x%02X hit_mask=0x%04X cps=%d)"
                % ("ACTIVE" if active else "CLEAR", decision, mask, int(cps)),
                "WARNING" if active else "INFO",
            )
        except Exception as e:
            self.log("Channel hard-alarm log failed: %s" % e, "ERROR")
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

        if not getattr(self, "is_tcp_mode", False):
            QMessageBox.warning(
                self, _t("msg_clear_mode_title"), _t("msg_clear_mode_need_master")
            )
            return False
        master_cid = getattr(self, "master_client_id", None)
        if not master_cid or not hasattr(self, "worker") or self.worker is None:
            QMessageBox.warning(
                self, _t("msg_clear_mode_title"), _t("msg_clear_mode_need_master")
            )
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
        master_cid = getattr(self, "master_client_id", None)
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
            QMessageBox.warning(
                self, _t("msg_clear_mode_title"), _t("msg_clear_mode_fail")
            )
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

    def request_channel_alarm_reset(self):
        """用户点「通道报警复位」→ 二次确认 → 主控 0x15。"""
        from core.translation import _t
        import time as _time

        master_cid = getattr(self, "master_client_id", None)
        if not master_cid or not getattr(self, "worker", None):
            QMessageBox.warning(
                self, _t("msg_channel_reset_title"), _t("msg_channel_reset_no_master")
            )
            return

        reply = QMessageBox.question(
            self,
            _t("msg_channel_reset_title"),
            _t("msg_channel_reset_text"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
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
            QMessageBox.warning(
                self, _t("msg_channel_reset_title"), _t("msg_channel_reset_fail")
            )
            return

        self._pending_channel_reset_at = _time.time()
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
        QMessageBox.warning(
            self, _t("msg_channel_reset_title"), _t("msg_channel_reset_timeout")
        )

    def on_channel_alarm_reset_feedback(self, packet):
        """主控 CmdFeedback control_code=0x15。"""
        from core.translation import _t

        pending = float(getattr(self, "_pending_channel_reset_at", 0) or 0)
        if pending <= 0 and not getattr(self, "_channel_reset_audit_snap", None):
            # 非本机发起也可记日志
            pass

        if not packet.status:
            self._pending_channel_reset_at = 0.0
            self.log(
                "Channel alarm reset rejected (status=0 value=0x%04X)"
                % (int(packet.value) & 0xFFFF),
                "WARNING",
            )
            btn = getattr(self.home_page, "channel_reset_btn", None)
            pkt = getattr(self, "latest_master_summary", None)
            if btn is not None and pkt is not None and pkt.is_channel_alarm():
                btn.setEnabled(True)
            QMessageBox.warning(
                self, _t("msg_channel_reset_title"), _t("msg_channel_reset_cmd_fail")
            )
            return

        # 成功：value 期望 0xA55A；硬报 UI 等下一拍 L2=0x05 再清
        val = int(packet.value) & 0xFFFF
        self._pending_channel_reset_at = 0.0
        self._awaiting_l2_acked = True
        self.log(
            "Channel alarm reset CmdFeedback OK value=0x%04X (expect 0xA55A)"
            % val,
            "INFO" if val == 0xA55A else "WARNING",
        )
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

    def _update_home_occupancy_probe(self, busy, lang="zh"):
        """Master offline: do not invent occupancy from probes."""
        from core.translation import _t
        page = self.home_page
        page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
        page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
        page.occupancy_status_label.setText(_t("master_offline"))
        self._set_home_status_style(
            page.occupancy_status_label, "#ff9800",
            "rgba(255, 152, 0, 0.12)", "rgba(255, 152, 0, 0.35)"
        )
        page.occupancy_desc_label.setText(_t("desc_master_offline"))
        page.occupancy_indicator_bar.setStyleSheet(
            "QFrame { background-color: #ff9800; border-radius: 1px; }"
        )

    def _update_home_occupancy(self, packet, lang="zh", master_offline=False):
        from core.translation import _t
        from core.master_summary import format_io_brief
        page = self.home_page
        if master_offline or packet is None:
            self._update_home_occupancy_probe(False, lang=lang)
            return

        busy = packet.is_channel_busy()
        if busy:
            page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_active'))
            page.occupancy_status_label.setText(_t("status_passing"))
            self._set_home_status_style(
                page.occupancy_status_label, "#2196f3",
                "rgba(33, 150, 243, 0.15)", "rgba(33, 150, 243, 0.4)"
            )
            page.occupancy_desc_label.setText(format_io_brief(packet, lang=lang))
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #2196f3; border-radius: 1px; }"
            )
        else:
            page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            page.occupancy_status_label.setText(_t("status_vacant"))
            self._set_home_status_style(
                page.occupancy_status_label, "#4caf50",
                "rgba(76, 175, 80, 0.1)", "rgba(76, 175, 80, 0.3)"
            )
            page.occupancy_desc_label.setText(format_io_brief(packet, lang=lang))
            page.occupancy_indicator_bar.setStyleSheet(
                "QFrame { background-color: #4caf50; border-radius: 1px; }"
            )

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
            active_count = sum(1 for v in get_alarm_logger().get_active_alarms().values() if v)
        except Exception:
            active_count = 0
        show = bool(radiation_alarm) or active_count > 0
        self.bottom_nav.set_alarm_log_badge(show)

    def update_alarm_status(self, is_alarm_active: bool):
        """Update alarm indicator on original overview page."""
        self.update_system_status(is_alarm_active)

    def update_system_status(self, is_alarm_active: Optional[bool] = None):
        """Update system status indicator on overview page, combining radiation alarms and device faults."""
        current_time = datetime.now().strftime("%H:%M:%S")
        master_pkt = getattr(self, "latest_master_summary", None)
        master_hard_alarm = bool(master_pkt is not None and self.is_master_online() and master_pkt.is_channel_alarm())

        # Original overview fallback: probe alarm bit only when no valid master hard-alarm source
        if is_alarm_active is None:
            is_alarm_active = master_hard_alarm
            if (not is_alarm_active) and self.primary_client_id and self.primary_client_id in self.client_latest_packets:
                latest_packet = self.client_latest_packets[self.primary_client_id]
                is_alarm_active = (latest_packet.device_status & 0b10000) != 0

        # Get all active faults from diagnostics manager
        active_faults = self.diagnostics_manager.get_all_active_faults()
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
        self._refresh_alarm_log_nav_badge(radiation_alarm=bool(is_alarm_active))

        if is_alarm_active:
            # 1. Radiation alarm active (Highest priority: Flashing Red)
            self.start_alarm_flashing()
            
            # Update title icon
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_active'))
            
            # Update status label with red active styling
            from core.translation import _t
            self.overview_page.alarm_status_label.setText(_t("status_alarm"))
            self.overview_page.alarm_status_label.setStyleSheet("""
                QLabel {
                    color: #ff4444;
                    font-size: 15px;
                    font-weight: bold;
                    margin-top: 2px;
                    padding: 2px 6px;
                    background-color: rgba(255, 68, 68, 0.15);
                    border-radius: 8px;
                    border: 1px solid rgba(255, 68, 68, 0.4);
                }
            """)
            
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
            self.overview_page.status_indicator_bar.setStyleSheet("""
                QFrame {
                    background-color: #ff4444;
                    border-radius: 1px;
                    margin-top: 5px;
                }
            """)
            
            # Update card border color (subtle red border)
            self.overview_page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: 2px solid #ff4444;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #ff6666;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)
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
                if hasattr(self, "format_fault_operator_message"):
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
            self.overview_page.alarm_status_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 15px;
                    font-weight: bold;
                    margin-top: 2px;
                    padding: 2px 6px;
                    background-color: rgba(255, 152, 0, 0.15);
                    border-radius: 8px;
                    border: 1px solid rgba(255, 152, 0, 0.4);
                }
            """)
            
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
            self.overview_page.status_indicator_bar.setStyleSheet("""
                QFrame {
                    background-color: #ff9800;
                    border-radius: 1px;
                    margin-top: 5px;
                }
            """)
            
            # Update card border color (subtle orange border)
            self.overview_page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: 2px solid #ff9800;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #ffb74d;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)
        else:
            # 3. System completely normal (Green)
            self.stop_alarm_flashing()
            
            # Update title icon and main indicator to inactive
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            
            # Update status label with green styling
            from core.translation import _t
            self.overview_page.alarm_status_label.setText(_t("status_normal"))
            self.overview_page.alarm_status_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 15px;
                    font-weight: bold;
                    margin-top: 2px;
                    padding: 2px 6px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 8px;
                    border: 1px solid rgba(76, 175, 80, 0.3);
                }
            """)
            
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
            self.overview_page.status_indicator_bar.setStyleSheet("""
                QFrame {
                    background-color: #4caf50;
                    border-radius: 1px;
                    margin-top: 5px;
                }
            """)
            
            # Reset card border color (no border like other cards)
            self.overview_page.alarm_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: none;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #444444;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)

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
            self.occupancy_status_label.setText(_t("master_offline"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ffe0b2; color: #000000;"
            )
            return
        busy = packet.is_channel_busy()
        if busy:
            self.occupancy_status_label.setText(_t("status_passing"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #bbdefb; color: #000000;"
            )
        else:
            self.occupancy_status_label.setText(_t("status_vacant"))
            self.occupancy_status_label.setStyleSheet(
                "background-color: #ccffcc; color: #000000;"
            )

    def _update_overview_occupancy_from_master(self, packet=None, master_offline=False):
        """概览页占用卡：跟主控 L2 is_channel_busy / format_io_brief。"""
        from core.translation import _t
        from core.master_summary import format_io_brief

        if not hasattr(self, "overview_page"):
            return

        if packet is None and not master_offline:
            if hasattr(self, "is_master_online") and self.is_master_online():
                packet = getattr(self, "latest_master_summary", None)

        if master_offline or packet is None:
            self.stop_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_status_label.setText(_t("master_offline"))
            self.overview_page.occupancy_status_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 18px;
                    font-weight: bold;
                    margin-top: 8px;
                    padding: 4px 12px;
                    background-color: rgba(255, 152, 0, 0.12);
                    border-radius: 10px;
                    border: 1px solid rgba(255, 152, 0, 0.35);
                }
            """)
            self.overview_page.occupancy_desc_label.setText(_t("desc_master_offline"))
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel { color: #888888; font-size: 12px; }
            """)
            self.overview_page.occupancy_indicator_bar.setStyleSheet("""
                QFrame { background-color: #ff9800; border: none; }
            """)
            self.overview_page.occupancy_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: none;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #444444;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)
            return

        busy = packet.is_channel_busy()
        try:
            from core.translation import TranslationManager
            brief = format_io_brief(packet, lang=TranslationManager().current_lang)
        except Exception:
            brief = format_io_brief(packet, lang="zh")

        if busy:
            self.start_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_active'))
            self.overview_page.occupancy_status_label.setText(_t("status_passing"))
            self.overview_page.occupancy_status_label.setStyleSheet("""
                QLabel {
                    color: #2196F3;
                    font-size: 18px;
                    font-weight: bold;
                    margin-top: 8px;
                    padding: 4px 12px;
                    background-color: rgba(33, 150, 243, 0.15);
                    border-radius: 10px;
                    border: 1px solid rgba(33, 150, 243, 0.4);
                }
            """)
            self.overview_page.occupancy_desc_label.setText(brief or _t("desc_traffic_detected"))
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #90caf9;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 2px;
                }
            """)
            self.overview_page.occupancy_indicator_bar.setStyleSheet("""
                QFrame {
                    background-color: #2196F3;
                    border-radius: 1px;
                    margin-top: 5px;
                }
            """)
            self.overview_page.occupancy_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: 2px solid #2196F3;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #64b5f6;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)
        else:
            self.stop_occupancy_flashing()
            self.overview_page.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
            self.overview_page.occupancy_status_label.setText(_t("status_vacant"))
            self.overview_page.occupancy_status_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 18px;
                    font-weight: bold;
                    margin-top: 8px;
                    padding: 4px 12px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 10px;
                    border: 1px solid rgba(76, 175, 80, 0.3);
                }
            """)
            self.overview_page.occupancy_desc_label.setText(brief or _t("desc_no_traffic"))
            self.overview_page.occupancy_desc_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 14px;
                    font-weight: normal;
                    margin-top: 2px;
                }
            """)
            self.overview_page.occupancy_indicator_bar.setStyleSheet("""
                QFrame {
                    background-color: #4caf50;
                    border-radius: 1px;
                    margin-top: 5px;
                }
            """)
            self.overview_page.occupancy_card.setStyleSheet("""
                QFrame {
                    background-color: #2a2a2a;
                    border-radius: 12px;
                    border: none;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2a2a2a, stop: 1 #1f1f1f);
                }
                QFrame:hover {
                    border: 2px solid #444444;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 #2f2f2f, stop: 1 #242424);
                }
            """)
    
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
        self.current_user = None
        try:
            self.user_manager.logout()
        except Exception:
            pass
        self.timeout_manager.stop_timer()
        self.status_bar.hide_timeout_display()
        self.status_bar.update_user_info(_t("status_public_mode"), None)
        # 主显示：隐藏整条 Qt 状态栏，改用 Web Header 单行（含时钟/电量/EN）
        self.status_bar.setVisible(False)
        self.setWindowTitle(_t("home_title"))
        self.stacked_widget.setCurrentIndex(0)
        self.bottom_nav.set_active_button(0)
        # 主显示保持整洁：隐藏登录条与底部 Tab
        self.button_container.setVisible(False)
        self.bottom_nav.setVisible(False)
        self.acquisition_btn.setVisible(False)
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
                border-radius: 12px; font-size: 14px; font-weight: bold; padding: 0 15px;
            }
            QPushButton:pressed { background-color: #45a049; }
        """)
        # 回到公共主显示时立刻刷一次现有探头/主控数据
        if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
            self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
        else:
            self._refresh_home_from_probes(self.client_data)
        if hasattr(self, "home_page") and hasattr(self.home_page, "schedule_web_flush"):
            self.home_page.schedule_web_flush()

    def update_ui_for_user_role(self):
        """根据用户角色更新UI"""
        from core.translation import _t
        if not self.is_logged_in():
            self.enter_public_mode()
            return
        
        role = self.current_user['role']
        self.button_container.setVisible(True)
        self.bottom_nav.setVisible(True)
        self.acquisition_btn.setVisible(True)
        self.save_data_btn.setVisible(True)
        self.logout_btn.setVisible(True)
        if hasattr(self, "status_bar"):
            on_home = self.stacked_widget.currentIndex() == 0
            self.status_bar.setVisible(not on_home)
            if not on_home and hasattr(self.status_bar, "set_clock_visible"):
                self.status_bar.set_clock_visible(True)
        
        # 更新用户管理按钮可见性
        # 注意：这里需要检查本地角色，而不是用户管理器中的角色
        if role == UserRole.VIEWER:
            # 如果是普通用户，检查VIEWER角色是否有用户管理权限
            from core.user_manager import Permission as Perm
            viewer_permissions = Perm.get_permissions_for_role(UserRole.VIEWER)
            can_manage_users = Permission.MANAGE_USERS in viewer_permissions
        else:
            # 管理员或其他角色，使用用户管理器的权限检查
            can_manage_users = self.user_manager.has_permission(Permission.MANAGE_USERS)
        self.user_management_btn.setVisible(can_manage_users)
        
        # 更新操作按钮状态（清除数据和保存数据）
        # 注意：这里需要检查本地角色，而不是用户管理器中的角色
        if role == UserRole.VIEWER:
            # 如果是普通用户，检查VIEWER角色是否有这些权限
            from core.user_manager import Permission as Perm
            viewer_permissions = Perm.get_permissions_for_role(UserRole.VIEWER)
            can_clear_data = Permission.CLEAR_DATA in viewer_permissions
            can_save_data = Permission.SAVE_DATA in viewer_permissions
        else:
            # 管理员或其他角色，使用用户管理器的权限检查
            can_clear_data = self.user_manager.has_permission(Permission.CLEAR_DATA)
            can_save_data = self.user_manager.has_permission(Permission.SAVE_DATA)
        
        # 禁用或启用清除数据按钮
        self.acquisition_btn.setEnabled(can_clear_data)
        
        # 禁用或启用保存数据按钮
        self.save_data_btn.setEnabled(can_save_data)
        
        # 更新logout/login按钮文本和功能
        from core.translation import _t
        if role == UserRole.VIEWER:
            # 普通用户模式：显示Login按钮
            self.logout_btn.setText(_t("btn_login"))
            self.logout_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 15px;
                    font-size: 16px;
                    font-weight: bold;
                    padding: 0 20px;
                }
                QPushButton:pressed {
                    background-color: #45a049;
                }
                QPushButton:disabled {
                    background-color: #666666;
                    color: #aaaaaa;
                }
            """)
            # 断开原来的logout连接，连接login功能
            try:
                self.logout_btn.clicked.disconnect()
            except:
                pass
            self.logout_btn.clicked.connect(self.login)
        else:
            # 管理员模式：显示Logout按钮
            self.logout_btn.setText(_t("btn_logout"))
            self.logout_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 15px;
                    font-size: 16px;
                    font-weight: bold;
                    padding: 0 20px;
                }
                QPushButton:pressed {
                    background-color: #d32f2f;
                }
                QPushButton:disabled {
                    background-color: #666666;
                    color: #aaaaaa;
                }
            """)
            # 断开原来的login连接，连接logout功能
            try:
                self.logout_btn.clicked.disconnect()
            except:
                pass
            self.logout_btn.clicked.connect(self.logout)
        
        # 更新状态栏用户信息
        if 'username' in self.current_user:
            self.status_bar.update_user_info(self.current_user['username'], role)
        
        # 如果是管理员，启动超时计时器
        if role == UserRole.ADMIN:
            self.timeout_manager.start_timer()
            self.log("管理员模式已启动，3分钟无操作将自动退出", 'INFO')
        else:
            self.timeout_manager.stop_timer()
            self.status_bar.hide_timeout_display()
        
        # 更新设置页面控件状态
        self.update_settings_controls_for_role(role)
    
    def update_settings_controls_for_role(self, role):
        """根据用户角色更新设置页面控件状态"""
        allow_viewer_settings = str(os.environ.get("ALLOW_VIEWER_SETTINGS", "0")).strip() == "1"
        # 检查用户是否有修改设置的权限
        can_modify_settings = self.user_manager.has_permission(Permission.MODIFY_COMM_SETTINGS) or \
                             self.user_manager.has_permission(Permission.MODIFY_DETECTOR_SETTINGS) or \
                             self.user_manager.has_permission(Permission.MODIFY_CONTROL_SETTINGS) or \
                             self.user_manager.has_permission(Permission.MODIFY_DEVICE_CONTROL) or \
                             self.user_manager.has_permission(Permission.MODIFY_LOG_SETTINGS)
        if allow_viewer_settings:
            can_modify_settings = True
        
        # 禁用或启用设置控件
        if hasattr(self, 'tcp_enable_checkbox'):
            self.tcp_enable_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'tcp_host_input'):
            self.tcp_host_input.setEnabled(can_modify_settings)
        
        if hasattr(self, 'tcp_port_spin'):
            self.tcp_port_spin.setEnabled(can_modify_settings)
        
        if hasattr(self, 'serial_port_combo'):
            self.serial_port_combo.setEnabled(can_modify_settings)
        
        if hasattr(self, 'baudrate_combo'):
            self.baudrate_combo.setEnabled(can_modify_settings)
        
        if hasattr(self, 'hv_spin'):
            self.hv_spin.setEnabled(can_modify_settings)
        
        if hasattr(self, 'threshold_spin'):
            self.threshold_spin.setEnabled(can_modify_settings)
        
        if hasattr(self, 'gain_stabilizer_btn'):
            self.gain_stabilizer_btn.setEnabled(can_modify_settings)
        
        if hasattr(self, 'sensitivity_spin'):
            self.sensitivity_spin.setEnabled(can_modify_settings)
        
        if hasattr(self, 'sensitivity_set_btn'):
            self.sensitivity_set_btn.setEnabled(can_modify_settings)
        
        if hasattr(self, 'sensitivity_read_btn'):
            self.sensitivity_read_btn.setEnabled(can_modify_settings)
        
        if hasattr(self, 'relay0_checkbox'):
            self.relay0_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'relay1_checkbox'):
            self.relay1_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'relay2_checkbox'):
            self.relay2_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'relay_read_btn'):
            self.relay_read_btn.setEnabled(can_modify_settings)

        if hasattr(self, 'master_relay0_checkbox'):
            self.master_relay0_checkbox.setEnabled(can_modify_settings)
        if hasattr(self, 'master_relay1_checkbox'):
            self.master_relay1_checkbox.setEnabled(can_modify_settings)
        if hasattr(self, 'master_relay2_checkbox'):
            self.master_relay2_checkbox.setEnabled(can_modify_settings)
        if getattr(self, 'master_relay_r1_btn', None) is not None:
            self.master_relay_r1_btn.setEnabled(can_modify_settings)
        if getattr(self, 'master_relay_r2_btn', None) is not None:
            self.master_relay_r2_btn.setEnabled(can_modify_settings)
        if getattr(self, 'master_relay_apply_btn', None) is not None:
            self.master_relay_apply_btn.setEnabled(can_modify_settings)
        if hasattr(self, 'master_relay_read_btn') and self.master_relay_read_btn is not None:
            self.master_relay_read_btn.setEnabled(can_modify_settings)
        if getattr(self, 'master_force_gate_btn', None) is not None:
            self.master_force_gate_btn.setEnabled(can_modify_settings)
        if getattr(self, 'alarm_clear_mode_combo', None) is not None:
            self.alarm_clear_mode_combo.setEnabled(can_modify_settings)
        if getattr(self, 'alarm_clear_mode_read_btn', None) is not None:
            self.alarm_clear_mode_read_btn.setEnabled(can_modify_settings)

        if hasattr(self, 'alarm_read_btn'):
            self.alarm_read_btn.setEnabled(can_modify_settings)

        if hasattr(self, 'expected_probe_spin'):
            self.expected_probe_spin.setEnabled(can_modify_settings)
        if hasattr(self, 'adopt_probe_count_btn'):
            self.adopt_probe_count_btn.setEnabled(can_modify_settings)
        if hasattr(self, 'probe_location_edits'):
            for edit in self.probe_location_edits:
                edit.setEnabled(can_modify_settings)
        
        if hasattr(self, 'telemetry_checkbox'):
            self.telemetry_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'log_path_input'):
            self.log_path_input.setEnabled(can_modify_settings and self.telemetry_checkbox.isChecked())
        
        if hasattr(self, 'select_path_btn'):
            self.select_path_btn.setEnabled(can_modify_settings and self.telemetry_checkbox.isChecked())
        
        # 自动保存控件权限控制
        if hasattr(self, 'auto_save_checkbox'):
            self.auto_save_checkbox.setEnabled(can_modify_settings)
        
        if hasattr(self, 'auto_save_interval_spin'):
            self.auto_save_interval_spin.setEnabled(can_modify_settings)
        
        if hasattr(self, 'auto_save_path_input'):
            self.auto_save_path_input.setEnabled(can_modify_settings and self.auto_save_enabled)
        
        if hasattr(self, 'auto_save_path_btn'):
            self.auto_save_path_btn.setEnabled(can_modify_settings and self.auto_save_enabled)
        
        # 更新按钮文本提示
        if not can_modify_settings:
            self.log("Current user is regular user, settings functions are disabled", 'INFO')
    
    def show_user_management(self):
        """显示用户管理对话框"""
        # 更新操作时间（重置超时计时器）
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
            QMessageBox.warning(
                self,
                _t("msg_login_required_title"),
                _t("msg_login_required_text"),
            )
            return False

        if str(os.environ.get("ALLOW_VIEWER_SETTINGS", "0")).strip() == "1":
            return True
        # 首先检查当前用户的本地角色
        if self.current_user and self.current_user['role'] == UserRole.VIEWER:
            # 如果是普通用户，检查是否有权限
            # 注意：这里使用用户管理器检查权限，但用户管理器中的角色可能是ADMIN
            # 所以我们需要额外检查本地角色
            if not self.user_manager.has_permission(permission_required):
                QMessageBox.warning(
                    self,
                    _t("msg_perm_title"),
                    _t("msg_perm_denied", action=action_text, perm=perm_str, user=user_name)
                )
                return False
            # 即使用户管理器说有权限，如果本地角色是VIEWER，也要检查VIEWER是否有这个权限
            # 获取VIEWER角色的权限列表
            from core.user_manager import Permission as Perm
            viewer_permissions = Perm.get_permissions_for_role(UserRole.VIEWER)
            if permission_required not in viewer_permissions:
                QMessageBox.warning(
                    self,
                    _t("msg_perm_title"),
                    _t("msg_perm_viewer", action=action_text, perm=perm_str)
                )
                return False
            return True
        else:
            # 管理员或其他角色，使用用户管理器的权限检查
            if not self.user_manager.has_permission(permission_required):
                QMessageBox.warning(
                    self,
                    _t("msg_perm_title"),
                    _t("msg_perm_denied_user", action=action_text, perm=perm_str, user=user_name)
                )
                return False
            return True
    
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
            reply = QMessageBox.question(
                self,
                _t("msg_relay0_off_title"),
                _t("msg_relay0_off_text"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
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
        reply = QMessageBox.question(
            self,
            _t("msg_force_gate_title"),
            _t("msg_force_gate_text"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
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
        
        reply = QMessageBox.question(
            self,
            _t("msg_logout_title"),
            _t("msg_logout_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
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
        
        # 只有在不是从logout()方法调用时才执行用户登出
        # 因为logout()方法已经处理了用户登出
        if not hasattr(self, '_logout_called') or not self._logout_called:
            # 用户登出
            self.user_manager.logout()
        
        # 调用父类方法
        super().closeEvent(event)
    
    def eventFilter(self, obj, event):
        """事件过滤器：超时计时 + 左上角隐藏入口长按（兼容树莓派触摸）。"""
        # 捕获鼠标点击和键盘输入事件
        if event.type() in [QEvent.MouseButtonPress, QEvent.KeyPress]:
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

    def update_operate_time(self):
        """更新操作时间（重置超时计时器）"""
        if self.current_user and self.current_user['role'] == UserRole.ADMIN:
            self.timeout_manager.update_operate_time()
    
    def on_admin_timeout(self):
        """Admin idle timeout -> return to public home monitor."""
        if self.current_user and self.current_user['role'] == UserRole.ADMIN:
            try:
                from core.software_keyboard import get_keyboard_manager
                get_keyboard_manager().hide_keyboard()
            except Exception:
                pass

            self.timeout_manager.last_operate_time = 0
            self.timeout_manager.save_state()
            self.enter_public_mode()
            self.log("Admin idle timeout -> public home monitor (silent)", 'INFO')
    
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
            QMessageBox.warning(
                self, _t("msg_login_failed_title"), _t("msg_login_failed_dialog")
            )
            return False

        actual_user = self.user_manager.get_current_user()
        if not actual_user:
            QMessageBox.warning(
                self, _t("msg_login_failed_title"), _t("msg_login_failed_user_manager")
            )
            return False

        current_user['role'] = actual_user.role
        self.current_user = current_user
        self.update_ui_for_user_role()

        role_name = "Admin" if current_user['role'] == UserRole.ADMIN else "User"
        username = current_user.get('username', '')
        self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")

        target = preferred_page if preferred_page is not None else 1
        self.stacked_widget.setCurrentIndex(target)
        self.bottom_nav.set_active_button(target)
        self.update_operate_time()
        if hasattr(self, "home_page") and hasattr(self.home_page, "schedule_web_flush"):
            self.home_page.schedule_web_flush()

        # 登录成功不弹框：界面切到管理页/顶栏模式变化即反馈
        self.log(f"Logged in: {username} ({actual_user.role.value})", 'INFO')
        return True
    
    def on_timeout_timer_updated(self, remaining_seconds: int):
        """超时计时器更新回调"""
        if self.current_user and self.current_user['role'] == UserRole.ADMIN:
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
        if not (self.current_user and self.current_user['role'] == UserRole.ADMIN):
            if not silent:
                QMessageBox.information(
                    self, "需要管理员权限",
                    "切换到 Ubuntu 桌面需要管理员权限，请先以管理员登录。"
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
            self.bottom_nav.setFixedHeight(70)
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
            role_name = "Admin" if self.current_user['role'] == UserRole.ADMIN else "User"
            self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
        else:
            self.setWindowTitle(_t("sys_title"))
            
        self.save_data_btn.setText(_t("btn_save"))
        self.user_management_btn.setText(_t("btn_user_mgmt"))
        # Viewer shows Login; Admin shows Logout
        if self.current_user and self.current_user.get('role') == UserRole.VIEWER:
            self.logout_btn.setText(_t("btn_login"))
        else:
            self.logout_btn.setText(_t("btn_logout"))
        
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
            # Find set buttons in det_group and retranslate
            for btn in self.det_group.findChildren(QPushButton):
                if btn.text() in ["Set HV", "设置高压"]:
                    btn.setText(_t("btn_set_hv"))
                elif btn.text() in ["Set Threshold", "设置阈值"]:
                    btn.setText(_t("btn_set_threshold"))
                    
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
            if hasattr(self, 'probe_locations_label'):
                self.probe_locations_label.setText(_t("set_probe_locations"))
                self.probe_locations_label.setToolTip(_t("tip_probe_locations"))
            # Stock labels follow language; custom overrides stay
            try:
                zh, en = self._stock_probe_slot_location_sets()
                locs = list(getattr(self.config, "probe_slot_locations", None) or [])
                if not locs or locs == zh or locs == en:
                    self.config.set_probe_slot_locations([])
            except Exception:
                pass
            if hasattr(self, 'refresh_probe_location_edits'):
                self.refresh_probe_location_edits()
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
            states = getattr(self, 'master_relay_states', None)
            if states is not None and len(states) >= 3:
                r0, r1, r2 = states[0], states[1], states[2]
                mask = (int(r0) & 1) | ((int(r1) & 1) << 1) | ((int(r2) & 1) << 2)
                self.master_relay_status_label.setText(
                    _t("master_relay_status_format", r0=int(r0), r1=int(r1), r2=int(r2), mask=mask)
                )
            else:
                self.master_relay_status_label.setText(_t("set_master_relay_status"))
            
        if hasattr(self, 'log_group'):
            self.log_group.setTitle(_t("set_raw_logging"))
            self.telemetry_checkbox.setText(_t("set_logging_enable"))
            self.log_path_input.setPlaceholderText(_t("set_logging_placeholder"))
            self.select_path_btn.setText(_t("btn_browse"))
            
        if hasattr(self, 'auto_save_group'):
            self.auto_save_group.setTitle(_t("set_auto_save"))
            self.auto_save_checkbox.setText(_t("set_auto_save_enable"))
            self.save_interval_title_label.setText(_t("set_save_interval"))
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
            
        # Call retranslate_ui on each page if they support it
        for page in [
            self.home_page, self.overview_page, self.spectrum_page,
            self.clients_page, self.alarm_log_page, self.settings_page,
        ]:
            if hasattr(page, 'retranslate_ui'):
                page.retranslate_ui()

        # Plot axis titles follow language
        if hasattr(self, 'retranslate_plot_labels'):
            self.retranslate_plot_labels()

        # Rebuild home HMI strings that were cached in Chinese/English
        try:
            if self.is_master_online() and getattr(self, "latest_master_summary", None) is not None:
                self.on_master_summary_ui(self.latest_master_summary, self.master_client_id)
            else:
                self._refresh_home_from_probes(self.client_data)
            if hasattr(self, "update_system_status"):
                self.update_system_status()
        except Exception:
            pass
                
        # Force a UI update
        self.update()
