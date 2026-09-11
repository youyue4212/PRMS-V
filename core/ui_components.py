# -*- coding: utf-8 -*-
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QFont

from core.utils import get_battery_percentage
from core.icons import get_icon_svg
from core.user_manager import UserRole

# 字体配置：优先微软雅黑，避免 Arial 导致中文/符号显示为 ?
FONTS = {
    "title": ("Microsoft YaHei", 20, "bold"),
    "subtitle": ("Microsoft YaHei", 18, "bold"),
    "mode": ("Microsoft YaHei", 16, "bold"),
    "data_key": ("Microsoft YaHei", 16),
    "data_value": ("Microsoft YaHei", 16, "bold"),
    "btn": ("Microsoft YaHei", 15),
    "tip": ("Microsoft YaHei", 14)
}

# 间距配置
PADDING = {
    "window": (20, 15),         # 窗口内边距
    "card": (25, 20),           # 卡片内边距
    "mode_frame": (15, 10),     # 模式区边距
    "operate_frame": (15, 10),  # 操作区边距
    "data_item": (12, 10),      # 数据项间距
    "btn": (8, 15)              # 按钮内边距
}


class StatusBar(QWidget):
    """Android-style status bar with battery, connection status, and user info"""
    language_changed = pyqtSignal(str)
    clear_requested = pyqtSignal()
    save_requested = pyqtSignal()
    users_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._hide_clock = False
        self._desktop_compact = False
        self.setFixedHeight(40)  # 工控触控：状态栏略加高
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: white;
            }
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 4, 12, 4)

        # Time label
        self.time_label = QLabel()
        # 应用字体配置
        time_font = QFont(FONTS["tip"][0], FONTS["tip"][1])
        if len(FONTS["tip"]) > 2 and "bold" in FONTS["tip"][2]:
            time_font.setBold(True)
        self.time_label.setFont(time_font)

        # User info label (initially hidden)
        self.user_label = QLabel()
        # 应用字体配置
        user_font = QFont(FONTS["tip"][0], FONTS["tip"][1])
        if len(FONTS["tip"]) > 2 and "bold" in FONTS["tip"][2]:
            user_font.setBold(True)
        self.user_label.setFont(user_font)
        
        self.user_label.setStyleSheet("""
            QLabel {
                margin-left: 10px;
                padding: 3px 8px;
                border-radius: 4px;
                background-color: #333333;
            }
        """)
        self.user_label.setVisible(False)

        # Admin timeout label (initially hidden)
        self.timeout_label = QLabel()
        # 应用字体配置
        timeout_font = QFont(FONTS["tip"][0], FONTS["tip"][1])
        if len(FONTS["tip"]) > 2 and "bold" in FONTS["tip"][2]:
            timeout_font.setBold(True)
        self.timeout_label.setFont(timeout_font)
        
        self.timeout_label.setStyleSheet("""
            QLabel {
                margin-left: 10px;
                padding: 3px 8px;
                border-radius: 4px;
                background-color: #ff9800;
                color: white;
                font-weight: bold;
            }
        """)
        self.timeout_label.setVisible(False)

        self.ops_clear = self._make_ops_btn("#ff9800")
        self.ops_save = self._make_ops_btn("#2196F3")
        self.ops_users = self._make_ops_btn("#9C27B0")
        self.ops_clear.clicked.connect(self.clear_requested.emit)
        self.ops_save.clicked.connect(self.save_requested.emit)
        self.ops_users.clicked.connect(self.users_requested.emit)
        self.ops_clear.setVisible(False)
        self.ops_save.setVisible(False)
        self.ops_users.setVisible(False)

        # Spacer
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        # Connection icon (default: disconnected)
        self.connection_icon_widget = QSvgWidget()
        self.connection_icon_widget.setFixedSize(22, 22)
        self.connection_icon_widget.load(get_icon_svg('disconnected'))

        # Battery label
        self.status_label = QLabel("100%")
        # 应用字体配置
        status_font = QFont(FONTS["tip"][0], FONTS["tip"][1])
        if len(FONTS["tip"]) > 2 and "bold" in FONTS["tip"][2]:
            status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("margin-left: 5px; margin-right: 15px;")

        # Language Switch Button — 必须覆盖全局 QPushButton(min-height:44/padding)
        # 否则在 40px 状态栏内文字（尤其 EN）会被裁切
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedHeight(32)
        self.lang_btn.setMinimumWidth(56)
        self.lang_btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.lang_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: #ff9800;
                border: 1px solid #ff9800;
                border-radius: 8px;
                padding: 0 10px;
                min-height: 32px;
                max-height: 32px;
                min-width: 56px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:pressed {
                background-color: #ff9800;
                color: black;
            }
        """)
        self.lang_btn.clicked.connect(self.toggle_language)
        
        # Set initial text based on current language
        from core.translation import TranslationManager
        current_lang = TranslationManager().get_language()
        self.lang_btn.setText("EN" if current_lang == "zh" else "中文")

        # Add widgets to layout
        layout.addWidget(self.time_label)
        layout.addWidget(self.user_label)
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.ops_clear)
        layout.addWidget(self.ops_save)
        layout.addWidget(self.ops_users)
        layout.addItem(spacer)
        layout.addWidget(self.connection_icon_widget)
        layout.addWidget(self.status_label)
        layout.addWidget(self.lang_btn)

        self.setLayout(layout)

        self._retranslate_ops_buttons()

        # Timer to update time and battery
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(10000)
        self.update_data()

    @staticmethod
    def _make_ops_btn(color: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedHeight(26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {color};
                border: 1px solid {color}; border-radius: 4px;
                padding: 0 8px; min-height: 26px; max-height: 26px;
                font-size: 11px; font-weight: bold;
            }}
            QPushButton:pressed {{ background-color: {color}; color: #111; }}
            QPushButton:disabled {{ color: #666; border-color: #555; }}
        """)
        return btn

    def set_ops_buttons(self, show_clear=False, show_save=False, show_users=False):
        """主控室：操作进设置页，状态栏不另占一排。"""
        self.ops_clear.setVisible(bool(show_clear))
        self.ops_save.setVisible(bool(show_save))
        self.ops_users.setVisible(bool(show_users))

    def set_desktop_compact(self, enabled: bool):
        """主控室电脑：状态栏用 px 字号，与顶栏胶囊同一套高度。"""
        from core.ui_tokens import CR_STATUS_BAR_H, CR_CHROME_H, CR_CHROME_FONT_PX
        self._desktop_compact = bool(enabled)
        if not self._desktop_compact:
            return
        self.setFixedHeight(CR_STATUS_BAR_H)
        px_font = QFont("Microsoft YaHei")
        px_font.setPixelSize(CR_CHROME_FONT_PX)
        for lab in (self.time_label, self.user_label, self.timeout_label, self.status_label):
            lab.setFont(px_font)
        self.time_label.setStyleSheet(
            f"color: white; font-size: {CR_CHROME_FONT_PX}px;"
        )
        self.status_label.setStyleSheet(
            f"color: white; font-size: {CR_CHROME_FONT_PX}px; "
            f"margin-left: 5px; margin-right: 10px;"
        )
        self.lang_btn.setFixedHeight(CR_CHROME_H)
        self.lang_btn.setMinimumWidth(52)
        self.lang_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #333333;
                color: #ff9800;
                border: 1px solid #ff9800;
                border-radius: 6px;
                padding: 0 10px;
                min-height: {CR_CHROME_H}px;
                max-height: {CR_CHROME_H}px;
                min-width: 52px;
                font-size: {CR_CHROME_FONT_PX}px;
                font-weight: bold;
            }}
            QPushButton:pressed {{
                background-color: #ff9800;
                color: black;
            }}
        """)

    def _retranslate_ops_buttons(self):
        from core.translation import _t
        if hasattr(self, "ops_clear"):
            self.ops_clear.setText(_t("btn_clear"))
            self.ops_save.setText(_t("btn_save"))
            self.ops_users.setText(_t("btn_user_mgmt"))

    def update_connection_status(self, is_connected: bool):
        """Update the connection icon dynamically"""
        tag = 'connected' if is_connected else 'disconnected'
        self.connection_icon_widget.load(get_icon_svg(tag))

    def update_user_info(self, username: str, role):
        """Update user information display"""
        from core.translation import _t
        if role is None:
            role_text = username or _t("status_public_mode")
            color = "#607d8b"
        elif role == UserRole.ADMIN:
            role_text = _t("role_admin")
            color = "#ff9800"  # Orange
        elif role == UserRole.MAINTAINER:
            role_text = _t("role_maintainer")
            color = "#8e24aa"
        else:
            role_text = _t("role_viewer")
            color = "#4caf50"  # Green
        
        # Only show role, not username to avoid duplication like "admin (Admin)"
        self.user_label.setText(role_text)
        font_px = ""
        if getattr(self, "_desktop_compact", False):
            from core.ui_tokens import CR_CHROME_FONT_PX
            font_px = f"font-size: {CR_CHROME_FONT_PX}px;"
        self.user_label.setStyleSheet(f"""
            QLabel {{
                margin-left: 10px;
                padding: 3px 8px;
                border-radius: 4px;
                background-color: {color};
                color: white;
                font-weight: bold;
                {font_px}
            }}
        """)
        self.user_label.setVisible(True)
        
        # If admin, show timeout label
        if role in (UserRole.ADMIN, UserRole.MAINTAINER):
            self.timeout_label.setText("03:00")
            self.timeout_label.setVisible(True)
        else:
            self.timeout_label.setVisible(False)

    def update_data(self):
        """Update battery level and current time"""
        battery_level, is_power_plugged = get_battery_percentage()
        if battery_level is None:
            label = ''
        else:
            label = f'{battery_level}%'
        self.status_label.setText(label)

        current_time = datetime.now().strftime("%H:%M")
        # 主显示 Web HMI 自带 HH:mm:ss 时钟，状态栏不再重复显示时间
        if getattr(self, "_hide_clock", False):
            self.time_label.setText("")
            self.time_label.setVisible(False)
        else:
            self.time_label.setVisible(True)
            self.time_label.setText(current_time)

    def set_clock_visible(self, visible: bool):
        self._hide_clock = not bool(visible)
        self.time_label.setVisible(bool(visible))
        if visible:
            self.update_data()
        else:
            self.time_label.setText("")

    def set_battery_visible(self, visible: bool):
        """PC control-room usually has no battery — hide the percent tag."""
        self.status_label.setVisible(bool(visible))
        if visible:
            self.update_data()

    def update_timeout_display(self, remaining_seconds: int):
        """Update timeout display"""
        if remaining_seconds <= 0:
            self.timeout_label.setVisible(False)
            return
        
        minutes = remaining_seconds // 60
        seconds = remaining_seconds % 60
        time_str = f"{minutes:02d}:{seconds:02d}"
        
        # Change color based on remaining time
        if remaining_seconds <= 30:
            color = "#ff4444"  # Red, last 30 seconds
        elif remaining_seconds <= 60:
            color = "#ff9800"  # Orange, last 1 minute
        else:
            color = "#4caf50"  # Green, sufficient time
        
        self.timeout_label.setText(time_str)
        font_px = ""
        if getattr(self, "_desktop_compact", False):
            from core.ui_tokens import CR_CHROME_FONT_PX
            font_px = f"font-size: {CR_CHROME_FONT_PX}px;"
        self.timeout_label.setStyleSheet(f"""
            QLabel {{
                margin-left: 8px;
                padding: 2px 8px;
                border-radius: 4px;
                background-color: {color};
                color: white;
                font-weight: bold;
                {font_px}
            }}
        """)
        self.timeout_label.setVisible(True)

    def toggle_language(self):
        """Toggle system language and emit signal"""
        from core.translation import TranslationManager
        tm = TranslationManager()
        new_lang = "en" if tm.get_language() == "zh" else "zh"
        tm.set_language(new_lang)
        self.lang_btn.setText("EN" if new_lang == "zh" else "中文")
        self.language_changed.emit(new_lang)
    
    def hide_timeout_display(self):
        """Hide timeout display"""
        self.timeout_label.setVisible(False)


class DataCard(QFrame):
    """Card widget for displaying radiation data"""
    def __init__(self, title, value, second_title, subvalue, subtitle, value_color="#ffffff", show_second_title=True, compact_mode=False, larger_font=False):
        super().__init__()
        
        # 设置固定高度，与ALARM STATUS框保持一致
        self.setFixedHeight(180)  # 统一高度为180px
        self.setObjectName("dataCard")
        # 只用 objectName 限定样式，避免 QFrame 选择器污染子控件（出现字下条框/分层）
        self.setStyleSheet("""
            QFrame#dataCard {
                background-color: #2a2a2a;
                border-radius: 10px;
                border: none;
            }
            QFrame#dataCard QLabel {
                background: transparent;
                border: none;
            }
        """)
        
        # 存储larger_font参数
        self.larger_font = larger_font
        
        layout = QVBoxLayout()
        
        # 设置内边距和间距，与ALARM STATUS框保持一致
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(4)
        
        # Title - 使用与ALARM STATUS框标题相似的样式
        self.title_label = QLabel(title)
        title_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1] - 2)  # 稍微小一点的字体
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self.title_label)
        
        # Main value - 根据larger_font参数调整字体大小
        self.value_label = QLabel(value)
        if larger_font:
            # 更大字体：34px
            value_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1] + 14)  # 更大的字体
            font_size = "34px"
            min_height = "48px"
        else:
            # 正常字体：28px
            value_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1] + 10)  # 较大的字体
            font_size = "28px"
            min_height = "42px"
        
        if len(FONTS["data_value"]) > 2 and "bold" in FONTS["data_value"][2]:
            value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-weight: bold;
                font-size: {font_size};
                margin: 5px 0;
                min-height: {min_height};
                background: transparent;
                border: none;
            }}
        """)
        self.value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.value_label)
        
        # second_title (optional) - 使用较小的字体
        self.second_title_label = QLabel(second_title)
        second_title_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1] - 2)
        self.second_title_label.setFont(second_title_font)
        self.second_title_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 13px;
                font-weight: normal;
                margin-top: 2px;
                background: transparent;
                border: none;
            }
        """)
        self.second_title_label.setVisible(show_second_title)
        self.second_title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.second_title_label)
        
        # Sub value - 使用中等字体
        self.sub_value_label = QLabel(subvalue)
        subvalue_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        self.sub_value_label.setFont(subvalue_font)
        self.sub_value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-weight: bold;
                font-size: 18px;
                margin-top: 4px;
                background: transparent;
                border: none;
            }}
        """)
        self.sub_value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.sub_value_label)
        
        # Subtitle - 使用较小的字体
        self.subtitle_label = QLabel(subtitle)
        subtitle_font = QFont(FONTS["tip"][0], FONTS["tip"][1] - 2)
        self.subtitle_label.setFont(subtitle_font)
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                font-weight: normal;
                margin-top: 2px;
                background: transparent;
                border: none;
            }
        """)
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.subtitle_label)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # 存储紧凑模式状态
        self.compact_mode = compact_mode
    
    def update_data(self, value, subvalue, value_color="#ffffff"):
        """Update card data"""
        self.value_label.setText(value)
        self.sub_value_label.setText(subvalue)
        
        # 更新样式，根据larger_font参数调整字体大小
        if self.larger_font:
            font_size = "28px"
            min_height = "45px"
        else:
            font_size = "24px"
            min_height = "40px"
        
        self.value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-weight: bold;
                font-size: {font_size};
                margin: 5px 0;
                min-height: {min_height};
                background: transparent;
                border: none;
            }}
        """)
        self.sub_value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-weight: bold;
                font-size: 16px;
                margin-top: 4px;
                background: transparent;
                border: none;
            }}
        """)
    
    def update_data_with_details(self, value, subvalue1, subvalue2, value_color="#ffffff"):
        """Update card data with two subvalues"""
        self.value_label.setText(value)
        # Combine subvalues with line break
        self.sub_value_label.setText(f"{subvalue1}\n{subvalue2}")
        self.value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-size: 18px;
                font-weight: bold;
                margin: 5px 0;
                background: transparent;
                border: none;
            }}
        """)
        self.sub_value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-size: 10px;
                font-weight: normal;
                margin-top: 8px;
                line-height: 1.2;
                background: transparent;
                border: none;
            }}
        """)


class BottomNavBar(QWidget):
    """Bottom navigation bar with page buttons"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._desktop_compact = False
        self._bar_height = 70
        self.setFixedHeight(self._bar_height)
        self.setMinimumHeight(self._bar_height)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 只对 BottomNavBar 本身设置样式，不影响子组件
        self.setStyleSheet("""
            BottomNavBar {
                background-color: #1f1f1f;
                border-top: 1px solid #333333;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.buttons = []
        self.button_widgets = []

        # 定义每个按钮的主题色
        button_colors = {
            "home": "#26c6da",          # 青色 - 主显示（免登录）
            "overview": "#4a9eff",      # 蓝色 - 原实时概览
            "spectrum": "#4caf50",      # 绿色
            "clients": "#ff9800",       # 橙色
            "alarm_log": "#ef9a9a",     # 浅红：日志入口，非「当前有报警」
            "settings": "#9c27b0"       # 紫色
        }
        
        from core.translation import _t
        home_widget = self.create_nav_button(_t("nav_home"), "home", button_colors["home"], True)
        self.button_widgets.append(home_widget)
        self.buttons.append(home_widget.findChild(QPushButton))

        overview_widget = self.create_nav_button(_t("nav_overview"), "overview", button_colors["overview"], False)
        self.button_widgets.append(overview_widget)
        self.buttons.append(overview_widget.findChild(QPushButton))
        
        spectrum_widget = self.create_nav_button(_t("nav_spectrum"), "spectrum", button_colors["spectrum"], False)
        self.button_widgets.append(spectrum_widget)
        self.buttons.append(spectrum_widget.findChild(QPushButton))
        
        clients_widget = self.create_nav_button(_t("nav_clients"), "clients", button_colors["clients"], False)
        self.button_widgets.append(clients_widget)
        self.buttons.append(clients_widget.findChild(QPushButton))
        
        alarm_log_widget = self.create_nav_button(_t("nav_alarm_log"), "alarm_log", button_colors["alarm_log"], False)
        self.button_widgets.append(alarm_log_widget)
        self.buttons.append(alarm_log_widget.findChild(QPushButton))
        
        settings_widget = self.create_nav_button(_t("nav_settings"), "settings", button_colors["settings"], False)
        self.button_widgets.append(settings_widget)
        self.buttons.append(settings_widget.findChild(QPushButton))
        
        layout.addWidget(home_widget)
        layout.addWidget(overview_widget)
        layout.addWidget(spectrum_widget)
        layout.addWidget(clients_widget)
        layout.addWidget(alarm_log_widget)
        layout.addWidget(settings_widget)
        
        self.setLayout(layout)

        self.home_btn = self.buttons[0]
        self.overview_btn = self.buttons[1]
        self.spectrum_btn = self.buttons[2]
        self.clients_btn = self.buttons[3]
        self.alarm_log_btn = self.buttons[4]
        self.settings_btn = self.buttons[5]
        self._active_index = 0
        self._alarm_log_badge = False

    def set_desktop_compact(self, enabled: bool):
        """主控室电脑：固定底栏高度，禁止被内容页挤扁；字号用 px 避免高 DPI 下 pt 撑破。"""
        self._desktop_compact = bool(enabled)
        self._bar_height = 64 if self._desktop_compact else 70
        self.setFixedHeight(self._bar_height)
        self.setMinimumHeight(self._bar_height)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        icon_size = 22 if self._desktop_compact else 28
        nav_font = 13
        if self._desktop_compact:
            from core.ui_tokens import CR_CHROME_FONT_PX
            nav_font = CR_CHROME_FONT_PX
        for container in self.button_widgets:
            container.setFixedHeight(self._bar_height)
            container.setMinimumHeight(self._bar_height)
            if hasattr(container, "icon_widget"):
                container.icon_widget.setFixedSize(icon_size, icon_size)
            if hasattr(container, "text_label"):
                container.text_label.setStyleSheet(
                    f"color: #cccccc; background: transparent; border: none; font-size: {nav_font}px;"
                )
            inner = getattr(container, "_inner_layout", None)
            if inner is not None and self._desktop_compact:
                inner.setContentsMargins(0, 4, 0, 4)
                inner.setSpacing(1)
        self.refresh_hit_areas()
        self.set_active_button(getattr(self, "_active_index", 0))

    def _alarm_log_icon_tag(self):
        return "alarm_log_alert" if self._alarm_log_badge else "alarm_log"

    def set_alarm_log_badge(self, active: bool):
        """有活动报警时显示铃铛红点；平时无角标。"""
        active = bool(active)
        if active == getattr(self, "_alarm_log_badge", False):
            return
        self._alarm_log_badge = active
        if len(self.button_widgets) < 5:
            return
        widget = self.button_widgets[4]
        widget.icon_tag = self._alarm_log_icon_tag()
        if self._active_index == 4:
            self._apply_active_style(widget, widget.icon_tag, widget.theme_color)
        else:
            self._apply_inactive_style(widget, widget.icon_tag)
    
    def create_nav_button(self, text, icon_tag, color, active=False):
        """Create a navigation button with SVG icon"""
        # Create a container widget for the button
        container = QWidget()
        container.setObjectName("nav_button_container")  # 设置对象名称以便精确样式定位
        bar_h = 70
        container.setFixedHeight(bar_h)
        
        # Create layout for icon and text
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)
        
        # Create SVG icon — 略放大，暗底更易辨认
        icon_widget = QSvgWidget()
        icon_widget.setFixedSize(28, 28)
        icon_widget.load(get_icon_svg(icon_tag))
        
        # Center the icon
        icon_layout = QHBoxLayout()
        icon_layout.addStretch()
        icon_layout.addWidget(icon_widget)
        icon_layout.addStretch()
        
        # Create text label
        text_label = QLabel(text)
        text_label.setAlignment(Qt.AlignCenter)
        text_font = QFont(FONTS["tip"][0], 11)
        text_label.setFont(text_font)
        
        layout.addLayout(icon_layout)
        layout.addWidget(text_label)
        container._inner_layout = layout
        
        # Create invisible button for click handling
        btn = QPushButton()
        btn.setFixedHeight(bar_h)
        
        # Add everything to container
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addLayout(layout)
        container.setLayout(container_layout)
        
        # Position button on top of the content
        btn.setParent(container)
        btn.setGeometry(0, 0, max(container.width(), 1), bar_h)
        btn.raise_()
        container._hit_btn = btn
        
        # Store references for later updates
        container.icon_widget = icon_widget
        container.text_label = text_label
        container.icon_tag = icon_tag
        container.theme_color = color
        
        if active:
            self._apply_active_style(container, icon_tag, color)
        else:
            self._apply_inactive_style(container, icon_tag)
        
        return container

    def resizeEvent(self, event):
        """窗口尺寸变化后同步透明点击层宽度（从最小化恢复全屏时尤其需要）。"""
        super().resizeEvent(event)
        self.refresh_hit_areas()

    def refresh_hit_areas(self):
        """按当前宽度重设底部导航按钮点击区域。"""
        h = getattr(self, "_bar_height", 70)
        self.setFixedHeight(h)
        self.setMinimumHeight(h)
        for container in self.button_widgets:
            container.setFixedHeight(h)
            container.setMinimumHeight(h)
            btn = getattr(container, '_hit_btn', None)
            if btn is not None:
                btn.setFixedHeight(h)
                btn.setGeometry(0, 0, max(container.width(), 1), h)
                btn.raise_()
    
    def _nav_font_px(self):
        if getattr(self, "_desktop_compact", False):
            from core.ui_tokens import CR_CHROME_FONT_PX
            return CR_CHROME_FONT_PX
        return 11

    def _apply_active_style(self, container, icon_tag, color):
        """Apply active style to button with custom color"""
        # 将 hex 颜色转换为 rgba
        hex_color = color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        container.setStyleSheet(f"""
            #nav_button_container {{
                background-color: rgba({r}, {g}, {b}, 0.1);
                border: none;
                border-top: 3px solid {color};
            }}
        """)
        # 添加发光效果的文字样式
        container.text_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-weight: bold;
                background-color: transparent;
                border: none;
                font-size: {self._nav_font_px()}px;
            }}
        """)
        # 为图标添加发光效果 - 在 SVG 中添加发光滤镜
        svg_template = '''
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <g>
                {content}
            </g>
        </svg>
        '''

        # 获取原始 SVG 并提取内容
        original_svg = get_icon_svg(icon_tag).decode()
        # 提取 <svg> 标签内的内容
        import re
        content_match = re.search(r'<svg[^>]*>(.*)</svg>', original_svg, re.DOTALL)
        if content_match:
            content = content_match.group(1)
            # 替换 currentColor 为发光颜色
            content = content.replace('currentColor', color)
            # 生成带主题色的 SVG（去掉易糊的 glow 滤镜）
            glowing_svg = svg_template.format(content=content)
            container.icon_widget.load(glowing_svg.encode())
        else:
            # 如果提取失败，使用原来的方法
            svg_data = original_svg.replace('currentColor', color)
            container.icon_widget.load(svg_data.encode())

        btn = container.findChild(QPushButton)
        btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)

    
    def _apply_inactive_style(self, container, icon_tag):
        """Apply inactive style to button"""
        # 未选中：容器与文字均透明，只保留灰色字/图标，避免标签下实色底块
        container.setStyleSheet("""
            #nav_button_container {
                background-color: transparent;
                border: none;
                border-top: 3px solid transparent;
            }
        """)
        container.text_label.setStyleSheet(f"""
            QLabel {{
                color: #cccccc;
                background-color: transparent;
                border: none;
                font-size: {self._nav_font_px()}px;
            }}
        """)
        # Update icon with inactive color — 提高对比，避免暗底看不清
        svg_data = get_icon_svg(icon_tag).decode().replace('currentColor', '#cccccc')
        container.icon_widget.load(svg_data.encode())

        btn = container.findChild(QPushButton)
        btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.06);
            }
        """)
    
    def set_active_button(self, index):
        """Set the active button"""
        self._active_index = index
        for i, widget in enumerate(self.button_widgets):
            # 报警日志图标跟活动报警角标同步
            if i == 4:
                widget.icon_tag = self._alarm_log_icon_tag()
            if i == index:
                self._apply_active_style(widget, widget.icon_tag, widget.theme_color)
            else:
                self._apply_inactive_style(widget, widget.icon_tag)

    def retranslate_ui(self):
        """Retranslate bottom navigation bar buttons"""
        from core.translation import _t
        nav_keys = [
            "nav_home", "nav_overview", "nav_spectrum",
            "nav_clients", "nav_alarm_log", "nav_settings",
        ]
        for i, widget in enumerate(self.button_widgets):
            if i < len(nav_keys):
                new_text = _t(nav_keys[i])
                widget.text_label.setText(new_text)
                if i == 4:
                    widget.icon_tag = self._alarm_log_icon_tag()
                if getattr(self, "_active_index", -1) == i:
                    self._apply_active_style(widget, widget.icon_tag, widget.theme_color)
                else:
                    self._apply_inactive_style(widget, widget.icon_tag)


class AcquisitionButton(QPushButton):
    """Clear current accumulation button."""
    def __init__(self):
        from core.translation import _t
        super().__init__(_t("btn_clear"))
        self.setFixedHeight(44)
        self.update_style()
    
    def retranslate_ui(self):
        from core.translation import _t
        self.setText(_t("btn_clear"))
    
    def update_style(self):
        self.setStyleSheet("""
            QPushButton {
                background-color: #2b2418;
                color: #ffb74d;
                border: 1px solid #ff9800;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 0 16px;
            }
            QPushButton:pressed {
                background-color: #ff9800;
                color: #111111;
            }
            QPushButton:disabled {
                background-color: #252525;
                color: #787878;
                border: 1px solid #555555;
            }
        """)












