from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy,
    QStackedWidget, QScrollArea, QAbstractScrollArea
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QFont

from core.ui_components import DataCard, FONTS, PADDING
from core.icons import get_icon_svg
from core.ui_tokens import PAGE_TITLE_QSS, TOUCH_H, RADIUS_BTN, WARN, OK, CR_SETTINGS_PAGE_QSS, cr_px
import time

# Original overview page card height
OVERVIEW_CARD_HEIGHT = 180


def _make_card_scroll_label(max_height: int = 40) -> QScrollArea:
    """Scrollable description inside cards."""
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
    """Original overview: radiation/status/alarm/occupancy cards + CPS chart."""

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.title = QLabel("Gamma Spectrum System")
        self.title.setStyleSheet(PAGE_TITLE_QSS)
        layout.addWidget(self.title)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)

        self.radiation_card = DataCard(
            "Radiation",
            "0 cps",
            "Count rate",
            "",
            "",
            value_color="#ffffff",
            show_second_title=True,
            larger_font=True
        )
        self.status_card = DataCard(
            "Device",
            "0 C",
            "Temperature",
            "0 V",
            "HV",
            value_color="#ff8c00"
        )

        # Alarm card
        self.alarm_card = QFrame()
        self.alarm_card.setObjectName("overviewCard")
        self.alarm_card.setFixedHeight(OVERVIEW_CARD_HEIGHT)
        self.alarm_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.alarm_card.setStyleSheet("""
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
        alarm_layout = QVBoxLayout()
        alarm_layout.setContentsMargins(10, 10, 10, 8)
        alarm_layout.setSpacing(4)

        title_layout = QHBoxLayout()
        self.alarm_title_icon = QSvgWidget()
        self.alarm_title_icon.setFixedSize(16, 16)
        self.alarm_title_icon.load(get_icon_svg('alarm_inactive'))
        title_layout.addWidget(self.alarm_title_icon)
        self.alarm_title_label = QLabel("Alarm")
        self.alarm_title_label.setStyleSheet(
            "color: #cccccc; font-size: 13px; font-weight: bold; background: transparent; border: none;"
        )
        title_layout.addWidget(self.alarm_title_label)
        title_layout.addStretch()
        alarm_layout.addLayout(title_layout)

        self.alarm_indicator = QSvgWidget()
        self.alarm_indicator.setFixedSize(40, 40)
        self.alarm_indicator.load(get_icon_svg('alarm_inactive'))
        alarm_layout.addWidget(self.alarm_indicator, 0, Qt.AlignCenter)

        self.alarm_status_label = QLabel("Normal")
        self.alarm_status_label.setAlignment(Qt.AlignCenter)
        self.alarm_status_label.setStyleSheet("""
            QLabel {
                color: #4caf50; font-size: 16px; font-weight: bold;
                margin-top: 2px; background: transparent; border: none;
            }
        """)
        alarm_layout.addWidget(self.alarm_status_label, 0, Qt.AlignCenter)

        self.alarm_desc_scroll, self.alarm_desc_label = _make_card_scroll_label(38)
        self.alarm_desc_label.setText("No alarm")
        self.alarm_desc_label.setStyleSheet("color: #aaaaaa; font-size: 11px; background: transparent; border: none;")
        alarm_layout.addWidget(self.alarm_desc_scroll)

        self.status_indicator_bar = QFrame()
        self.status_indicator_bar.setObjectName("cardAccentBar")
        self.status_indicator_bar.setFixedHeight(2)
        self.status_indicator_bar.setStyleSheet(
            "QFrame#cardAccentBar { background-color: #4caf50; border: none; border-radius: 1px; }"
        )
        alarm_layout.addWidget(self.status_indicator_bar)
        self.alarm_card.setLayout(alarm_layout)

        # Occupancy card
        self.occupancy_card = QFrame()
        self.occupancy_card.setObjectName("overviewCard")
        self.occupancy_card.setFixedHeight(OVERVIEW_CARD_HEIGHT)
        self.occupancy_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.occupancy_card.setStyleSheet("""
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
        occupancy_layout = QVBoxLayout()
        occupancy_layout.setContentsMargins(10, 10, 10, 8)
        occupancy_layout.setSpacing(4)

        occ_title_layout = QHBoxLayout()
        self.occupancy_title_icon = QSvgWidget()
        self.occupancy_title_icon.setFixedSize(16, 16)
        self.occupancy_title_icon.load(get_icon_svg('occupancy_inactive'))
        occ_title_layout.addWidget(self.occupancy_title_icon)
        self.occupancy_title_label = QLabel("Channel")
        self.occupancy_title_label.setStyleSheet(
            "color: #cccccc; font-size: 13px; font-weight: bold; background: transparent; border: none;"
        )
        occ_title_layout.addWidget(self.occupancy_title_label)
        occ_title_layout.addStretch()
        occupancy_layout.addLayout(occ_title_layout)

        self.occupancy_indicator = QSvgWidget()
        self.occupancy_indicator.setFixedSize(40, 40)
        self.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
        occupancy_layout.addWidget(self.occupancy_indicator, 0, Qt.AlignCenter)

        self.occupancy_status_label = QLabel("Vacant")
        self.occupancy_status_label.setAlignment(Qt.AlignCenter)
        self.occupancy_status_label.setStyleSheet("""
            QLabel {
                color: #4caf50; font-size: 16px; font-weight: bold;
                margin-top: 2px; background: transparent; border: none;
            }
        """)
        occupancy_layout.addWidget(self.occupancy_status_label, 0, Qt.AlignCenter)

        self.occupancy_desc_scroll, self.occupancy_desc_label = _make_card_scroll_label(38)
        self.occupancy_desc_label.setText("No traffic")
        self.occupancy_desc_label.setStyleSheet("color: #aaaaaa; font-size: 11px; background: transparent; border: none;")
        occupancy_layout.addWidget(self.occupancy_desc_scroll)

        self.occupancy_indicator_bar = QFrame()
        self.occupancy_indicator_bar.setObjectName("cardAccentBar")
        self.occupancy_indicator_bar.setFixedHeight(2)
        self.occupancy_indicator_bar.setStyleSheet(
            "QFrame#cardAccentBar { background-color: #4caf50; border: none; border-radius: 1px; }"
        )
        occupancy_layout.addWidget(self.occupancy_indicator_bar)
        self.occupancy_card.setLayout(occupancy_layout)

        cards_layout.addWidget(self.radiation_card, 1)
        cards_layout.addWidget(self.status_card, 1)
        cards_layout.addWidget(self.alarm_card, 1)
        cards_layout.addWidget(self.occupancy_card, 1)
        layout.addLayout(cards_layout)

        chart_header = QHBoxLayout()
        chart_header.setContentsMargins(0, 0, 0, 0)
        chart_header.setSpacing(8)
        self.chart_title = QLabel("CPS Chart")
        chart_title_font = QFont(FONTS["subtitle"][0], FONTS["subtitle"][1])
        if len(FONTS["subtitle"]) > 2 and "bold" in FONTS["subtitle"][2]:
            chart_title_font.setBold(True)
        self.chart_title.setFont(chart_title_font)
        self.chart_title.setStyleSheet(
            "QLabel { color: white; font-weight: bold; font-size: 14px; }"
        )
        chart_header.addWidget(self.chart_title, 1)
        if hasattr(parent, "create_cps_window_controls_widget"):
            chart_header.addWidget(
                parent.create_cps_window_controls_widget(),
                0, Qt.AlignRight | Qt.AlignVCenter
            )
        layout.addLayout(chart_header)

        self.chart = parent.create_cps_widget()
        layout.addWidget(self.chart, 1)
        self.setLayout(layout)

    def retranslate_ui(self):
        from core.translation import _t
        self.title.setText(_t("sys_title_overview"))
        self.radiation_card.title_label.setText(_t("card_rad_title_overview"))
        self.radiation_card.second_title_label.setText(_t("card_rad_desc_overview"))
        self.status_card.title_label.setText(_t("card_status_title_overview"))
        self.status_card.second_title_label.setText(_t("card_status_temp"))
        self.status_card.subtitle_label.setText(_t("card_status_hv"))
        self.alarm_title_label.setText(_t("card_alarm_title"))
        self.alarm_status_label.setText(_t("status_normal"))
        self.alarm_desc_label.setText(_t("desc_no_alarm"))
        self.occupancy_title_label.setText(_t("card_occ_title"))
        self.occupancy_status_label.setText(_t("status_vacant"))
        self.occupancy_desc_label.setText(_t("desc_no_traffic"))
        self.chart_title.setText(_t("chart_title"))


class SpectrumPage(QWidget):
    """Spectrum page for displaying energy spectrum"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        self.title = QLabel("能谱与谱图分析")
        self.title.setStyleSheet(PAGE_TITLE_QSS)
        layout.addWidget(self.title)
        
        # Create a splitter layout for better resizing
        from PyQt5.QtWidgets import QSplitter
        
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1a1a1a;
                height: 6px;
                margin: 0;
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
        main_layout.setContentsMargins(20, 12, 20, 8)
        main_layout.setSpacing(8)
        
        self.title = QLabel("系统设置")
        self.title.setStyleSheet(PAGE_TITLE_QSS)
        main_layout.addWidget(self.title)

        # 设置项很多：必须让滚动区可以缩到比内容更矮，否则全屏+高 DPI
        # 时 QStackedWidget 会按内容高度把底栏顶出屏幕。
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setMinimumHeight(0)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        try:
            scroll_area.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        except Exception:
            pass
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        container_widget = QWidget()
        container_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if getattr(parent, "control_room_mode", False):
            container_widget.setStyleSheet(CR_SETTINGS_PAGE_QSS)
        container_layout = QVBoxLayout(container_widget)
        container_layout.setContentsMargins(5, 5, 15, 5)
        container_layout.setSpacing(10)
        
        parent.add_widgets_to_setting_layout(container_layout)
        container_layout.addStretch()
        
        scroll_area.setWidget(container_widget)
        main_layout.addWidget(scroll_area, 1)
        
        self.setLayout(main_layout)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
        self.unlock_btn.setFixedHeight(TOUCH_H)
        self.unlock_btn.setMinimumWidth(220)
        self.unlock_btn.setMaximumWidth(320)
        self.unlock_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {WARN};
                color: white;
                border: none;
                border-radius: {RADIUS_BTN}px;
                font-size: 15px;
                font-weight: bold;
                margin-top: 12px;
            }}
            QPushButton:pressed {{
                background-color: #e65100;
            }}
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
        self.clients_title.setStyleSheet(PAGE_TITLE_QSS)
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
        self.refresh_btn.setFixedHeight(TOUCH_H)
        self.refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {OK};
                color: white;
                border: none;
                border-radius: {RADIUS_BTN}px;
                font-size: 15px;
                font-weight: bold;
                padding: 0 20px;
                min-width: 140px;
            }}
            QPushButton:pressed {{
                background-color: #45a049;
            }}
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
        self._apply_control_room_diag_chrome()

    def _diag_px(self, n: int) -> int:
        """Same px ladder as probe cards; control-room scales with cr_px."""
        if getattr(self.parent, "control_room_mode", False):
            return cr_px(n)
        return int(n)

    def _diag_style(self, role: str, color: str = None) -> str:
        p = self._diag_px
        color = color or "#ffffff"
        if role == "title":
            return "QLabel { color: %s; font-size: %dpx; font-weight: bold; }" % (color, p(16))
        if role == "status":
            return "QLabel { color: %s; font-size: %dpx; font-weight: normal; }" % (color, p(14))
        if role == "alarm":
            return (
                "QLabel { color: %s; font-size: %dpx; font-weight: bold; margin-top: 2px; }"
                % (color, p(14))
            )
        if role == "faults":
            return (
                "QLabel { color: %s; font-size: %dpx; font-weight: bold; margin-top: 2px; }"
                % (color, p(12))
            )
        if role == "key":
            return "QLabel { color: #aaaaaa; font-size: %dpx; font-weight: normal; }" % p(14)
        if role == "val":
            return "QLabel { color: %s; font-size: %dpx; font-weight: bold; }" % (color, p(16))
        if role == "key2":
            return "QLabel { color: #aaaaaa; font-size: %dpx; font-weight: normal; }" % p(12)
        if role == "val2":
            return "QLabel { color: #cccccc; font-size: %dpx; font-weight: normal; }" % p(12)
        return "QLabel { color: %s; font-size: %dpx; }" % (color, p(14))

    def _diag_card_qss(self) -> str:
        return """
            QFrame {
                background-color: #2a2a2a;
                border-radius: 10px;
                border: 1px solid #333333;
            }
        """

    def _apply_control_room_diag_chrome(self):
        if not getattr(self.parent, "control_room_mode", False):
            return
        from core.ui_tokens import CR_CHROME_H, CR_CHROME_FONT_PX, TEXT, MUTED
        title_px = cr_px(22)
        self.clients_title.setStyleSheet(
            "QLabel { color: %s; font-size: %dpx; font-weight: bold; "
            "margin-bottom: 8px; background: transparent; border: none; }"
            % (TEXT, title_px)
        )
        self.lock_title.setStyleSheet(
            "QLabel { color: #ff9800; font-size: %dpx; font-weight: bold; margin-top: 6px; }"
            % cr_px(18)
        )
        self.lock_desc.setStyleSheet(
            "QLabel { color: %s; font-size: %dpx; margin-top: 4px; }" % (MUTED, cr_px(13))
        )
        self.unlock_btn.setFixedHeight(CR_CHROME_H)
        self.refresh_btn.setFixedHeight(CR_CHROME_H)
        for btn, bg, press in (
            (self.unlock_btn, WARN, "#e65100"),
            (self.refresh_btn, OK, "#45a049"),
        ):
            btn.setStyleSheet(
                "QPushButton { background-color: %s; color: white; border: none; "
                "border-radius: %dpx; font-size: %dpx; font-weight: bold; "
                "padding: 0 16px; min-height: %dpx; }"
                "QPushButton:pressed { background-color: %s; }"
                % (bg, RADIUS_BTN, CR_CHROME_FONT_PX, CR_CHROME_H, press)
            )

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_client_display()
    
    def refresh_client_display(self):
        """Refresh the client display with current data"""
        if not self.isVisible():
            return
        # Check current user role
        from core.user_manager import UserRole
        is_admin = False
        if hasattr(self.parent, 'current_user') and self.parent.current_user:
            is_admin = self.parent.current_user.get('role') in (
                UserRole.ADMIN,
                UserRole.MAINTAINER,
            )
            
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

        # Dedicated master card
        master_key = "__master__"
        master_data = self._collect_master_diag_data()
        if master_data is not None:
            if master_key not in self.client_widgets:
                master_widget = self.create_master_widget(master_data)
                self.client_widgets[master_key] = master_widget
                self.scroll_layout.insertWidget(0, master_widget)
            else:
                self.update_master_widget(self.client_widgets[master_key], master_data)
        elif master_key in self.client_widgets:
            widget = self.client_widgets.pop(master_key)
            self.scroll_layout.removeWidget(widget)
            widget.deleteLater()

        system_key = "__system__"
        system_data = self._collect_system_diag_data()
        if system_data is not None:
            insert_at = 1 if master_key in self.client_widgets else 0
            if system_key not in self.client_widgets:
                system_widget = self.create_system_widget(system_data)
                self.client_widgets[system_key] = system_widget
                self.scroll_layout.insertWidget(insert_at, system_widget)
            else:
                self.update_system_widget(self.client_widgets[system_key], system_data)
        elif system_key in self.client_widgets:
            widget = self.client_widgets.pop(system_key)
            self.scroll_layout.removeWidget(widget)
            widget.deleteLater()
        
        # Remove old client widgets
        for client_id, widget in list(self.client_widgets.items()):
            if client_id in (master_key, system_key):
                continue
            if client_id not in client_data:
                self.scroll_layout.removeWidget(widget)
                widget.deleteLater()
                del self.client_widgets[client_id]
        
        # Add/update client widgets (exclude master TCP id — shown as dedicated card)
        master_cid = getattr(self.parent, "master_client_id", None)
        for client_id, data in client_data.items():
            if master_cid and client_id == master_cid:
                continue
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

    def _collect_master_diag_data(self):
        if not hasattr(self.parent, "master_client_id"):
            return None
        pkt = getattr(self.parent, "latest_master_summary", None)
        master_cid = getattr(self.parent, "master_client_id", None)
        online = bool(pkt is not None and getattr(self.parent, "is_master_online", lambda: False)())
        link_only = bool(master_cid) and not online
        faults = []
        dm = getattr(self.parent, "diagnostics_manager", None)
        if dm is not None:
            faults = sorted((dm.active_faults.get("master", {}) or {}).keys())
        if not (master_cid or pkt is not None or faults or getattr(self.parent, "_last_master_ip", "")):
            return None
        from core.master_summary import format_io_brief, format_sensor_mode_brief
        from core.translation import TranslationManager
        try:
            lang = TranslationManager().get_language()
        except Exception:
            lang = "zh"
        ir_installed = bool(getattr(getattr(self.parent, "config", None), "ir_installed", True))
        _brief = getattr(self.parent, "_io_brief", None)
        if pkt is not None and callable(_brief):
            try:
                io_text = _brief(pkt, lang, beam_detail="always")
            except Exception:
                io_text = format_io_brief(pkt, lang, ir_installed=ir_installed, beam_detail="always")
        else:
            io_text = (
                format_io_brief(pkt, lang, ir_installed=ir_installed, beam_detail="always") if pkt is not None else "--"
            )
        sensor_brief = "--"
        if pkt is not None:
            _sup = getattr(self.parent, "_occupancy_gate_suppressed", None)
            ov = 2 if callable(_sup) and _sup() else None
            sensor_brief = format_sensor_mode_brief(pkt, lang=lang, mode_override=ov)
        l2_time = "--"
        if pkt is not None:
            rx = float(getattr(pkt, "received_at", 0) or 0)
            if rx > 0:
                l2_time = datetime.fromtimestamp(rx).strftime("%H:%M:%S")
        ip = "--"
        getter = getattr(self.parent, "get_master_display_ip", None)
        if callable(getter):
            ip = getter() or "--"
        elif master_cid and hasattr(self.parent, "_extract_client_ip"):
            ip = self.parent._extract_client_ip(master_cid) or "--"
        return {
            "client_id": master_cid or "master",
            "online": online,
            "link_only": link_only,
            "master_id": ip,
            "decision": getattr(pkt, "decision_result", None) if pkt is not None else None,
            "decision_text": (
                pkt.decision_detail_text(lang) if pkt is not None else None
            ),
            "ir_installed": ir_installed,
            "ir_degraded": bool(getattr(pkt, "ir_degraded", False)) if pkt is not None else False,
            "sensor_brief": sensor_brief,
            "sensor_unconfigured": bool(
                pkt is not None and int(pkt.sensor_mode_code()) == 2
            ),
            "hit_mask": int(getattr(pkt, "hit_probe_mask", 0) or 0) if pkt is not None else 0,
            "online_mask": int(getattr(pkt, "online_mask", 0) or 0) if pkt is not None else 0,
            "io_text": io_text,
            "l2_time": l2_time,
            "faults": faults,
        }

    def _collect_system_diag_data(self):
        dm = getattr(self.parent, "diagnostics_manager", None)
        if dm is None:
            return None
        codes = sorted((dm.active_faults.get("system", {}) or {}).keys())
        if not codes:
            return None
        fmt = getattr(self.parent, "format_fault_diag_message", None)
        lines = []
        for code in codes:
            lines.append(fmt("system", code) if fmt else str(code))
        return {"faults": lines}

    def create_system_widget(self, data: dict) -> QFrame:
        from core.translation import _t
        widget = QFrame()
        widget.setMinimumHeight(88)
        widget.setMaximumHeight(120)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setStyleSheet(self._diag_card_qss())
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(4)
        title = QLabel(_t("system_diag_title"))
        title.setStyleSheet(self._diag_style("title"))
        layout.addWidget(title)
        fault_label = QLabel("")
        fault_label.setWordWrap(True)
        fault_label.setStyleSheet(self._diag_style("faults", "#ffb74d"))
        layout.addWidget(fault_label)
        widget.data_labels = {"title": title, "faults": fault_label}
        self.update_system_widget(widget, data)
        return widget

    def update_system_widget(self, widget: QFrame, data: dict):
        from core.translation import _t
        labels = widget.data_labels
        labels["title"].setText(_t("system_diag_title"))
        faults = data.get("faults", []) or []
        if faults:
            labels["faults"].setText(_t("probe_faults_active", faults="  |  ".join(faults)))
            labels["faults"].setStyleSheet(self._diag_style("faults", "#ffb74d"))
        else:
            labels["faults"].setText(_t("system_diag_faults_normal"))
            labels["faults"].setStyleSheet(self._diag_style("faults", "#4caf50"))

    def create_master_widget(self, data: dict) -> QFrame:
        from core.translation import _t
        widget = QFrame()
        widget.setMinimumHeight(140)
        widget.setMaximumHeight(160)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setStyleSheet(self._diag_card_qss())
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        left = QVBoxLayout()
        left.setSpacing(3)
        title = QLabel("")
        title.setStyleSheet(self._diag_style("title"))
        left.addWidget(title)
        client_id_label = QLabel("")
        client_id_label.setStyleSheet(self._diag_style("title"))
        client_id_label.hide()
        left.addWidget(client_id_label)
        link_label = QLabel("")
        link_label.setStyleSheet(self._diag_style("alarm", "#4caf50"))
        left.addWidget(link_label)
        fault_label = QLabel("")
        fault_label.setWordWrap(True)
        fault_label.setStyleSheet(self._diag_style("faults", "#4caf50"))
        left.addWidget(fault_label)
        left.addStretch()
        layout.addLayout(left)

        right = QGridLayout()
        right.setHorizontalSpacing(20)
        right.setVerticalSpacing(5)
        key_style = self._diag_style("key")
        val_style = self._diag_style("val")
        key2_style = self._diag_style("key2")
        val2_style = self._diag_style("val2")

        decision_key = QLabel(_t("master_diag_decision_key"))
        decision_key.setStyleSheet(key_style)
        decision_label = QLabel("--")
        decision_label.setStyleSheet(val_style)
        right.addWidget(decision_key, 0, 0)
        right.addWidget(decision_label, 0, 1)

        mode_key = QLabel(_t("master_diag_mode_key"))
        mode_key.setStyleSheet(key_style)
        mode_label = QLabel("--")
        mode_label.setStyleSheet(val_style)
        right.addWidget(mode_key, 1, 0)
        right.addWidget(mode_label, 1, 1)

        hit_key = QLabel(_t("master_diag_hit_key"))
        hit_key.setStyleSheet(key_style)
        hit_label = QLabel("--")
        hit_label.setStyleSheet(val_style)
        right.addWidget(hit_key, 2, 0)
        right.addWidget(hit_label, 2, 1)

        online_key = QLabel(_t("master_diag_online_key"))
        online_key.setStyleSheet(key2_style)
        online_label = QLabel("--")
        online_label.setStyleSheet(val2_style)
        right.addWidget(online_key, 0, 2)
        right.addWidget(online_label, 0, 3)

        io_key = QLabel(_t("master_diag_io_key"))
        io_key.setStyleSheet(key_style)
        io_label = QLabel("--")
        io_label.setStyleSheet(val_style)
        io_label.setWordWrap(True)
        right.addWidget(io_key, 1, 2)
        right.addWidget(io_label, 1, 3)

        l2_key = QLabel(_t("master_diag_l2_key"))
        l2_key.setStyleSheet(key2_style)
        l2_label = QLabel("--")
        l2_label.setStyleSheet(val2_style)
        right.addWidget(l2_key, 2, 2)
        right.addWidget(l2_label, 2, 3)

        layout.addLayout(right)

        widget.data_labels = {
            "title": title,
            "client_id": client_id_label,
            "link": link_label,
            "faults": fault_label,
            "decision": decision_label,
            "mode": mode_label,
            "hit": hit_label,
            "online_mask": online_label,
            "io": io_label,
            "l2_time": l2_label,
            "decision_key": decision_key,
            "mode_key": mode_key,
            "hit_key": hit_key,
            "online_key": online_key,
            "io_key": io_key,
            "l2_key": l2_key,
        }
        self.update_master_widget(widget, data)
        return widget

    def update_master_widget(self, widget: QFrame, data: dict):
        from core.translation import _t
        labels = widget.data_labels
        ip_text = _t("master_diag_id", id=data.get("master_id") or "--")
        labels["title"].setText(ip_text)
        labels["title"].setStyleSheet(self._diag_style("title"))
        labels["client_id"].setText(ip_text)
        labels["client_id"].hide()
        if "decision_key" in labels:
            labels["decision_key"].setText(_t("master_diag_decision_key"))
            labels["mode_key"].setText(_t("master_diag_mode_key"))
            labels["hit_key"].setText(_t("master_diag_hit_key"))
            labels["online_key"].setText(_t("master_diag_online_key"))
            if "io_key" in labels:
                labels["io_key"].setText(_t("master_diag_io_key"))
                labels["l2_key"].setText(_t("master_diag_l2_key"))

        if data.get("online"):
            link_text = _t("master_online")
            link_color = "#4caf50"
        elif data.get("link_only"):
            link_text = _t("master_l2_invalid")
            link_color = "#ff9800"
        else:
            link_text = _t("master_offline")
            link_color = "#f44336"
        labels["link"].setText(_t("master_diag_link", status=link_text))
        labels["link"].setStyleSheet(self._diag_style("alarm", link_color))

        decision_text = data.get("decision_text") or "--"
        if data.get("decision") is None:
            decision_text = "--"
        if "hit" in labels:
            labels["decision"].setText(str(decision_text))
        else:
            # legacy single-line widgets
            labels["decision"].setText(_t("master_diag_decision", decision=decision_text))

        if data.get("link_only"):
            mode_text = _t("master_mode_invalid_l2")
        elif data.get("sensor_brief") and data.get("sensor_brief") != "--":
            mode_text = str(data.get("sensor_brief"))
        elif data.get("ir_degraded"):
            mode_text = _t("master_mode_degraded")
        else:
            mode_text = _t("master_mode_normal")
        if "hit" in labels:
            labels["mode"].setText(mode_text)
            labels["hit"].setText("0x%04X" % int(data.get("hit_mask", 0) or 0))
            labels["online_mask"].setText("0x%04X" % int(data.get("online_mask", 0) or 0))
            if "io" in labels:
                labels["io"].setText(str(data.get("io_text") or "--"))
                labels["l2_time"].setText(str(data.get("l2_time") or "--"))
        else:
            labels["mode"].setText(_t("master_diag_mode", mode=mode_text))
            if "masks" in labels:
                labels["masks"].setText(
                    _t(
                        "master_diag_masks",
                        hit=int(data.get("hit_mask", 0)),
                        online=int(data.get("online_mask", 0)),
                    )
                )

        faults = data.get("faults", []) or []
        if faults:
            fmt = getattr(self.parent, "format_fault_diag_message", None)
            shown = ", ".join(fmt("master", c) if fmt else str(c) for c in faults)
            labels["faults"].setText(_t("master_diag_faults_active", faults=shown))
            labels["faults"].setStyleSheet(self._diag_style("faults", "#ffb74d"))
        else:
            labels["faults"].setText(_t("master_diag_faults_normal"))
            labels["faults"].setStyleSheet(self._diag_style("faults", "#4caf50"))

    def create_client_widget(self, client_id: str, data: dict) -> QFrame:
        """Create a widget for displaying client information"""
        from core.translation import _t
        widget = QFrame()
        widget.setMinimumHeight(140)
        widget.setMaximumHeight(160)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setStyleSheet(self._diag_card_qss())
        
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        
        # Client ID and status
        left_layout = QVBoxLayout()
        left_layout.setSpacing(3)
        
        client_id_label = QLabel(_t("probe_id", id=client_id))
        client_id_label.setStyleSheet(self._diag_style("title"))
        left_layout.addWidget(client_id_label)
        
        # Last update time
        last_update = data.get('last_update', 0)
        time_diff = time.time() - last_update
        status_color = "#4caf50" if time_diff < 5 else "#ff9800" if time_diff < 15 else "#f44336"
        status_text = _t("status_active") if time_diff < 5 else _t("status_idle") if time_diff < 15 else _t("status_inactive")
        
        status_label = QLabel(_t("probe_status", status=status_text))
        status_label.setStyleSheet(self._diag_style("status", status_color))
        left_layout.addWidget(status_label)
        
        # Alarm status
        alarm_status = data.get('alarm', False)
        alarm_label = QLabel(_t("probe_alarm_active") if alarm_status else _t("probe_alarm_normal"))
        alarm_label.setStyleSheet(self._diag_style("alarm", "#ff4444" if alarm_status else "#4caf50"))
        left_layout.addWidget(alarm_label)

        # Faults status
        faults_label = QLabel(_t("probe_faults_normal"))
        faults_label.setStyleSheet(self._diag_style("faults", "#4caf50"))
        left_layout.addWidget(faults_label)
        
        left_layout.addStretch()
        layout.addLayout(left_layout)
        
        # Data display
        data_layout = QGridLayout()
        data_layout.setHorizontalSpacing(20)
        data_layout.setVerticalSpacing(5)
        key_style = self._diag_style("key")
        val_style = self._diag_style("val")
        key2_style = self._diag_style("key2")
        val2_style = self._diag_style("val2")
        
        # Count rate
        count_rate_label = QLabel(_t("label_rates"))
        count_rate_label.setStyleSheet(key_style)
        data_layout.addWidget(count_rate_label, 0, 0)
        
        count_rate_value = QLabel(f"{data.get('rates', 0)} cps")
        count_rate_value.setStyleSheet(val_style)
        data_layout.addWidget(count_rate_value, 0, 1)
        
        # Temperature
        temp_label = QLabel(_t("label_temp"))
        temp_label.setStyleSheet(key_style)
        data_layout.addWidget(temp_label, 1, 0)
        
        temp_value = QLabel(f"{data.get('temp', 0):.1f} " + chr(176) + "C")
        temp_value.setStyleSheet(val_style)
        data_layout.addWidget(temp_value, 1, 1)
        
        # High Voltage
        hv_label = QLabel(_t("label_hv"))
        hv_label.setStyleSheet(key_style)
        data_layout.addWidget(hv_label, 2, 0)
        
        hv_value = QLabel(f"{data.get('hv', 0):.1f} V")
        hv_value.setStyleSheet(val_style)
        data_layout.addWidget(hv_value, 2, 1)
        
        # Product ID and Sensitivity
        product_label = QLabel(_t("label_product_id"))
        product_label.setStyleSheet(key2_style)
        data_layout.addWidget(product_label, 0, 2)
        
        product_value = QLabel(f"{data.get('product_id', 0)}")
        product_value.setStyleSheet(val2_style)
        data_layout.addWidget(product_value, 0, 3)
        
        sensitivity_label = QLabel(_t("label_sensitivity"))
        sensitivity_label.setStyleSheet(key2_style)
        data_layout.addWidget(sensitivity_label, 1, 2)
        
        sensitivity_value = QLabel(f"{data.get('sensitivity', 0)}")
        sensitivity_value.setStyleSheet(val2_style)
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
        labels['status'].setStyleSheet(self._diag_style("status", status_color))
        
        # Update alarm status
        alarm_status = data.get('alarm', False)
        labels['alarm'].setText(_t("probe_alarm_active") if alarm_status else _t("probe_alarm_normal"))
        labels['alarm'].setStyleSheet(
            self._diag_style("alarm", "#ff4444" if alarm_status else "#4caf50")
        )

        # Update faults status
        client_id = data.get('client_id')
        if hasattr(self.parent, 'diagnostics_manager') and client_id:
            active_faults = self.parent.diagnostics_manager.active_faults.get(client_id, {})
            if active_faults:
                fmt = getattr(self.parent, "format_fault_diag_message", None)
                if fmt:
                    faults_str = ", ".join(fmt(client_id, c) for c in active_faults.keys())
                else:
                    faults_str = ", ".join(active_faults.keys())
                labels['faults'].setText(_t("probe_faults_active", faults=faults_str))
                labels['faults'].setStyleSheet(self._diag_style("faults", "#ff9800"))
            else:
                labels['faults'].setText(_t("probe_faults_normal"))
                labels['faults'].setStyleSheet(self._diag_style("faults", "#4caf50"))

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
