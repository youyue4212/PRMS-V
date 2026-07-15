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
from core.pages import OverviewPage, SpectrumPage, SettingsPage, ClientsPage

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
        if current_user and 'username' in current_user:
            username = current_user['username']
            role_name = "Admin" if current_user['role'] == UserRole.ADMIN else "User"
            self.setWindowTitle(f"Gamma-ray Spectrometer - {username} ({role_name})")
        else:
            self.setWindowTitle("Gamma-ray Spectrometer")
        
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
        main_layout.addWidget(self.status_bar)
        
        # Stacked widget for pages
        self.stacked_widget = QStackedWidget()
        

        self.overview_page = OverviewPage(self)
        
        # Spectrum page (现在在第二位)
        self.spectrum_page = SpectrumPage(self)

        # Clients page (现在在第三位)
        self.clients_page = ClientsPage(self)
        
        # Alarm log page (第四位)
        self.alarm_log_page = AlarmLogPage(self)

        self.settings_page=SettingsPage(self)
        
        self.stacked_widget.addWidget(self.overview_page)
        self.stacked_widget.addWidget(self.spectrum_page)
        self.stacked_widget.addWidget(self.clients_page)
        self.stacked_widget.addWidget(self.alarm_log_page)
        self.stacked_widget.addWidget(self.settings_page)
        
        main_layout.addWidget(self.stacked_widget, 1)
        
        # Acquisition button container - 优化为小屏幕
        button_container = QWidget()
        button_container.setStyleSheet("background-color: #1a1a1a;")
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(20, 5, 20, 5)  # 大幅减少边距，适应小屏幕
        
        # 使用更小的按钮高度
        button_height = 35  # 从40减少到35
        
        self.acquisition_btn = AcquisitionButton()
        self.acquisition_btn.clicked.connect(self.clear_data)
        button_layout.addWidget(self.acquisition_btn)
        
        # Add save data button
        self.save_data_btn = QPushButton("Save Data")
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
        self.user_management_btn = QPushButton("User Mgmt")
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

        # Add logout button
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.setFixedHeight(button_height)
        self.logout_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 15px;
                min-height: {button_height}px;
            }}
            QPushButton:pressed {{
                background-color: #d32f2f;
            }}
            QPushButton:disabled {{
                background-color: #666666;
                color: #aaaaaa;
            }}
        """)
        self.logout_btn.clicked.connect(self.logout)
        button_layout.addWidget(self.logout_btn)
        
        button_container.setLayout(button_layout)
        main_layout.addWidget(button_container)
        
        # Bottom navigation
        self.bottom_nav = BottomNavBar()
        self.bottom_nav.overview_btn.clicked.connect(lambda: self.switch_page(0))
        self.bottom_nav.spectrum_btn.clicked.connect(lambda: self.switch_page(1))  # 能谱页面现在在第二位
        self.bottom_nav.clients_btn.clicked.connect(lambda: self.switch_page(2))   # 客户端页面现在在第三位
        self.bottom_nav.alarm_log_btn.clicked.connect(lambda: self.switch_page(3))  # 报警记录页面在第四位
        self.bottom_nav.settings_btn.clicked.connect(lambda: self.switch_page(4))   # 设置页面现在在第五位
        main_layout.addWidget(self.bottom_nav)
        
        central_widget.setLayout(main_layout)
        
        # 注意：UIBase.__init__()已经调用了setup_ui()，所以这里不需要再次调用
        # 但是我们需要确保回调函数正确设置
        # 在UIBase中设置回调函数
        self.data_updated_callback = self.data_updated
        self.alarm_status_callback = self.update_alarm_status

        # 连接超时管理器信号
        self.timeout_manager.timeout_occurred.connect(self.on_admin_timeout)
        self.timeout_manager.timer_updated.connect(self.on_timeout_timer_updated)
        
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
        
        # 根据用户权限更新UI
        self.update_ui_for_user_role()
        
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
        
    
    def switch_page(self, index):
        """Switch between pages"""
        self.stacked_widget.setCurrentIndex(index)
        self.bottom_nav.set_active_button(index)
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
    
    def clear_data(self):
        """Clear all data (spectrum, time series, etc.)"""
        # 检查权限
        if not self.check_permission_before_action("Clear data", Permission.CLEAR_DATA):
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        if self.is_acquiring:
            # 如果正在采集，询问用户是否要先停止采集
            reply = QMessageBox.question(self, "Acquisition Running", 
                                        "Data acquisition is currently running. Would you like to:\n\n"
                                        "1. Stop acquisition and clear data\n"
                                        "2. Cancel clearing data\n\n"
                                        "Click 'Yes' to stop and clear, 'No' to cancel.",
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
        reply = QMessageBox.question(self, "Clear Data", 
                                    "Are you sure you want to clear all data? This will reset spectrum, time series, and client data.",
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
            
            # 更新卡片显示
            self.overview_page.radiation_card.update_data("0.00 uSv/h", "0 cps")
            self.overview_page.status_card.update_data("0°C", "0 V")
            
            self.log("All data cleared", 'INFO')
    
    def save_data(self, auto_save=False, auto_save_path=""):
        """Save current data to file"""
        # 如果是自动保存，跳过权限检查（自动保存对所有用户级别都生效）
        if not auto_save:
            # 手动保存需要检查权限
            if not self.check_permission_before_action("Save data", Permission.SAVE_DATA):
                return
            
            # 更新操作时间（重置超时计时器）
            self.update_operate_time()
        
        # 调用父类方法，传递参数
        super().save_data(auto_save=auto_save, auto_save_path=auto_save_path)
    
    def data_updated(self, data, total_count_rate=None, client_data=None):
         hv,rates,temp =data['hv'], data['rates'],data['temp']
         
         # 更新辐射卡：只显示计数率(cps)，不显示剂量率
         self.overview_page.radiation_card.update_data(
             f'{int(rates)} cps',  # 主值：计数率 (cps)
             ""  # 空字符串，不显示剂量率
         )
         
         # 更新状态卡：大字体显示温度，小字体显示高压
         self.overview_page.status_card.update_data(f'{round(temp,1)} ' + chr(176) + 'C', f'{round(hv,1)} V')
         
         # 不再处理总计数率和客户端数据显示
         # 根据用户要求，移除Total Count Rate和Client count数据显示
    
    def update_alarm_status(self, is_alarm_active: bool):
        """Update alarm indicator on overview page - Restored to previous display form"""
        current_time = datetime.now().strftime("%H:%M:%S")
        
        if is_alarm_active:
            # Start flashing alarm
            self.start_alarm_flashing()
            
            # Update title icon
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_active'))
            
            # Update status label with restored styling
            self.overview_page.alarm_status_label.setText("ALARM ACTIVE")
            self.overview_page.alarm_status_label.setStyleSheet("""
                QLabel {
                    color: #ff4444;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 8px;
                    padding: 4px 12px;
                    background-color: rgba(255, 68, 68, 0.15);
                    border-radius: 10px;
                    border: 1px solid rgba(255, 68, 68, 0.4);
                }
            """)
            
            # Update description with timestamp
            self.overview_page.alarm_desc_label.setText(f"Alarm detected at {current_time}")
            self.overview_page.alarm_desc_label.setStyleSheet("""
                QLabel {
                    color: #ff8888;
                    font-size: 10px;
                    font-weight: normal;
                    margin-top: 2px;
                    font-style: italic;
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
        else:
            # Stop flashing and show normal inactive state
            self.stop_alarm_flashing()
            
            # Update title icon
            self.overview_page.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
            
            # Load inactive icon
            self.overview_page.alarm_indicator.load(get_icon_svg('alarm_inactive'))
            
            # Update status label with restored styling
            self.overview_page.alarm_status_label.setText("SYSTEM NORMAL")
            self.overview_page.alarm_status_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 8px;
                    padding: 4px 12px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 10px;
                    border: 1px solid rgba(76, 175, 80, 0.3);
                }
            """)
            
            # Update description with timestamp
            self.overview_page.alarm_desc_label.setText(f"Last checked: {current_time}")
            self.overview_page.alarm_desc_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 10px;
                    font-weight: normal;
                    margin-top: 2px;
                    font-style: italic;
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
    
    def update_ui_for_user_role(self):
        """根据用户角色更新UI"""
        if not self.current_user:
            return
        
        role = self.current_user['role']
        
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
        if role == UserRole.VIEWER:
            # 普通用户模式：显示Login按钮
            self.logout_btn.setText("Login")
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
            self.logout_btn.setText("Logout")
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
        
        if hasattr(self, 'alarm_read_btn'):
            self.alarm_read_btn.setEnabled(can_modify_settings)
        
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
        """在执行操作前检查权限"""
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
                    "Insufficient Permission",
                    f"You don't have permission to perform '{action_name}' operation.\n\n"
                    f"Required permission: {permission_required}\n"
                    f"Current user: {self.current_user['username'] if self.current_user else 'Unknown user'} (Viewer mode)"
                )
                return False
            # 即使用户管理器说有权限，如果本地角色是VIEWER，也要检查VIEWER是否有这个权限
            # 获取VIEWER角色的权限列表
            from core.user_manager import Permission as Perm
            viewer_permissions = Perm.get_permissions_for_role(UserRole.VIEWER)
            if permission_required not in viewer_permissions:
                QMessageBox.warning(
                    self, 
                    "Insufficient Permission",
                    f"You are in viewer mode and don't have permission to perform '{action_name}' operation.\n\n"
                    f"Required permission: {permission_required}\n"
                    f"Current mode: Viewer (temporary mode)"
                )
                return False
            return True
        else:
            # 管理员或其他角色，使用用户管理器的权限检查
            if not self.user_manager.has_permission(permission_required):
                QMessageBox.warning(
                    self, 
                    "Insufficient Permission",
                    f"You don't have permission to perform '{action_name}' operation.\n\n"
                    f"Required permission: {permission_required}\n"
                    f"Current user: {self.current_user['username'] if self.current_user else 'Unknown user'}"
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
    
    def control_single_relay(self, relay_num, state):
        """控制单个继电器 - 添加权限检查"""
        if not self.check_permission_before_action("Control relay", Permission.MODIFY_DEVICE_CONTROL):
            return
        
        # 调用父类方法
        super().control_single_relay(relay_num, state)
    
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
        if not self.check_permission_before_action("Modify log settings", Permission.MODIFY_LOG_SETTINGS):
            # 恢复原始状态
            self.telemetry_checkbox.blockSignals(True)
            self.telemetry_checkbox.setChecked(not state)
            self.telemetry_checkbox.blockSignals(False)
            return
        
        # 调用父类方法
        super().toggle_raw_packet_logging(state)
    
    def select_log_path(self):
        """选择日志路径 - 添加权限检查"""
        if not self.check_permission_before_action("Modify log settings", Permission.MODIFY_LOG_SETTINGS):
            return
        
        # 调用父类方法
        super().select_log_path()
    
    def toggle_auto_save(self, state):
        """切换自动保存开关 - 添加权限检查"""
        if not self.check_permission_before_action("Modify auto-save settings", Permission.SAVE_DATA):
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
        if not self.check_permission_before_action("Modify auto-save settings", Permission.SAVE_DATA):
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
        if not self.check_permission_before_action("Modify auto-save settings", Permission.SAVE_DATA):
            return
        
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        # 调用父类方法
        super().select_auto_save_path()
    
    def logout(self):
        """退出到普通用户模式（viewer模式）"""
        # 注意：在logout过程中不更新操作时间，避免重新启动计时器
        # self.update_operate_time()  # 注释掉这一行
        
        reply = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to logout from admin mode?\n\n"
            "You will be switched to normal user (viewer) mode.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 首先停止超时计时器
            self.timeout_manager.stop_timer()
            
            # 重要：重置超时管理器状态
            self.timeout_manager.last_operate_time = 0
            self.timeout_manager.save_state()
            
            # 切换到普通用户模式（本地）
            # 注意：不修改用户管理器中的实际用户角色，保持为ADMIN
            if self.current_user and self.current_user['role'] == UserRole.ADMIN:
                # 记录切换前的角色
                old_role = self.current_user['role']
                self.current_user['role'] = UserRole.VIEWER
                
                # 更新UI为普通用户
                self.update_ui_for_user_role()
                
                # 更新窗口标题
                if 'username' in self.current_user:
                    username = self.current_user['username']
                    self.setWindowTitle(f"Gamma-ray Spectrometer - {username} (User)")
                
                # 显示通知
                QMessageBox.information(
                    self,
                    "Switched to User Mode",
                    "Successfully switched to normal user (viewer) mode.\n\n"
                    "To perform settings operations, please log in as admin again."
                )
                
                # 记录日志
                self.log(f"Manually switched from {old_role.value} mode to normal user mode", 'INFO')
                
                # 确保超时计时器已停止（再次确认）
                self.timeout_manager.stop_timer()
                self.status_bar.hide_timeout_display()
            else:
                # 如果当前用户不是管理员，显示信息
                QMessageBox.information(
                    self,
                    "Already in User Mode",
                    "You are already in normal user (viewer) mode."
                )
    
    def _delayed_relogin(self):
        """延迟重新登录，确保旧的窗口完全关闭"""
        # 重新显示登录对话框
        from core.login_dialog import LoginDialog
        from PyQt5.QtWidgets import QApplication
        
        app = QApplication.instance()
        login_dialog = LoginDialog()
        if login_dialog.exec_() == LoginDialog.Accepted:
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
        """Admin mode timeout callback - temporarily switch to normal user mode"""
        if self.current_user and self.current_user['role'] == UserRole.ADMIN:
            # IMPORTANT: We should NOT permanently modify the user role in user manager
            # Instead, we just update the local current_user dictionary for UI purposes
            # The actual user role in user manager remains ADMIN
            
            # Switch current user to normal mode (local only)
            self.current_user['role'] = UserRole.VIEWER

            # 先关掉可能打开的软件键盘：它是置顶非模态窗口，若不关，
            # 下面的模态提示框会被它挡住导致界面卡死、点不到“确定”。
            try:
                from core.software_keyboard import get_keyboard_manager
                get_keyboard_manager().hide_keyboard()
            except Exception:
                pass

            # DO NOT update the user in user manager - keep it as ADMIN
            # This ensures that when user logs out and logs back in, they're still admin

            # Update UI for normal user
            self.update_ui_for_user_role()
            
            # Show timeout notification (non-blocking)
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, lambda: QMessageBox.information(
                self,
                "Admin Mode Timeout",
                "Admin mode inactive timeout (3 minutes), temporarily switched to normal view mode.\n\n"
                "To perform settings operations, please log in as admin again."
            ))
            
            # Log the event
            self.log("Admin mode inactive timeout, temporarily switched to normal view mode", 'INFO')
            
            # Clear timeout state
            self.timeout_manager.last_operate_time = 0
            self.timeout_manager.save_state()
            
            # Update window title
            if 'username' in self.current_user:
                username = self.current_user['username']
                self.setWindowTitle(f"Gamma-ray Spectrometer - {username} (User - Temp)")
    
    def login(self):
        """从普通用户模式登录到管理员模式"""
        # 更新操作时间（重置超时计时器）
        self.update_operate_time()
        
        from core.login_dialog import LoginDialog
        
        # 显示登录对话框
        login_dialog = LoginDialog()
        if login_dialog.exec_() == LoginDialog.Accepted:
            # 获取登录用户信息
            current_user = login_dialog.get_current_user_info()
            
            if current_user:
                # 重要：确保用户角色正确（从用户管理器获取真实角色）
                user_manager = self.user_manager
                actual_user = user_manager.get_current_user()
                if actual_user:
                    # 使用用户管理器中的真实角色
                    current_user['role'] = actual_user.role
                    
                    # 更新当前用户信息
                    self.current_user = current_user
                    
                    # 更新UI为管理员模式
                    self.update_ui_for_user_role()
                    
                    # 更新窗口标题
                    if 'username' in self.current_user:
                        username = self.current_user['username']
                        self.setWindowTitle(f"Gamma-ray Spectrometer - {username} (Admin)")
                    
                    # 显示通知
                    QMessageBox.information(
                        self,
                        "Switched to Admin Mode",
                        "Successfully logged in as administrator.\n\n"
                        "You now have full control permissions.\n"
                        "Note: Admin mode will auto logout after 3 minutes of inactivity."
                    )
                    
                    # 记录日志
                    self.log(f"Logged in as administrator: {current_user['username']}", 'INFO')
                else:
                    QMessageBox.warning(
                        self,
                        "Login Failed",
                        "Failed to get user information from user manager."
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Login Failed",
                    "Failed to get user information from login dialog."
                )
    
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
