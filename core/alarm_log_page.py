# -*- coding: utf-8 -*-
"""
Alarm Log Page
For displaying alarm event records and statistics
"""

import time
from datetime import datetime
from typing import List

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QScrollArea, QSizePolicy, QTabWidget
)

from core.alarm_logger import (
    get_alarm_logger, AlarmEvent, is_system_event_type,
)


def format_alarm_event_client(event: AlarmEvent) -> str:
    from core.translation import _t
    t = str(getattr(event, "alarm_type", "") or "")
    if t == "MasterFault":
        return _t("log_master_client")
    if t == "ChannelMatch":
        msg = str(getattr(event, "message", "") or "")
        probes = ""
        if " | " in msg:
            probes = msg.split(" | ", 1)[0].strip()
        if probes in ("探头未标明", "Probe not identified", _t("log_hit_probes_none")):
            probes = ""
        if probes:
            return probes
        cid = str(getattr(event, "client_id", "") or "")
        if cid == "master_channel":
            cps = 0
            try:
                cps = int(float(getattr(event, "count_rate", 0) or 0))
            except (TypeError, ValueError):
                cps = 0
            if cps > 0:
                return "%s %d cps" % (_t("log_channel_device"), cps)
            return _t("log_channel_device")
        return cid or _t("log_master_client")
    return str(getattr(event, "client_id", "") or "")


def format_alarm_event_type(event: AlarmEvent) -> str:
    from core.translation import _t
    t = str(getattr(event, "alarm_type", "") or "")
    if t == "MasterFault":
        return _t("log_type_system_comm")
    if t == "ChannelMatch":
        return _t("log_type_channel_match")
    if t in ("Radiation", "radiation", "Alarm"):
        return _t("log_type_radiation")
    return t or "--"


def format_alarm_event_status(event: AlarmEvent) -> str:
    from core.translation import _t
    active = bool(getattr(event, "alarm_status", False))
    if is_system_event_type(getattr(event, "alarm_type", "")):
        return _t("log_status_link_down") if active else _t("log_status_link_restored")
    return _t("log_status_active") if active else _t("log_status_cleared")


def format_alarm_event_message(event: AlarmEvent) -> str:
    t = str(getattr(event, "alarm_type", "") or "")
    msg = str(getattr(event, "message", "") or "")
    if t == "ChannelMatch":
        if " | " in msg:
            return msg.split(" | ", 1)[1].strip()
        return msg
    if t != "MasterFault":
        return msg
    client_id = str(getattr(event, "client_id", "") or "")
    if client_id.startswith("master_fault_"):
        code = client_id.replace("master_fault_", "", 1)
        if code and code not in msg:
            msg = ("%s %s" % (code, msg)).strip()
    return msg


def format_alarm_fault_code(event: AlarmEvent) -> str:
    client_id = str(getattr(event, "client_id", "") or "")
    if client_id.startswith("master_fault_"):
        return client_id.replace("master_fault_", "", 1)
    msg = str(getattr(event, "message", "") or "")
    for tok in msg.split():
        if tok.startswith("M") and len(tok) == 4 and tok[1:].isdigit():
            return tok
    return "--"


class AlarmLogPage(QWidget):
    """Alarm log page"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # addWidget 到 QStackedWidget 后 self.parent() 会变，须保留主窗引用
        self.main_window = parent
        self.alarm_logger = get_alarm_logger()
        self.setup_ui()
        self.setup_timer()

    def _format_event_client(self, event: AlarmEvent) -> str:
        return format_alarm_event_client(event)

    def _format_event_type(self, event: AlarmEvent) -> str:
        return format_alarm_event_type(event)

    def _format_event_status(self, event: AlarmEvent) -> str:
        return format_alarm_event_status(event)

    def _format_event_message(self, event: AlarmEvent) -> str:
        return format_alarm_event_message(event)
    
    def setup_ui(self):
        """Setup UI interface"""
        from core.translation import _t
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        from core.ui_tokens import PAGE_TITLE_QSS
        self.title_label = QLabel(_t("log_title"))
        self.title_label.setStyleSheet(PAGE_TITLE_QSS)
        layout.addWidget(self.title_label)
        
        # Statistics cards and control buttons row
        stats_buttons_layout = QHBoxLayout()
        stats_buttons_layout.setSpacing(15)
        
        # Statistics cards：与概览页状态卡同风格（渐变底 + 状态胶囊 + 底条）
        stats_cards_layout = QHBoxLayout()
        stats_cards_layout.setSpacing(10)

        self.active_alarms_card = self.create_stat_card(
            _t("log_active_alarms"), "0", "#4caf50", "active_alarms"
        )
        stats_cards_layout.addWidget(self.active_alarms_card)

        self.today_events_card = self.create_stat_card(
            _t("log_today_events"), "0", "#26c6da", "today_events"
        )
        stats_cards_layout.addWidget(self.today_events_card)

        self.last_alarm_card = self.create_stat_card(
            _t("log_last_alarm"), _t("log_last_alarm_none"), "#90a4ae", "last_alarm"
        )
        stats_cards_layout.addWidget(self.last_alarm_card)

        # 右侧辅助操作：日志目录/清除显示仅管理员
        buttons_wrap = QWidget()
        buttons_wrap.setFixedWidth(112)
        buttons_layout = QVBoxLayout(buttons_wrap)
        buttons_layout.setSpacing(6)
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        self.open_folder_btn = QPushButton(_t("btn_open_log_folder"))
        self.open_folder_btn.setFixedHeight(44)
        self.open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: #dddddd;
                border: 1px solid #555555;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 8px;
            }
            QPushButton:pressed { background-color: #2f2f2f; }
        """)
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        buttons_layout.addWidget(self.open_folder_btn)

        self.clear_btn = QPushButton(_t("btn_clear_log"))
        self.clear_btn.setFixedHeight(44)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 0 8px;
            }
            QPushButton:pressed { background-color: #b71c1c; }
        """)
        self.clear_btn.clicked.connect(self.clear_alarm_logs)
        buttons_layout.addWidget(self.clear_btn)
        buttons_layout.addStretch(1)

        stats_buttons_layout.addLayout(stats_cards_layout, 1)
        stats_buttons_layout.addWidget(buttons_wrap, 0)
        layout.addLayout(stats_buttons_layout)
        self.update_auth_controls()
        
        # Pagination: large prev/next + page label (fixed page size)
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        page_btn_style = """
            QPushButton {
                background-color: #455a64;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 0 18px;
                min-width: 110px;
            }
            QPushButton:pressed { background-color: #37474f; }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """

        self.prev_page_btn = QPushButton(_t("btn_prev"))
        self.prev_page_btn.setFixedHeight(44)
        self.prev_page_btn.setStyleSheet(page_btn_style)
        self.prev_page_btn.clicked.connect(self.go_to_previous_page)
        pagination_layout.addWidget(self.prev_page_btn)

        self.total_pages_label = QLabel(_t("page_info", curr=0, total=0))
        self.total_pages_label.setAlignment(Qt.AlignCenter)
        self.total_pages_label.setStyleSheet(
            "color: #dddddd; font-size: 14px; font-weight: bold; min-width: 120px;"
        )
        pagination_layout.addWidget(self.total_pages_label, 1)

        self.next_page_btn = QPushButton(_t("btn_next"))
        self.next_page_btn.setFixedHeight(44)
        self.next_page_btn.setStyleSheet(page_btn_style)
        self.next_page_btn.clicked.connect(self.go_to_next_page)
        pagination_layout.addWidget(self.next_page_btn)

        layout.addLayout(pagination_layout)

        # Initialize pagination variables
        self.current_page = 1
        self.page_size = 15
        self.total_events = 0
        self.total_pages = 0
        self._log_category = "radiation"  # radiation | system

        # Tabs: 辐射报警 vs 系统/通信（工业分层，不混字段）
        self.log_tabs = QTabWidget()
        self.log_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 8px;
                background: #1a1a1a;
                top: -1px;
            }
            QTabBar::tab {
                background: #2a2a2a;
                color: #bbbbbb;
                padding: 10px 18px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 13px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #3a3a3a;
                color: #ffffff;
                border-bottom: 2px solid #26c6da;
            }
        """)
        self.log_tabs.currentChanged.connect(self._on_log_tab_changed)

        self.table_widget = self._make_log_table(system=False)
        self.system_table_widget = self._make_log_table(system=True)

        rad_page = QWidget()
        rad_lay = QVBoxLayout(rad_page)
        rad_lay.setContentsMargins(8, 8, 8, 8)
        rad_scroll = self._wrap_table_scroll(self.table_widget)
        rad_lay.addWidget(rad_scroll)
        self.log_tabs.addTab(rad_page, _t("log_tab_radiation"))

        sys_page = QWidget()
        sys_lay = QVBoxLayout(sys_page)
        sys_lay.setContentsMargins(8, 8, 8, 8)
        sys_scroll = self._wrap_table_scroll(self.system_table_widget)
        sys_lay.addWidget(sys_scroll)
        self.log_tabs.addTab(sys_page, _t("log_tab_system"))

        layout.addWidget(self.log_tabs, 1)

        self.setLayout(layout)

        # Initial refresh
        self.refresh_display()

    def _make_log_table(self, system: bool = False) -> QTableWidget:
        from core.translation import _t
        table = QTableWidget()
        if system:
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels([
                _t("header_time"), _t("header_fault_code"), _t("header_link_status"),
                _t("header_outage_duration"), _t("header_message"),
            ])
        else:
            table.setColumnCount(7)
            table.setHorizontalHeaderLabels([
                _t("header_time"), _t("header_client"), _t("header_type"), _t("header_status"),
                _t("header_rates"), _t("header_duration"), _t("header_message"),
            ])
        table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #f0f0f0;
                border: none;
                gridline-color: #444444;
                font-size: 13px;
                alternate-background-color: #222222;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #444444;
            }
            QTableWidget::item:selected {
                background-color: #2a5caa;
                color: white;
                font-weight: bold;
            }
            QHeaderView::section {
                background-color: #151515;
                color: #e0e0e0;
                padding: 8px 6px;
                border: none;
                border-bottom: 2px solid #444444;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        header = table.horizontalHeader()
        cols = table.columnCount()
        for i in range(cols - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(cols - 1, QHeaderView.Stretch)
        header.setMinimumSectionSize(56)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setMinimumHeight(200)
        return table

    def _wrap_table_scroll(self, table: QTableWidget) -> QScrollArea:
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
        table_container = QWidget()
        table_container_layout = QVBoxLayout(table_container)
        table_container_layout.setContentsMargins(0, 0, 0, 0)
        table_container_layout.addWidget(table)
        scroll_area.setWidget(table_container)
        return scroll_area

    def _on_log_tab_changed(self, index: int):
        self._log_category = "system" if int(index) == 1 else "radiation"
        self.current_page = 1
        self._page_table_sig = None
        self.update_table_with_pagination()

    def _active_table(self) -> QTableWidget:
        if self._log_category == "system":
            return self.system_table_widget
        return self.table_widget

    def create_stat_card(self, title: str, value: str, color: str, card_id: str = "") -> QFrame:
        """概览同款状态卡：深色渐变、标题灰、数值胶囊、底部色条。"""
        card = QFrame()
        card.setObjectName("logStatCard")
        card.setMinimumHeight(96)
        card.setMaximumHeight(110)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setProperty("accent", color)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                background: transparent;
            }
        """)
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setWordWrap(True)
        layout.addWidget(value_label, 1)

        bar = QFrame()
        bar.setFixedHeight(2)
        bar.setStyleSheet(
            "QFrame { background-color: %s; border-radius: 1px; }" % color
        )
        layout.addWidget(bar)

        card.setLayout(layout)
        self._paint_stat_card(card, title_label, value_label, bar, color, card_id)

        if card_id == "today_events":
            self.today_events_label = value_label
            self.today_events_title = title_label
            self.today_events_bar = bar
        elif card_id == "active_alarms":
            self.active_alarms_label = value_label
            self.active_alarms_title = title_label
            self.active_alarms_bar = bar
        elif card_id == "last_alarm":
            self.last_alarm_label = value_label
            self.last_alarm_title = title_label
            self.last_alarm_bar = bar

        return card

    def _paint_stat_card(self, card, title_label, value_label, bar, color: str, card_id: str = ""):
        """刷新统计卡：纯色数值字 + 底条，与概览卡一致（无胶囊框）。"""
        card.setStyleSheet(f"""
            QFrame#logStatCard {{
                background-color: #2a2a2a;
                border-radius: 10px;
                border: none;
            }}
            QFrame#logStatCard QLabel {{
                background: transparent;
                border: none;
            }}
        """)
        # 有活动报警时整卡细描边提示
        if card_id == "active_alarms" and color.lower() in ("#ff4444", "#f44336", "#ef4444"):
            card.setStyleSheet(f"""
                QFrame#logStatCard {{
                    background-color: #2a2a2a;
                    border-radius: 10px;
                    border: 2px solid {color};
                }}
                QFrame#logStatCard QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

        title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
        """)

        font_size = "14px" if card_id == "last_alarm" else "22px"
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: {font_size};
                font-weight: bold;
                margin-top: 2px;
                background: transparent;
                border: none;
            }}
        """)
        bar.setObjectName("cardAccentBar")
        bar.setStyleSheet(
            "QFrame#cardAccentBar { background-color: %s; border: none; border-radius: 1px; }" % color
        )
        card.setProperty("accent", color)

    def setup_timer(self):
        """Setup timer for auto-refresh with optimized frequency"""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_display)
        # Optimized: Increase refresh interval from 2 seconds to 3 seconds
        # This reduces UI updates by 33% while still providing timely updates
        self.refresh_timer.start(3000)  # Refresh every 3 seconds (was 2 seconds)
    
    def refresh_display(self):
        """Refresh display with pagination support"""
        if not self.isVisible():
            return
        from core.translation import _t
        stats = self.alarm_logger.get_statistics()

        active_n = int(stats.get('active_alarms', 0) or 0)
        today_n = int(stats.get('today_events', 0) or 0)
        self.active_alarms_label.setText(str(active_n))
        self.today_events_label.setText(str(today_n))

        # 活动报警：有则红，无则绿（正常）
        active_color = "#ff4444" if active_n > 0 else "#4caf50"
        self._paint_stat_card(
            self.active_alarms_card,
            self.active_alarms_title,
            self.active_alarms_label,
            self.active_alarms_bar,
            active_color,
            "active_alarms",
        )

        # 今日事件：青色信息态
        self._paint_stat_card(
            self.today_events_card,
            self.today_events_title,
            self.today_events_label,
            self.today_events_bar,
            "#26c6da",
            "today_events",
        )

        last = stats.get('last_event')
        if last is None:
            self.last_alarm_label.setText(_t("log_last_alarm_none"))
            last_color = "#90a4ae"
        else:
            tstr = datetime.fromtimestamp(last.timestamp).strftime('%H:%M:%S')
            typ = self._format_event_type(last)
            st = self._format_event_status(last)
            self.last_alarm_label.setText("%s\n%s · %s" % (tstr, typ, st))
            last_color = "#ff4444" if bool(getattr(last, "alarm_status", False)) else "#ff9800"

        self._paint_stat_card(
            self.last_alarm_card,
            self.last_alarm_title,
            self.last_alarm_label,
            self.last_alarm_bar,
            last_color,
            "last_alarm",
        )

        self.update_table_with_pagination()
        if hasattr(self, "log_tabs"):
            sys_n = int(stats.get("active_system", 0) or 0)
            sys_title = _t("log_tab_system")
            if sys_n > 0:
                sys_title = "%s (%d)" % (sys_title, sys_n)
            self.log_tabs.setTabText(1, sys_title)

    def update_table(self):
        """Legacy full-table refresh (radiation only). Prefer pagination path."""
        events = self.alarm_logger.get_recent_events(100, category="radiation")
        
        # Performance optimization: Only update if data has changed
        current_event_count = len(events)
        if hasattr(self, '_last_event_count') and self._last_event_count == current_event_count:
            # No new events, skip full table update to reduce CPU usage
            return
        
        # Store current event count for next comparison
        self._last_event_count = current_event_count
        
        # Performance optimization: Disable visual updates during table population
        self.table_widget.setUpdatesEnabled(False)
        
        try:
            # Set row count
            self.table_widget.setRowCount(current_event_count)
            
            # Fill data (display from newest to oldest)
            for row, event in enumerate(reversed(events)):
                # Time
                time_str = datetime.fromtimestamp(event.timestamp).strftime('%Y-%m-%d %H:%M:%S')
                if row < self.table_widget.rowCount():
                    # Reuse existing items if possible
                    if self.table_widget.item(row, 0):
                        self.table_widget.item(row, 0).setText(time_str)
                    else:
                        time_item = QTableWidgetItem(time_str)
                        time_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 0, time_item)
                
                display_client = self._format_event_client(event)
                display_type = self._format_event_type(event)
                display_status = self._format_event_status(event)
                display_message = self._format_event_message(event)

                # Client ID
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 1):
                        self.table_widget.item(row, 1).setText(display_client)
                    else:
                        client_item = QTableWidgetItem(display_client)
                        client_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 1, client_item)
                
                # Alarm type
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 2):
                        self.table_widget.item(row, 2).setText(display_type)
                    else:
                        type_item = QTableWidgetItem(display_type)
                        type_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 2, type_item)
                
                # Status
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 3):
                        self.table_widget.item(row, 3).setText(display_status)
                        if event.alarm_status:
                            self.table_widget.item(row, 3).setForeground(Qt.red)
                        else:
                            self.table_widget.item(row, 3).setForeground(Qt.green)
                    else:
                        status_item = QTableWidgetItem(display_status)
                        status_item.setTextAlignment(Qt.AlignCenter)
                        if event.alarm_status:
                            status_item.setForeground(Qt.red)
                        else:
                            status_item.setForeground(Qt.green)
                        self.table_widget.setItem(row, 3, status_item)
                
                # Peak rate (ACTIVE: trigger; INACTIVE: peak during alarm)
                peak_rate = getattr(event, 'peak_count_rate', event.count_rate)
                peak_rate_text = f"{peak_rate:.1f}"
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 4):
                        self.table_widget.item(row, 4).setText(peak_rate_text)
                    else:
                        peak_rate_item = QTableWidgetItem(peak_rate_text)
                        peak_rate_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 4, peak_rate_item)
                
                # Trigger count rate
                trigger_count_rate_text = f"{event.trigger_count_rate:.1f}"
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 5):
                        self.table_widget.item(row, 5).setText(trigger_count_rate_text)
                    else:
                        trigger_count_rate_item = QTableWidgetItem(trigger_count_rate_text)
                        trigger_count_rate_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 5, trigger_count_rate_item)
                
                # Temperature
                temp_text = f"{event.temperature:.1f}"
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 6):
                        self.table_widget.item(row, 6).setText(temp_text)
                    else:
                        temp_item = QTableWidgetItem(temp_text)
                        temp_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 6, temp_item)
                
                # High voltage
                hv_text = f"{event.hv:.1f}"
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 7):
                        self.table_widget.item(row, 7).setText(hv_text)
                    else:
                        hv_item = QTableWidgetItem(hv_text)
                        hv_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 7, hv_item)
                
                # Duration
                duration_text = f"{event.duration:.3f}" if event.duration > 0 else ""
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 8):
                        self.table_widget.item(row, 8).setText(duration_text)
                    else:
                        duration_item = QTableWidgetItem(duration_text)
                        duration_item.setTextAlignment(Qt.AlignCenter)
                        self.table_widget.setItem(row, 8, duration_item)
                
                # Message
                if row < self.table_widget.rowCount():
                    if self.table_widget.item(row, 9):
                        self.table_widget.item(row, 9).setText(display_message)
                    else:
                        message_item = QTableWidgetItem(display_message)
                        self.table_widget.setItem(row, 9, message_item)
                        
        finally:
            # Re-enable visual updates
            self.table_widget.setUpdatesEnabled(True)
    
    def _host_window(self):
        host = getattr(self, "main_window", None)
        if host is not None and hasattr(host, "current_user"):
            return host
        w = self.parent()
        while w is not None:
            if hasattr(w, "current_user"):
                return w
            w = w.parent()
        return None

    def _is_admin_user(self) -> bool:
        try:
            from core.user_manager import UserRole
            host = self._host_window()
            user = getattr(host, "current_user", None) if host is not None else None
            return bool(
                isinstance(user, dict)
                and user.get("role") in (UserRole.ADMIN, UserRole.MAINTAINER)
            )
        except Exception:
            return False

    def update_auth_controls(self):
        """日志目录/清除显示仅管理员可见。"""
        is_admin = self._is_admin_user()
        if hasattr(self, "clear_btn"):
            self.clear_btn.setVisible(is_admin)
        if hasattr(self, "open_folder_btn"):
            self.open_folder_btn.setVisible(is_admin)

    def clear_alarm_logs(self):
        """Clear on-screen alarm records (Excel files kept)."""
        from core.translation import _t
        from core.industrial_dialogs import ask_confirm, show_warn

        if not self._is_admin_user():
            show_warn(
                self, _t("msg_clear_log_title"), _t("msg_clear_log_need_admin")
            )
            self.update_auth_controls()
            return

        if not ask_confirm(
            self,
            _t("msg_clear_log_title"),
            _t("msg_clear_log_text"),
            danger=True,
        ):
            return

        self.alarm_logger.clear_events()
        self.current_page = 1
        self.refresh_display()

    def open_log_folder(self):
        """Open the alarm Excel log folder in the system file manager."""
        from core.translation import _t
        from core.industrial_dialogs import show_warn
        import os
        import sys
        import subprocess
        from pathlib import Path

        if not self._is_admin_user():
            show_warn(
                self, _t("btn_open_log_folder"), _t("msg_open_log_need_admin")
            )
            self.update_auth_controls()
            return

        try:
            folder = Path(getattr(self.alarm_logger, "log_folder", "") or "")
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
            path = str(folder.resolve())
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            show_warn(self, _t("btn_open_log_folder"), _t("msg_open_log_fail"))

    def showEvent(self, event):
        """Show event with delayed refresh to improve page switching performance"""
        super().showEvent(event)
        self.update_auth_controls()
        # Use delayed refresh to avoid immediate heavy operations during page switch
        QTimer.singleShot(100, self.refresh_display)
    
    # Pagination methods
    def go_to_previous_page(self):
        """Go to previous page"""
        if self.current_page > 1:
            self.current_page -= 1
            self.update_table_with_pagination()
    
    def go_to_next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.update_table_with_pagination()
    
    def update_table_with_pagination(self):
        """Update active tab table with pagination (radiation or system)."""
        from core.translation import _t
        category = getattr(self, "_log_category", "radiation")
        all_events = self.alarm_logger.get_recent_events(1000, category=category)
        table = self._active_table()

        # Update pagination info
        self.total_events = len(all_events)
        self.total_pages = max(1, (self.total_events + self.page_size - 1) // self.page_size)

        # Ensure current page is valid
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        if self.current_page < 1:
            self.current_page = 1

        # Update pagination controls
        self.update_pagination_controls()

        # Calculate start and end indices for current page
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, self.total_events)

        # Get events for current page (newest first)
        page_events = list(reversed(all_events))[start_idx:end_idx]

        bar = table.verticalScrollBar()
        scroll_val = bar.value()
        if bar.isSliderDown():
            return
        page_key = (category, self.current_page)
        page_changed = getattr(self, "_shown_page", None) != page_key
        if page_changed:
            scroll_val = 0
        self._shown_page = page_key

        sig = (
            category,
            "empty-hint" if (category == "system" and not page_events) else "rows",
            tuple(
                (
                    getattr(ev, "timestamp", 0),
                    bool(ev.alarm_status),
                    str(getattr(ev, "message", "") or ""),
                    float(getattr(ev, "peak_count_rate", ev.count_rate) or 0),
                    float(getattr(ev, "duration", 0) or 0),
                )
                for ev in page_events
            ),
        )
        expected_rows = 1 if (category == "system" and not page_events) else len(page_events)
        if sig == getattr(self, "_page_table_sig", None) and table.rowCount() == expected_rows:
            return
        self._page_table_sig = sig

        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(page_events))
            if category == "system":
                if not page_events:
                    table.setRowCount(1)
                    hint = QTableWidgetItem(_t("log_system_empty_hint"))
                    hint.setForeground(Qt.gray)
                    table.setItem(0, 0, hint)
                    table.setSpan(0, 0, 1, table.columnCount())
                else:
                    table.clearSpans()
                    for row, event in enumerate(page_events):
                        time_str = datetime.fromtimestamp(event.timestamp).strftime('%m-%d %H:%M:%S')
                        time_item = QTableWidgetItem(time_str)
                        time_item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(row, 0, time_item)

                        code_item = QTableWidgetItem(format_alarm_fault_code(event))
                        code_item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(row, 1, code_item)

                        status_item = QTableWidgetItem(self._format_event_status(event))
                        status_item.setTextAlignment(Qt.AlignCenter)
                        if event.alarm_status:
                            status_item.setForeground(Qt.yellow)
                        else:
                            status_item.setForeground(Qt.green)
                        table.setItem(row, 2, status_item)

                        duration_text = f"{event.duration:.1f}" if event.duration > 0 else ""
                        duration_item = QTableWidgetItem(duration_text)
                        duration_item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(row, 3, duration_item)

                        table.setItem(row, 4, QTableWidgetItem(self._format_event_message(event)))
            else:
                table.clearSpans()
                for row, event in enumerate(page_events):
                    display_client = self._format_event_client(event)
                    display_type = self._format_event_type(event)
                    display_status = self._format_event_status(event)
                    display_message = self._format_event_message(event)

                    time_str = datetime.fromtimestamp(event.timestamp).strftime('%m-%d %H:%M:%S')
                    time_item = QTableWidgetItem(time_str)
                    time_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 0, time_item)

                    client_item = QTableWidgetItem(display_client)
                    client_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 1, client_item)

                    type_item = QTableWidgetItem(display_type)
                    type_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 2, type_item)

                    status_item = QTableWidgetItem(display_status)
                    status_item.setTextAlignment(Qt.AlignCenter)
                    if event.alarm_status:
                        status_item.setForeground(Qt.red)
                    else:
                        status_item.setForeground(Qt.green)
                    table.setItem(row, 3, status_item)

                    peak_rate = getattr(event, 'peak_count_rate', event.count_rate)
                    peak_rate_item = QTableWidgetItem(f"{peak_rate:.1f}")
                    peak_rate_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 4, peak_rate_item)

                    duration_text = f"{event.duration:.1f}" if event.duration > 0 else ""
                    duration_item = QTableWidgetItem(duration_text)
                    duration_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 5, duration_item)

                    table.setItem(row, 6, QTableWidgetItem(display_message))
        finally:
            table.setUpdatesEnabled(True)
            table.verticalScrollBar().setValue(scroll_val)
    
    def update_pagination_controls(self):
        """Update pagination control states"""
        from core.translation import _t
        self.total_pages_label.setText(_t("page_info", curr=self.current_page, total=self.total_pages))
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.title_label.setText(_t("log_title"))
        
        # Update stats cards titles
        if hasattr(self, "active_alarms_title"):
            self.active_alarms_title.setText(_t("log_active_alarms"))
        if hasattr(self, "today_events_title"):
            self.today_events_title.setText(_t("log_today_events"))
        if hasattr(self, "last_alarm_title"):
            self.last_alarm_title.setText(_t("log_last_alarm"))
        
        # Update buttons
        if hasattr(self, "open_folder_btn"):
            self.open_folder_btn.setText(_t("btn_open_log_folder"))
        if hasattr(self, "clear_btn"):
            self.clear_btn.setText(_t("btn_clear_log"))
        self.update_auth_controls()
        
        # Update pagination labels
        self.prev_page_btn.setText(_t("btn_prev"))
        self.next_page_btn.setText(_t("btn_next"))

        if hasattr(self, "log_tabs"):
            self.log_tabs.setTabText(0, _t("log_tab_radiation"))
            self.log_tabs.setTabText(1, _t("log_tab_system"))

        if hasattr(self, "table_widget"):
            self.table_widget.setHorizontalHeaderLabels([
                _t("header_time"), _t("header_client"), _t("header_type"), _t("header_status"),
                _t("header_rates"), _t("header_duration"), _t("header_message")
            ])
        if hasattr(self, "system_table_widget"):
            self.system_table_widget.setHorizontalHeaderLabels([
                _t("header_time"), _t("header_fault_code"), _t("header_link_status"),
                _t("header_outage_duration"), _t("header_message"),
            ])

        # Refresh display to update pagination info text
        self.refresh_display()
    
    
    def closeEvent(self, event):
        """Close event"""
        self.refresh_timer.stop()
        # 页面关闭时刷盘即可；写线程生命周期由主窗口 shutdown 管理
        try:
            self.alarm_logger.flush(timeout=3.0)
        except Exception:
            pass
        super().closeEvent(event)
