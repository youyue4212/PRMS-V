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
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit, QGroupBox,
    QGridLayout, QScrollArea, QSizePolicy, QComboBox, QLineEdit
)

from core.alarm_logger import get_alarm_logger, AlarmEvent


class AlarmLogPage(QWidget):
    """Alarm log page"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.alarm_logger = get_alarm_logger()
        self.setup_ui()
        self.setup_timer()

    def _format_event_client(self, event: AlarmEvent) -> str:
        from core.translation import _t
        if str(getattr(event, "alarm_type", "")) == "MasterFault":
            return _t("log_master_client")
        return str(getattr(event, "client_id", "") or "")

    def _format_event_type(self, event: AlarmEvent) -> str:
        from core.translation import _t
        if str(getattr(event, "alarm_type", "")) == "MasterFault":
            return _t("log_master_fault_type")
        return str(getattr(event, "alarm_type", "") or "")

    def _format_event_status(self, event: AlarmEvent) -> str:
        from core.translation import _t
        return _t("log_status_active") if bool(getattr(event, "alarm_status", False)) else _t("log_status_cleared")

    def _format_event_message(self, event: AlarmEvent) -> str:
        msg = str(getattr(event, "message", "") or "")
        if str(getattr(event, "alarm_type", "")) != "MasterFault":
            return msg
        client_id = str(getattr(event, "client_id", "") or "")
        if client_id.startswith("master_fault_"):
            code = client_id.replace("master_fault_", "", 1)
            if code and code not in msg:
                msg = ("%s %s" % (code, msg)).strip()
        return msg
    
    def setup_ui(self):
        """Setup UI interface"""
        from core.translation import _t
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        self.title_label = QLabel(_t("log_title"))
        self.title_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(self.title_label)
        
        # Statistics cards and control buttons row
        stats_buttons_layout = QHBoxLayout()
        stats_buttons_layout.setSpacing(15)
        
        # Statistics cards (left side)
        stats_cards_layout = QHBoxLayout()
        stats_cards_layout.setSpacing(10)
        
        # Total alarm events
        self.total_events_card = self.create_stat_card(_t("log_total_events"), "0", "#4caf50", "total_events")
        stats_cards_layout.addWidget(self.total_events_card)
        
        # Active alarms
        self.active_alarms_card = self.create_stat_card(_t("log_active_alarms"), "0", "#ff4444", "active_alarms")
        stats_cards_layout.addWidget(self.active_alarms_card)
        
        # Alarm types
        self.alarm_types_card = self.create_stat_card(_t("log_alarm_types"), "0", "#2196F3", "alarm_types")
        stats_cards_layout.addWidget(self.alarm_types_card)
        
        stats_buttons_layout.addLayout(stats_cards_layout)
        
        # Control buttons (right side) - more compact design
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(5)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        
        # Refresh button - smaller and more compact
        self.refresh_btn = QPushButton(_t("btn_refresh"))
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 10px;
                min-width: 80px;
            }
            QPushButton:pressed {
                background-color: #45a049;
            }
            QPushButton:hover {
                background-color: #5cb860;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_display)
        buttons_layout.addWidget(self.refresh_btn)
        
        # Clear records button
        self.clear_btn = QPushButton(_t("btn_clear_log"))
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 10px;
                min-width: 80px;
            }
            QPushButton:pressed {
                background-color: #cc3333;
            }
            QPushButton:hover {
                background-color: #ff6666;
            }
        """)
        self.clear_btn.clicked.connect(self.clear_alarm_logs)
        buttons_layout.addWidget(self.clear_btn)
        
        # Save to EXCEL button
        self.save_btn = QPushButton(_t("btn_save_excel"))
        self.save_btn.setFixedHeight(30)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: bold;
                padding: 0 10px;
                min-width: 80px;
            }
            QPushButton:pressed {
                background-color: #1976D2;
            }
            QPushButton:hover {
                background-color: #42a5f5;
            }
        """)
        self.save_btn.clicked.connect(self.save_to_excel)
        buttons_layout.addWidget(self.save_btn)
        
        stats_buttons_layout.addLayout(buttons_layout)
        layout.addLayout(stats_buttons_layout)
        
        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(10)
        
        # Page size selector
        self.page_size_label = QLabel(_t("page_size"))
        pagination_layout.addWidget(self.page_size_label)
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["10", "20", "50", "100"])
        self.page_size_combo.setCurrentText("20")
        self.page_size_combo.setFixedWidth(80)
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)
        
        # Total pages label
        self.total_pages_label = QLabel(_t("page_info", curr=0, total=0))
        self.total_pages_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        pagination_layout.addWidget(self.total_pages_label)
        
        # First page button
        self.first_page_btn = QPushButton(_t("btn_first"))
        self.first_page_btn.setFixedHeight(30)
        self.first_page_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                padding: 0 10px;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        self.first_page_btn.clicked.connect(self.go_to_first_page)
        pagination_layout.addWidget(self.first_page_btn)
        
        # Previous page button
        self.prev_page_btn = QPushButton(_t("btn_prev"))
        self.prev_page_btn.setFixedHeight(30)
        self.prev_page_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                padding: 0 10px;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        self.prev_page_btn.clicked.connect(self.go_to_previous_page)
        pagination_layout.addWidget(self.prev_page_btn)
        
        # Current page input
        self.current_page_input = QLineEdit("1")
        self.current_page_input.setFixedWidth(50)
        self.current_page_input.setAlignment(Qt.AlignCenter)
        self.current_page_input.setStyleSheet("""
            QLineEdit {
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        self.current_page_input.returnPressed.connect(self.go_to_specific_page)
        pagination_layout.addWidget(self.current_page_input)
        
        # Next page button
        self.next_page_btn = QPushButton(_t("btn_next"))
        self.next_page_btn.setFixedHeight(30)
        self.next_page_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                padding: 0 10px;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        self.next_page_btn.clicked.connect(self.go_to_next_page)
        pagination_layout.addWidget(self.next_page_btn)
        
        # Last page button
        self.last_page_btn = QPushButton(_t("btn_last"))
        self.last_page_btn.setFixedHeight(30)
        self.last_page_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                padding: 0 10px;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        self.last_page_btn.clicked.connect(self.go_to_last_page)
        pagination_layout.addWidget(self.last_page_btn)
        
        pagination_layout.addStretch()
        layout.addLayout(pagination_layout)
        
        # Initialize pagination variables
        self.current_page = 1
        self.page_size = 20
        self.total_events = 0
        self.total_pages = 0
        
        # Alarm records table with scroll area for better small window support
        self.table_group = QGroupBox(_t("log_title"))
        self.table_group.setStyleSheet("""
            QGroupBox {
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        
        table_layout = QVBoxLayout(self.table_group)
        
        # Create scroll area for table
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
        
        # Create table container
        table_container = QWidget()
        table_container_layout = QVBoxLayout(table_container)
        table_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create table
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(10)
        self.table_widget.setHorizontalHeaderLabels([
            _t("header_time"), _t("header_client"), _t("header_type"), _t("header_status"), _t("header_rates"), 
            _t("header_trigger"), _t("header_temp"), _t("header_hv"), _t("header_duration"), _t("header_message")
        ])
        
        # Set table style - Improved readability with smaller font for small windows
        self.table_widget.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                color: #f0f0f0;
                border: none;
                gridline-color: #444444;
                font-size: 13px;  /* Smaller font for better fit in small windows */
                alternate-background-color: #222222;
            }
            QTableWidget::item {
                padding: 4px;  /* Reduced padding for small windows */
                border-bottom: 1px solid #444444;
            }
            QTableWidget::item:hover {
                background-color: #333333;
            }
            QTableWidget::item:selected {
                background-color: #2a5caa;
                color: white;
                font-weight: bold;
            }
            QHeaderView::section {
                background-color: #151515;
                color: #e0e0e0;
                padding: 6px;  /* Reduced padding for small windows */
                border: none;
                border-bottom: 2px solid #444444;
                font-weight: bold;
                font-size: 13px;  /* Smaller font for headers */
            }
            QHeaderView::section:hover {
                background-color: #252525;
            }
        """)
        
        # Set column widths - more aggressive ResizeToContents for small windows
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Time
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Client
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Alarm Type
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Count Rate
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Trigger Rate
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Temperature
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)  # HV
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)  # Duration
        header.setSectionResizeMode(9, QHeaderView.Stretch)           # Message
        
        # Set minimum column widths to ensure readability
        header.setMinimumSectionSize(60)  # Minimum column width
        
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.verticalHeader().setVisible(False)
        
        # Set minimum size for table to ensure visibility in small windows
        self.table_widget.setMinimumHeight(200)
        
        table_container_layout.addWidget(self.table_widget)
        scroll_area.setWidget(table_container)
        
        table_layout.addWidget(scroll_area)
        layout.addWidget(self.table_group, 1)  # 1 means occupy remaining space
        
        self.setLayout(layout)
        
        # Initial refresh
        self.refresh_display()
    
    def create_stat_card(self, title: str, value: str, color: str, card_id: str = "") -> QFrame:
        """Create statistics card - Simplified design without redundant description"""
        card = QFrame()
        # Reduced height since we removed the description label
        card.setMinimumHeight(80)
        card.setMaximumHeight(120)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #2a2a2a;
                border-radius: 12px;
                border: 2px solid {color};
                min-width: 140px;
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)  # Adjusted margins for more compact layout
        layout.setSpacing(5)  # Reduced spacing between elements
        
        # Title - Clear and concise
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 14px;  /* Slightly larger for better visibility */
                font-weight: bold;
                qproperty-alignment: 'AlignCenter';
            }}
        """)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        
        # Value - Prominent display
        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 32px;  /* Larger for emphasis */
                font-weight: bold;
                padding: 2px 0;
                qproperty-alignment: 'AlignCenter';
                text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5);
            }}
        """)
        value_label.setWordWrap(True)
        value_label.setMinimumWidth(80)
        layout.addWidget(value_label)
        
        card.setLayout(layout)
        
        # Store label references for updating (only value label needed now)
        if card_id == "total_events":
            self.total_events_label = value_label
        elif card_id == "active_alarms":
            self.active_alarms_label = value_label
        elif card_id == "alarm_types":
            self.alarm_types_label = value_label
        
        return card
    
    def setup_timer(self):
        """Setup timer for auto-refresh with optimized frequency"""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_display)
        # Optimized: Increase refresh interval from 2 seconds to 3 seconds
        # This reduces UI updates by 33% while still providing timely updates
        self.refresh_timer.start(3000)  # Refresh every 3 seconds (was 2 seconds)
    
    def refresh_display(self):
        """Refresh display with pagination support"""
        # Get statistics
        stats = self.alarm_logger.get_statistics()
        
        # Update statistics cards
        self.total_events_label.setText(str(stats['total_events']))
        self.active_alarms_label.setText(str(stats['active_alarms']))
        self.alarm_types_label.setText(str(len(stats['alarm_types'])))
        
        # Update table with pagination
        self.update_table_with_pagination()
    
    def update_table(self):
        """Update table data with performance optimizations"""
        # Get recent alarm events (max 100)
        events = self.alarm_logger.get_recent_events(100)
        
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
    
    def clear_alarm_logs(self):
        """Clear alarm records"""
        self.alarm_logger.clear_events()
        self.refresh_display()
    
    def save_to_excel(self):
        """Save alarm records to EXCEL with user feedback"""
        try:
            # Get current file path before saving
            current_file = self.alarm_logger.current_excel_file
            
            # Save all events
            self.alarm_logger.save_all_events()
            
            # Get the actual file path after saving (in case new file was created)
            saved_file = self.alarm_logger.current_excel_file
            
            # Show success message
            from PyQt5.QtWidgets import QMessageBox
            from pathlib import Path
            
            # Format the file path for display
            if saved_file:
                file_path = Path(saved_file)
                display_path = f"{file_path.parent.name}/{file_path.name}"
                
                # Create informative message
                stats = self.alarm_logger.get_statistics()
                total_events = stats['total_events']
                
                message = f"""
                <div style='font-size: 12pt;'>
                <b>? Alarm records saved successfully!</b>
                </div>
                <div style='margin-top: 10px; font-size: 10pt;'>
                <b>File:</b> {display_path}<br>
                <b>Location:</b> {file_path.parent}<br>
                <b>Total events saved:</b> {total_events}<br>
                <b>Active alarms:</b> {stats['active_alarms']}<br>
                <b>Alarm types:</b> {len(stats['alarm_types'])}
                </div>
                <div style='margin-top: 15px; font-size: 9pt; color: #888888;'>
                <i>Note: Alarm events are also automatically saved in real-time.</i>
                </div>
                """
                
                QMessageBox.information(
                    self,
                    "Save Successful",
                    message,
                    QMessageBox.Ok
                )
            else:
                QMessageBox.warning(
                    self,
                    "Save Failed",
                    "No EXCEL file is currently open for saving.",
                    QMessageBox.Ok
                )
                
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save alarm records:\n{str(e)}",
                QMessageBox.Ok
            )
    
    def showEvent(self, event):
        """Show event with delayed refresh to improve page switching performance"""
        super().showEvent(event)
        # Use delayed refresh to avoid immediate heavy operations during page switch
        QTimer.singleShot(100, self.refresh_display)
    
    # Pagination methods
    def on_page_size_changed(self, page_size_text):
        """Handle page size change"""
        try:
            new_page_size = int(page_size_text)
            if new_page_size != self.page_size:
                self.page_size = new_page_size
                self.current_page = 1  # Reset to first page
                self.update_table_with_pagination()
        except ValueError:
            pass
    
    def go_to_first_page(self):
        """Go to first page"""
        if self.current_page != 1:
            self.current_page = 1
            self.update_table_with_pagination()
    
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
    
    def go_to_last_page(self):
        """Go to last page"""
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self.update_table_with_pagination()
    
    def go_to_specific_page(self):
        """Go to specific page entered by user"""
        try:
            page_num = int(self.current_page_input.text())
            if 1 <= page_num <= self.total_pages:
                self.current_page = page_num
                self.update_table_with_pagination()
            else:
                # Reset to current page if invalid
                self.current_page_input.setText(str(self.current_page))
        except ValueError:
            # Reset to current page if invalid input
            self.current_page_input.setText(str(self.current_page))
    
    def update_table_with_pagination(self):
        """Update table with pagination support"""
        # Get all alarm events
        all_events = self.alarm_logger.get_recent_events(1000)  # Get up to 1000 events for pagination
        
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
        
        # Performance optimization: Disable visual updates during table population
        self.table_widget.setUpdatesEnabled(False)
        
        try:
            # Set row count
            self.table_widget.setRowCount(len(page_events))
            
            # Fill data for current page
            for row, event in enumerate(page_events):
                display_client = self._format_event_client(event)
                display_type = self._format_event_type(event)
                display_status = self._format_event_status(event)
                display_message = self._format_event_message(event)

                # Time
                time_str = datetime.fromtimestamp(event.timestamp).strftime('%Y-%m-%d %H:%M:%S')
                time_item = QTableWidgetItem(time_str)
                time_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 0, time_item)
                
                # Client ID
                client_item = QTableWidgetItem(display_client)
                client_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 1, client_item)
                
                # Alarm type
                type_item = QTableWidgetItem(display_type)
                type_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 2, type_item)
                
                # Status
                status_item = QTableWidgetItem(display_status)
                status_item.setTextAlignment(Qt.AlignCenter)
                if event.alarm_status:
                    status_item.setForeground(Qt.red)
                else:
                    status_item.setForeground(Qt.green)
                self.table_widget.setItem(row, 3, status_item)
                
                # Peak rate
                peak_rate = getattr(event, 'peak_count_rate', event.count_rate)
                peak_rate_item = QTableWidgetItem(f"{peak_rate:.1f}")
                peak_rate_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 4, peak_rate_item)
                
                # Trigger count rate
                trigger_count_rate_item = QTableWidgetItem(f"{event.trigger_count_rate:.1f}")
                trigger_count_rate_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 5, trigger_count_rate_item)
                
                # Temperature
                temp_item = QTableWidgetItem(f"{event.temperature:.1f}")
                temp_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 6, temp_item)
                
                # High voltage
                hv_item = QTableWidgetItem(f"{event.hv:.1f}")
                hv_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 7, hv_item)
                
                # Duration
                duration_text = f"{event.duration:.3f}" if event.duration > 0 else ""
                duration_item = QTableWidgetItem(duration_text)
                duration_item.setTextAlignment(Qt.AlignCenter)
                self.table_widget.setItem(row, 8, duration_item)
                
                # Message
                message_item = QTableWidgetItem(display_message)
                self.table_widget.setItem(row, 9, message_item)
                
        finally:
            # Re-enable visual updates
            self.table_widget.setUpdatesEnabled(True)
    
    def update_pagination_controls(self):
        """Update pagination control states"""
        # Update page info label
        from core.translation import _t
        self.total_pages_label.setText(_t("page_info", curr=self.current_page, total=self.total_pages))
        
        # Update current page input
        self.current_page_input.setText(str(self.current_page))
        
        # Update button states
        self.first_page_btn.setEnabled(self.current_page > 1)
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)
        self.last_page_btn.setEnabled(self.current_page < self.total_pages)
        
        # Update page size combo
        self.page_size_combo.setCurrentText(str(self.page_size))

    def retranslate_ui(self):
        """Retranslate UI elements based on current language"""
        from core.translation import _t
        self.title_label.setText(_t("log_title"))
        
        # Update stats cards titles
        # Since we stored references to value labels, we need to find the title labels of cards
        # Let's update the card title labels directly
        self.total_events_card.findChild(QLabel).setText(_t("log_total_events"))
        self.active_alarms_card.findChild(QLabel).setText(_t("log_active_alarms"))
        self.alarm_types_card.findChild(QLabel).setText(_t("log_alarm_types"))
        
        # Update buttons
        self.refresh_btn.setText(_t("btn_refresh"))
        self.clear_btn.setText(_t("btn_clear_log"))
        self.save_btn.setText(_t("btn_save_excel"))
        
        # Update pagination labels
        self.page_size_label.setText(_t("page_size"))
        self.first_page_btn.setText(_t("btn_first"))
        self.prev_page_btn.setText(_t("btn_prev"))
        self.next_page_btn.setText(_t("btn_next"))
        self.last_page_btn.setText(_t("btn_last"))
        
        # Update table group title
        self.table_group.setTitle(_t("log_title"))
        
        # Update table headers
        self.table_widget.setHorizontalHeaderLabels([
            _t("header_time"), _t("header_client"), _t("header_type"), _t("header_status"), _t("header_rates"), 
            _t("header_trigger"), _t("header_temp"), _t("header_hv"), _t("header_duration"), _t("header_message")
        ])
        
        # Refresh display to update pagination info text
        self.refresh_display()
    
    
    def clear_alarm_logs(self):
        """Clear alarm records"""
        self.alarm_logger.clear_events()
        # Reset pagination
        self.current_page = 1
        self.refresh_display()
    
    def closeEvent(self, event):
        """Close event"""
        self.refresh_timer.stop()
        super().closeEvent(event)
