from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy,
    QStackedWidget, QScrollArea
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QFont

from core.ui_components import DataCard, FONTS, PADDING
from core.icons import get_icon_svg
import time

# 概览页四张卡片统一高度，避免故障多行文字把整页撑出全屏
OVERVIEW_CARD_HEIGHT = 180


def _make_card_scroll_label(max_height: int = 40) -> QScrollArea:
    """卡片内可滚动说明文字，限制高度防止撑破全屏布局。"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setMaximumHeight(max_height)
    scroll.setStyleSheet("""
        QScrollArea { background: transparent; border: none; }
        QScrollBar:vertical { width: 4px; background: transparent; }
        QScrollBar::handle:vertical { background: #555555; border-radius: 2px; }
    """)
    label = QLabel("")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignCenter)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    scroll.setWidget(label)
    return scroll, label


class OverviewPage(QWidget):
    """Overview page showing radiation data cards and chart - optimized for 1024x600 screen"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        layout = QVBoxLayout()
        # Reduce margins for small screen
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Title - smaller font
        self.title = QLabel("伽玛能谱探测系统")
        self.title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 18px !important;
                font-weight: bold !important;
                margin-bottom: 8px;
            }
        """)
        layout.addWidget(self.title)
        
        # Cards row - ensure three cards have equal width
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)
        
        # Radiation card - shows count rate (cps) with larger font, no dose rate
        self.radiation_card = DataCard(
            "辐射水平",
            "0 cps",
            "当前计数率",  # Show second title
            "",  # Empty subvalue (no dose rate)
            "",  # Empty subtitle
            value_color="#ffffff",
            show_second_title=True,  # Show second title
            larger_font=True  # Use larger font for count rate
        )
        
        # Status card - shows temperature and HV
        self.status_card = DataCard(
            "设备状态",
            "0 " + chr(176) + "C",
            "探头温度",
            "0 V",
            "高压电压",
            value_color="#ff8c00"
        )
        
        # Alarm indicator card - optimized for compact
        self.alarm_card = QFrame()
        self.alarm_card.setFixedHeight(OVERVIEW_CARD_HEIGHT)
        self.alarm_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.alarm_card.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 10px;
                border: none;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2a2a2a, stop: 1 #1f1f1f);
            }
            QFrame:hover {
                border: 1px solid #444444;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2f2f2f, stop: 1 #242424);
            }
        """)
        
        alarm_layout = QVBoxLayout()
        alarm_layout.setContentsMargins(10, 10, 10, 8)
        alarm_layout.setSpacing(4)
        
        # Alarm title with icon
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)
        
        # Title icon
        self.alarm_title_icon = QSvgWidget()
        self.alarm_title_icon.setFixedSize(16, 16)
        self.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
        title_layout.addWidget(self.alarm_title_icon)
        
        self.alarm_title_label = QLabel("报警状态")
        self.alarm_title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }
        """)
        title_layout.addWidget(self.alarm_title_label)
        title_layout.addStretch()
        
        alarm_layout.addLayout(title_layout)
        
        # Main alarm indicator
        self.alarm_indicator = QSvgWidget()
        self.alarm_indicator.setFixedSize(40, 40)
        self.alarm_indicator.load(get_icon_svg('alarm_inactive'))
        alarm_layout.addWidget(self.alarm_indicator, 0, Qt.AlignCenter)
        
        # Alarm status label
        self.alarm_status_label = QLabel("系统正常")
        self.alarm_status_label.setStyleSheet("""
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
        self.alarm_status_label.setAlignment(Qt.AlignCenter)
        alarm_layout.addWidget(self.alarm_status_label, 0, Qt.AlignCenter)
        
        # Alarm description (scrollable, max 2 lines visible)
        self.alarm_desc_scroll, self.alarm_desc_label = _make_card_scroll_label(38)
        self.alarm_desc_label.setText("未检测到异常")
        self.alarm_desc_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 11px;
                font-weight: normal;
                margin-top: 0px;
            }
        """)
        alarm_layout.addWidget(self.alarm_desc_scroll)
        
        # Status indicator bar
        self.status_indicator_bar = QFrame()
        self.status_indicator_bar.setFixedHeight(2)
        self.status_indicator_bar.setStyleSheet("""
            QFrame {
                background-color: #4caf50;
                border-radius: 1px;
                margin-top: 3px;
            }
        """)
        alarm_layout.addWidget(self.status_indicator_bar)
        
        self.alarm_card.setLayout(alarm_layout)

        # Occupancy indicator card - optimized for compact
        self.occupancy_card = QFrame()
        self.occupancy_card.setFixedHeight(OVERVIEW_CARD_HEIGHT)
        self.occupancy_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.occupancy_card.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 10px;
                border: none;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2a2a2a, stop: 1 #1f1f1f);
            }
            QFrame:hover {
                border: 1px solid #444444;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2f2f2f, stop: 1 #242424);
            }
        """)
        
        occupancy_layout = QVBoxLayout()
        occupancy_layout.setContentsMargins(10, 10, 10, 8)
        occupancy_layout.setSpacing(4)
        
        # Occupancy title with icon
        occ_title_layout = QHBoxLayout()
        occ_title_layout.setContentsMargins(0, 0, 0, 0)
        occ_title_layout.setSpacing(6)
        
        # Title icon
        self.occupancy_title_icon = QSvgWidget()
        self.occupancy_title_icon.setFixedSize(16, 16)
        self.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
        occ_title_layout.addWidget(self.occupancy_title_icon)
        
        self.occupancy_title_label = QLabel("通道状态")
        self.occupancy_title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }
        """)
        occ_title_layout.addWidget(self.occupancy_title_label)
        occ_title_layout.addStretch()
        
        occupancy_layout.addLayout(occ_title_layout)
        
        # Main occupancy indicator
        self.occupancy_indicator = QSvgWidget()
        self.occupancy_indicator.setFixedSize(40, 40)
        self.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
        occupancy_layout.addWidget(self.occupancy_indicator, 0, Qt.AlignCenter)
        
        # Occupancy status label
        self.occupancy_status_label = QLabel("通道空闲")
        self.occupancy_status_label.setStyleSheet("""
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
        self.occupancy_status_label.setAlignment(Qt.AlignCenter)
        occupancy_layout.addWidget(self.occupancy_status_label, 0, Qt.AlignCenter)
        
        # Occupancy description (scrollable)
        self.occupancy_desc_scroll, self.occupancy_desc_label = _make_card_scroll_label(38)
        self.occupancy_desc_label.setText("未检测到人员经过")
        self.occupancy_desc_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 11px;
                font-weight: normal;
                margin-top: 0px;
            }
        """)
        occupancy_layout.addWidget(self.occupancy_desc_scroll)
        
        # Occupancy indicator bar
        self.occupancy_indicator_bar = QFrame()
        self.occupancy_indicator_bar.setFixedHeight(2)
        self.occupancy_indicator_bar.setStyleSheet("""
            QFrame {
                background-color: #4caf50;
                border-radius: 1px;
                margin-top: 3px;
            }
        """)
        occupancy_layout.addWidget(self.occupancy_indicator_bar)
        
        self.occupancy_card.setLayout(occupancy_layout)
        
        # Add four cards to layout with equal width
        cards_layout.addWidget(self.radiation_card, 1)
        cards_layout.addWidget(self.status_card, 1)
        cards_layout.addWidget(self.alarm_card, 1)
        cards_layout.addWidget(self.occupancy_card, 1)
        
        layout.addLayout(cards_layout)
        
        # Chart section：标题与时间窗口同一行，不额外占曲线高度
        chart_header = QHBoxLayout()
        chart_header.setContentsMargins(0, 0, 0, 0)
        chart_header.setSpacing(8)

        self.chart_title = QLabel("实时计数率时序图")
        chart_title_font = QFont(FONTS["subtitle"][0], FONTS["subtitle"][1])
        if len(FONTS["subtitle"]) > 2 and "bold" in FONTS["subtitle"][2]:
            chart_title_font.setBold(True)
        self.chart_title.setFont(chart_title_font)
        self.chart_title.setStyleSheet("""
            QLabel {
                color: white;
                font-weight: bold;
                font-size: 14px;
                margin-top: 4px;
                margin-bottom: 2px;
            }
        """)
        chart_header.addWidget(self.chart_title, 1)
        if hasattr(parent, "create_cps_window_controls_widget"):
            chart_header.addWidget(parent.create_cps_window_controls_widget(), 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(chart_header)
        
        self.chart = parent.create_cps_widget()
        layout.addWidget(self.chart, 1)
        
        self.setLayout(layout)


    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.title.setText(_t("sys_title"))
        
        # Update DataCards titles
        self.radiation_card.title_label.setText(_t("card_rad_title"))
        self.radiation_card.second_title_label.setText(_t("card_rad_desc"))
        
        self.status_card.title_label.setText(_t("card_status_title"))
        self.status_card.second_title_label.setText(_t("card_status_temp"))
        self.status_card.subtitle_label.setText(_t("card_status_hv"))
        
        # Update Alarm card
        self.alarm_title_label.setText(_t("card_alarm_title"))
        self.alarm_status_label.setText(_t("status_normal"))
        self.alarm_desc_label.setText(_t("desc_no_alarm"))
        
        # Update Occupancy card
        self.occupancy_title_label.setText(_t("card_occ_title"))
        self.occupancy_status_label.setText(_t("status_vacant"))
        self.occupancy_desc_label.setText(_t("desc_no_traffic"))
        
        # Update Chart title
        self.chart_title.setText(_t("chart_title"))


class SpectrumPage(QWidget):
    """Spectrum page for displaying energy spectrum"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        self.title = QLabel("能谱与谱图分析")
        self.title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px !important;
                font-weight: bold !important;
                margin-bottom: 20px;
            }
        """)
        layout.addWidget(self.title)
        
        # Create a splitter layout for better resizing
        from PyQt5.QtWidgets import QSplitter
        
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #444444;
                height: 2px;
            }
            QSplitter::handle:hover {
                background-color: #666666;
            }
        """)
        
        # Placeholder for spectrum display
        self.spec_widget = parent.create_spec_widget()
        self.spectrogram_widget = parent.create_spectrogram_widget()
        
        # Add widgets to splitter
        splitter.addWidget(self.spec_widget)
        splitter.addWidget(self.spectrogram_widget)
        
        # Set initial sizes (60% for spectrum, 40% for spectrogram)
        splitter.setSizes([400, 300])
        
        # Set minimum sizes to ensure visibility
        self.spec_widget.setMinimumHeight(200)
        self.spectrogram_widget.setMinimumHeight(150)
        
        layout.addWidget(splitter, 1)
        
        self.setLayout(layout)

    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.title.setText(_t("spec_title"))


class SettingsPage(QWidget):
    """Settings page for configuration"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        self.title = QLabel("系统设置")
        self.title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px !important;
                font-weight: bold !important;
                margin-bottom: 20px;
            }
        """)
        main_layout.addWidget(self.title)

        # Create scroll area for settings content
        from PyQt5.QtWidgets import QScrollArea
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        # Create container widget
        container_widget = QWidget()
        container_layout = QVBoxLayout(container_widget)
        container_layout.setContentsMargins(5, 5, 15, 5)
        container_layout.setSpacing(15)
        
        # Add settings content to container layout
        parent.add_widgets_to_setting_layout(container_layout)
        
        # Add stretch
        container_layout.addStretch()
        
        # Set container widget to scroll area
        scroll_area.setWidget(container_widget)
        
        # Add scroll area to main layout
        main_layout.addWidget(scroll_area, 1)
        
        self.setLayout(main_layout)

    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.title.setText(_t("settings_title"))


class ClientsPage(QWidget):
    """Clients page showing detailed information for each connected client"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        
        # Main layout is a QVBoxLayout containing the QStackedWidget
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.stacked_widget = QStackedWidget()
        
        # 1. Lock screen widget (Index 0) — 可滚动，适配 1024x600 全屏
        self.lock_widget = QWidget()
        lock_outer = QVBoxLayout(self.lock_widget)
        lock_outer.setContentsMargins(0, 0, 0, 0)

        lock_scroll = QScrollArea()
        lock_scroll.setWidgetResizable(True)
        lock_scroll.setFrameShape(QFrame.NoFrame)
        lock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lock_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        lock_content = QWidget()
        lock_layout = QVBoxLayout(lock_content)
        lock_layout.setContentsMargins(20, 16, 20, 16)
        lock_layout.setSpacing(10)
        lock_layout.setAlignment(Qt.AlignCenter)
        
        # Lock Icon
        self.lock_icon = QSvgWidget()
        self.lock_icon.setFixedSize(64, 64)
        self.lock_icon.load(get_icon_svg('lock'))
        lock_layout.addWidget(self.lock_icon, 0, Qt.AlignCenter)
        
        # Lock Title
        self.lock_title = QLabel("工程师诊断界面 (工程师/维保人员专用)")
        self.lock_title.setWordWrap(True)
        self.lock_title.setStyleSheet("""
            QLabel {
                color: #ff9800;
                font-size: 18px;
                font-weight: bold;
                margin-top: 6px;
            }
        """)
        self.lock_title.setAlignment(Qt.AlignCenter)
        lock_layout.addWidget(self.lock_title)
        
        # Lock Description
        self.lock_desc = QLabel(
            "此界面包含详细的硬件参数、探头原始数据及故障诊断代码。\n"
            "根据工业安全与 ISA-18.2 规范，日常运行中这些信息对普通操作员隐藏。\n\n"
            "请点击下方按钮输入工程师密码进行解锁查看。"
        )
        self.lock_desc.setWordWrap(True)
        self.lock_desc.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 13px;
                margin-top: 4px;
            }
        """)
        self.lock_desc.setAlignment(Qt.AlignCenter)
        lock_layout.addWidget(self.lock_desc)
        
        # Unlock Button
        self.unlock_btn = QPushButton("输入工程师密码解锁")
        self.unlock_btn.setFixedHeight(42)
        self.unlock_btn.setMinimumWidth(220)
        self.unlock_btn.setMaximumWidth(320)
        self.unlock_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: bold;
                margin-top: 12px;
            }
            QPushButton:pressed {
                background-color: #e65100;
            }
        """)
        self.unlock_btn.clicked.connect(self.parent.login)
        lock_layout.addWidget(self.unlock_btn, 0, Qt.AlignCenter)

        lock_scroll.setWidget(lock_content)
        lock_outer.addWidget(lock_scroll)
        
        # 2. Content widget (Index 1)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(12, 10, 12, 8)
        content_layout.setSpacing(8)
        
        # Title
        self.clients_title = QLabel("已连接的探测器")
        self.clients_title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 18px !important;
                font-weight: bold !important;
                margin-bottom: 4px;
            }
        """)
        content_layout.addWidget(self.clients_title)
        
        # Client count summary
        self.client_summary_label = QLabel("无探测器连接")
        summary_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        self.client_summary_label.setFont(summary_font)
        self.client_summary_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-weight: normal;
                margin-bottom: 4px;
            }
        """)
        content_layout.addWidget(self.client_summary_label)
        
        # Scroll area for client cards (真正的 QScrollArea)
        self.client_list_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.client_list_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)

        client_scroll = QScrollArea()
        client_scroll.setWidgetResizable(True)
        client_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        client_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        client_scroll.setFrameShape(QFrame.NoFrame)
        client_scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: transparent; }
            QScrollArea > QWidget > QWidget { background-color: transparent; }
        """)
        client_scroll.setWidget(self.client_list_widget)
        self.client_scroll = client_scroll
        content_layout.addWidget(client_scroll, 1)
        
        # Add refresh button
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
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
        """)
        self.refresh_btn.clicked.connect(self.refresh_client_display)
        content_layout.addWidget(self.refresh_btn, 0, Qt.AlignCenter)
        
        # Add widgets to stacked widget
        self.stacked_widget.addWidget(self.lock_widget)
        self.stacked_widget.addWidget(self.content_widget)
        
        main_layout.addWidget(self.stacked_widget, 1)
        self.setLayout(main_layout)
        
        # Timer to auto-refresh client display
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_client_display)
        self.refresh_timer.start(2000)
        
        # Store client widgets
        self.client_widgets = {}
    
    def refresh_client_display(self):
        """Refresh the client display with current data"""
        # Check current user role
        from core.user_manager import UserRole
        is_admin = False
        if hasattr(self.parent, 'current_user') and self.parent.current_user:
            is_admin = self.parent.current_user.get('role') == UserRole.ADMIN
            
        if not is_admin:
            self.stacked_widget.setCurrentIndex(0)
            return
        else:
            self.stacked_widget.setCurrentIndex(1)

        # Get client data from parent
        if hasattr(self.parent, 'client_data'):
            client_data = self.parent.client_data
        else:
            client_data = getattr(self.parent, 'client_data', {})
        
        # Update summary
        from core.translation import _t
        client_count = len(client_data)
        if client_count == 0:
            self.client_summary_label.setText(_t("clients_no_conn"))
        else:
            self.client_summary_label.setText(_t("clients_conn_count", count=client_count))
        
        # Remove old client widgets
        for client_id, widget in list(self.client_widgets.items()):
            if client_id not in client_data:
                self.scroll_layout.removeWidget(widget)
                widget.deleteLater()
                del self.client_widgets[client_id]
        
        # Add/update client widgets
        for client_id, data in client_data.items():
            if client_id not in self.client_widgets:
                client_widget = self.create_client_widget(client_id, data)
                self.client_widgets[client_id] = client_widget
                self.scroll_layout.addWidget(client_widget)
            else:
                self.update_client_widget(self.client_widgets[client_id], data)
        
        # Add stretch at the end
        if self.scroll_layout.count() > 0:
            for i in range(self.scroll_layout.count()):
                item = self.scroll_layout.itemAt(i)
                if item and item.spacerItem():
                    self.scroll_layout.removeItem(item)
                    break
            self.scroll_layout.addStretch()
    
    def create_client_widget(self, client_id: str, data: dict) -> QFrame:
        """Create a widget for displaying client information"""
        from core.translation import _t
        widget = QFrame()
        widget.setMinimumHeight(140)
        widget.setMaximumHeight(160)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 12px;
                border: 1px solid #333333;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        
        # Client ID and status
        left_layout = QVBoxLayout()
        left_layout.setSpacing(3)
        
        client_id_label = QLabel(_t("probe_id", id=client_id))
        client_id_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        left_layout.addWidget(client_id_label)
        
        # Last update time
        last_update = data.get('last_update', 0)
        time_diff = time.time() - last_update
        status_color = "#4caf50" if time_diff < 5 else "#ff9800" if time_diff < 15 else "#f44336"
        status_text = _t("status_active") if time_diff < 5 else _t("status_idle") if time_diff < 15 else _t("status_inactive")
        
        status_label = QLabel(_t("probe_status", status=status_text))
        status_label.setStyleSheet(f"""
            QLabel {{
                color: {status_color};
                font-size: 14px;
                font-weight: normal;
            }}
        """)
        left_layout.addWidget(status_label)
        
        # Alarm status
        alarm_status = data.get('alarm', False)
        alarm_label = QLabel(_t("probe_alarm_active") if alarm_status else _t("probe_alarm_normal"))
        alarm_label.setStyleSheet(f"""
            QLabel {{
                color: {'#ff4444' if alarm_status else '#4caf50'};
                font-size: 14px;
                font-weight: bold;
                margin-top: 2px;
            }}
        """)
        left_layout.addWidget(alarm_label)

        # Occupancy status
        occupancy_status = data.get('occupancy', False)
        occupancy_label = QLabel(_t("probe_occ_active") if occupancy_status else _t("probe_occ_normal"))
        occupancy_label.setStyleSheet(f"""
            QLabel {{
                color: {'#ffb74d' if occupancy_status else '#4caf50'};
                font-size: 14px;
                font-weight: bold;
                margin-top: 2px;
            }}
        """)
        left_layout.addWidget(occupancy_label)

        # Faults status
        faults_label = QLabel(_t("probe_faults_normal"))
        faults_label.setStyleSheet("""
            QLabel {
                color: #4caf50;
                font-size: 12px;
                font-weight: bold;
                margin-top: 2px;
            }
        """)
        left_layout.addWidget(faults_label)
        
        left_layout.addStretch()
        layout.addLayout(left_layout)
        
        # Data display
        data_layout = QGridLayout()
        data_layout.setHorizontalSpacing(20)
        data_layout.setVerticalSpacing(5)
        
        # Count rate
        count_rate_label = QLabel(_t("label_rates"))
        count_rate_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 14px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(count_rate_label, 0, 0)
        
        count_rate_value = QLabel(f"{data.get('rates', 0)} cps")
        count_rate_value.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        data_layout.addWidget(count_rate_value, 0, 1)
        
        # Temperature
        temp_label = QLabel(_t("label_temp"))
        temp_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 14px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(temp_label, 1, 0)
        
        temp_value = QLabel(f"{data.get('temp', 0):.1f} " + chr(176) + "C")
        temp_value.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        data_layout.addWidget(temp_value, 1, 1)
        
        # High Voltage
        hv_label = QLabel(_t("label_hv"))
        hv_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 14px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(hv_label, 2, 0)
        
        hv_value = QLabel(f"{data.get('hv', 0):.1f} V")
        hv_value.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        data_layout.addWidget(hv_value, 2, 1)
        
        # Product ID and Sensitivity
        product_label = QLabel(_t("label_product_id"))
        product_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(product_label, 0, 2)
        
        product_value = QLabel(f"{data.get('product_id', 0)}")
        product_value.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 12px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(product_value, 0, 3)
        
        sensitivity_label = QLabel(_t("label_sensitivity"))
        sensitivity_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(sensitivity_label, 1, 2)
        
        sensitivity_value = QLabel(f"{data.get('sensitivity', 0)}")
        sensitivity_value.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 12px;
                font-weight: normal;
            }
        """)
        data_layout.addWidget(sensitivity_value, 1, 3)
        
        layout.addLayout(data_layout)
        
        widget.setLayout(layout)
        
        # Store references to updateable labels
        widget.data_labels = {
            'count_rate': count_rate_value,
            'temp': temp_value,
            'hv': hv_value,
            'product_id': product_value,
            'sensitivity': sensitivity_value,
            'status': status_label,
            'alarm': alarm_label,
            'occupancy': occupancy_label,
            'faults': faults_label
        }
        
        return widget
    
    def update_client_widget(self, widget: QFrame, data: dict):
        """Update an existing client widget with new data"""
        from core.translation import _t
        labels = widget.data_labels
        
        # Update data values
        labels['count_rate'].setText(f"{data.get('rates', 0)} cps")
        labels['temp'].setText(f"{data.get('temp', 0):.1f} " + chr(176) + "C")
        labels['hv'].setText(f"{data.get('hv', 0):.1f} V")
        labels['product_id'].setText(f"{data.get('product_id', 0)}")
        labels['sensitivity'].setText(f"{data.get('sensitivity', 0)}")
        
        # Update status
        last_update = data.get('last_update', 0)
        time_diff = time.time() - last_update
        status_color = "#4caf50" if time_diff < 5 else "#ff9800" if time_diff < 15 else "#f44336"
        status_text = _t("status_active") if time_diff < 5 else _t("status_idle") if time_diff < 15 else _t("status_inactive")
        
        labels['status'].setText(_t("probe_status", status=status_text))
        labels['status'].setStyleSheet(f"""
            QLabel {{
                color: {status_color};
                font-size: 12px;
                font-weight: normal;
            }}
        """)
        
        # Update alarm status
        alarm_status = data.get('alarm', False)
        labels['alarm'].setText(_t("probe_alarm_active") if alarm_status else _t("probe_alarm_normal"))
        labels['alarm'].setStyleSheet(f"""
            QLabel {{
                color: {'#ff4444' if alarm_status else '#4caf50'};
                font-size: 12px;
                font-weight: bold;
                margin-top: 5px;
            }}
        """)

        # Update occupancy status
        occupancy_status = data.get('occupancy', False)
        labels['occupancy'].setText(_t("probe_occ_active") if occupancy_status else _t("probe_occ_normal"))
        labels['occupancy'].setStyleSheet(f"""
            QLabel {{
                color: {'#ffb74d' if occupancy_status else '#4caf50'};
                font-size: 12px;
                font-weight: bold;
                margin-top: 5px;
            }}
        """)

        # Update faults status
        client_id = data.get('client_id')
        if hasattr(self.parent, 'diagnostics_manager') and client_id:
            active_faults = self.parent.diagnostics_manager.active_faults.get(client_id, {})
            if active_faults:
                faults_str = ", ".join(active_faults.keys())
                labels['faults'].setText(_t("probe_faults_active", faults=faults_str))
                labels['faults'].setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 12px;
                        font-weight: bold;
                        margin-top: 5px;
                    }
                """)
            else:
                labels['faults'].setText(_t("probe_faults_normal"))
                labels['faults'].setStyleSheet("""
                    QLabel {
                        color: #4caf50;
                        font-size: 12px;
                        font-weight: bold;
                        margin-top: 5px;
                    }
                """)

    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.lock_title.setText(_t("lock_title"))
        self.lock_desc.setText(_t("lock_desc"))
        self.unlock_btn.setText(_t("btn_unlock"))
        self.clients_title.setText(_t("clients_title"))
        self.refresh_btn.setText(_t("btn_refresh"))
        
        # Trigger refresh to update summary and existing client widgets
        self.refresh_client_display()
