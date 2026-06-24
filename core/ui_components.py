import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QFont

from core.utils import get_battery_percentage
from core.icons import get_icon_svg
from core.user_manager import UserRole

# 字体配置（参考文档：伽玛数据采集看板）- 使用Arial字体
# 根据用户要求进一步调整字体大小，使UI更清晰易读
FONTS = {
    "title": ("Arial", 20, "bold"),        # 主标题 - 从18增加到20
    "subtitle": ("Arial", 18, "bold"),     # 子标题（卡片标题）- 从16增加到18
    "mode": ("Arial", 16, "bold"),         # 模式标识 - 从14增加到16
    "data_key": ("Arial", 16),             # 数据项键名 - 从14增加到16
    "data_value": ("Arial", 16, "bold"),   # 数据项值 - 从14增加到16
    "btn": ("Arial", 15),                  # 按钮字体 - 从13增加到15
    "tip": ("Arial", 14)                   # 提示文本 - 从12增加到14
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
    def __init__(self):
        super().__init__()
        self.setFixedHeight(32)  # 稍微增加高度以容纳更好的字体显示
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: white;
            }
        """)

        layout = QHBoxLayout()
        layout.setContentsMargins(20, 6, 20, 6)  # 使用参考文档的窗口内边距

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

        # Spacer
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        # Connection icon (default: disconnected)
        self.connection_icon_widget = QSvgWidget()
        self.connection_icon_widget.setFixedSize(18, 18)
        self.connection_icon_widget.load(get_icon_svg('disconnected'))

        # Battery label
        self.status_label = QLabel("100%")
        # 应用字体配置
        status_font = QFont(FONTS["tip"][0], FONTS["tip"][1])
        if len(FONTS["tip"]) > 2 and "bold" in FONTS["tip"][2]:
            status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("margin-left: 5px;")

        # Add widgets to layout
        layout.addWidget(self.time_label)
        layout.addWidget(self.user_label)
        layout.addWidget(self.timeout_label)
        layout.addItem(spacer)
        layout.addWidget(self.connection_icon_widget)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

        # Timer to update time and battery
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(10000)
        self.update_data()

    def update_connection_status(self, is_connected: bool):
        """Update the connection icon dynamically"""
        tag = 'connected' if is_connected else 'disconnected'
        self.connection_icon_widget.load(get_icon_svg(tag))

    def update_user_info(self, username: str, role):
        """Update user information display"""
        if role == UserRole.ADMIN:
            role_text = "Admin"
            color = "#ff9800"  # Orange
        else:
            role_text = "User"
            color = "#4caf50"  # Green
        
        # Only show role, not username to avoid duplication like "admin (Admin)"
        self.user_label.setText(role_text)
        self.user_label.setStyleSheet(f"""
            QLabel {{
                margin-left: 10px;
                padding: 3px 8px;
                border-radius: 4px;
                background-color: {color};
                color: white;
                font-weight: bold;
            }}
        """)
        self.user_label.setVisible(True)
        
        # If admin, show timeout label
        if role == UserRole.ADMIN:
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
        self.time_label.setText(current_time)
    
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
        self.timeout_label.setStyleSheet(f"""
            QLabel {{
                margin-left: 10px;
                padding: 3px 8px;
                border-radius: 4px;
                background-color: {color};
                color: white;
                font-weight: bold;
            }}
        """)
        self.timeout_label.setVisible(True)
    
    def hide_timeout_display(self):
        """Hide timeout display"""
        self.timeout_label.setVisible(False)


class DataCard(QFrame):
    """Card widget for displaying radiation data"""
    def __init__(self, title, value, second_title, subvalue, subtitle, value_color="#ffffff", show_second_title=True, compact_mode=False, larger_font=False):
        super().__init__()
        
        # 设置固定高度，与ALARM STATUS框保持一致
        # ALARM STATUS框没有设置固定高度，但根据内容布局，大约为180-200px
        # 为了确保三个框一样大，我们设置固定高度
        self.setFixedHeight(180)  # 统一高度为180px
        
        # 存储larger_font参数
        self.larger_font = larger_font
        
        self.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 12px;
                border: none;
            }
        """)
        
        layout = QVBoxLayout()
        
        # 设置内边距和间距，与ALARM STATUS框保持一致
        # ALARM STATUS框的内边距是(10, 10, 10, 8)，间距是4
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(4)
        
        # Title - 使用与ALARM STATUS框标题相似的样式
        self.title_label = QLabel(title)
        title_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1] - 2)  # 稍微小一点的字体
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 0.5px;
                text-transform: uppercase;
                margin-bottom: 4px;
            }
        """)
        layout.addWidget(self.title_label)
        
        # Main value - 根据larger_font参数调整字体大小
        self.value_label = QLabel(value)
        if larger_font:
            # 更大字体：28px
            value_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1] + 10)  # 更大的字体
            font_size = "28px"
            min_height = "45px"
        else:
            # 正常字体：24px
            value_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1] + 6)  # 较大的字体
            font_size = "24px"
            min_height = "40px"
        
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
                font-size: 11px;
                font-weight: normal;
                margin-top: 2px;
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
                font-size: 16px;
                margin-top: 4px;
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
                font-size: 10px;
                font-weight: normal;
                margin-top: 2px;
                font-style: italic;
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
            }}
        """)
        self.sub_value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-weight: bold;
                font-size: 16px;
                margin-top: 4px;
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
            }}
        """)
        self.sub_value_label.setStyleSheet(f"""
            QLabel {{
                color: {value_color};
                font-size: 10px;
                font-weight: normal;
                margin-top: 8px;
                line-height: 1.2;
            }}
        """)


class BottomNavBar(QWidget):
    """Bottom navigation bar with page buttons"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
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
            "overview": "#4a9eff",      # 蓝色
            "spectrum": "#4caf50",      # 绿色
            "clients": "#ff9800",       # 橙色
            "alarm_log": "#f44336",     # 红色
            "settings": "#9c27b0"       # 紫色
        }
        
        # Overview button
        overview_widget = self.create_nav_button("Overview", "overview", button_colors["overview"], True)
        self.button_widgets.append(overview_widget)
        self.buttons.append(overview_widget.findChild(QPushButton))
        
        # Spectrum button (第二个页面)
        spectrum_widget = self.create_nav_button("Spectrum", "spectrum", button_colors["spectrum"], False)
        self.button_widgets.append(spectrum_widget)
        self.buttons.append(spectrum_widget.findChild(QPushButton))
        
        # Clients button (第三个页面)
        clients_widget = self.create_nav_button("Clients", "clients", button_colors["clients"], False)
        self.button_widgets.append(clients_widget)
        self.buttons.append(clients_widget.findChild(QPushButton))
        
        # Alarm log button (第四个页面)
        alarm_log_widget = self.create_nav_button("Alarm Log", "alarm_log", button_colors["alarm_log"], False)
        self.button_widgets.append(alarm_log_widget)
        self.buttons.append(alarm_log_widget.findChild(QPushButton))
        
        # Settings button
        settings_widget = self.create_nav_button("Settings", "settings", button_colors["settings"], False)
        self.button_widgets.append(settings_widget)
        self.buttons.append(settings_widget.findChild(QPushButton))
        
        layout.addWidget(overview_widget)
        layout.addWidget(spectrum_widget)
        layout.addWidget(clients_widget)
        layout.addWidget(alarm_log_widget)
        layout.addWidget(settings_widget)
        
        self.setLayout(layout)

        # 保持向后兼容性 - 添加按钮属性引用
        self.overview_btn = self.buttons[0]
        self.spectrum_btn = self.buttons[1]
        self.clients_btn = self.buttons[2]
        self.alarm_log_btn = self.buttons[3]
        self.settings_btn = self.buttons[4]
    
    def create_nav_button(self, text, icon_tag, color, active=False):
        """Create a navigation button with SVG icon"""
        # Create a container widget for the button
        container = QWidget()
        container.setObjectName("nav_button_container")  # 设置对象名称以便精确样式定位
        container.setFixedHeight(70)
        
        # Create layout for icon and text
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        
        # Create SVG icon
        icon_widget = QSvgWidget()
        icon_widget.setFixedSize(24, 24)
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
        
        # Create invisible button for click handling
        btn = QPushButton()
        btn.setFixedHeight(70)
        
        # Add everything to container
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addLayout(layout)
        container.setLayout(container_layout)
        
        # Position button on top of the content
        btn.setParent(container)
        btn.setGeometry(0, 0, container.width(), 70)
        btn.raise_()
        
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
            }}
        """)
        # 为图标添加发光效果 - 在 SVG 中添加发光滤镜
        svg_template = '''
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <filter id="glow">
                    <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
                    <feMerge>
                        <feMergeNode in="coloredBlur"/>
                        <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                </filter>
            </defs>
            <g filter="url(#glow)">
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
            # 生成带发光效果的 SVG
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
        container.setStyleSheet("""
            #nav_button_container {
                background-color: #1f1f1f;
                border: none;
                border-top: 3px solid transparent;
            }
        """)
        container.text_label.setStyleSheet("""
            QLabel {
                color: #888888;
            }
        """)
        # Update icon with inactive color
        svg_data = get_icon_svg(icon_tag).decode().replace('currentColor', '#888888')
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
    
    def set_active_button(self, index):
        """Set the active button"""
        for i, widget in enumerate(self.button_widgets):
            if i == index:
                self._apply_active_style(widget, widget.icon_tag, widget.theme_color)
            else:
                self._apply_inactive_style(widget, widget.icon_tag)


class AcquisitionButton(QPushButton):
    """Clear Data button"""
    def __init__(self):
        super().__init__("Clear Data")
        self.setFixedHeight(40)
        self.update_style()
    
    def update_style(self):
        self.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:pressed {
                background-color: #f57c00;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #aaaaaa;
            }
        """)












