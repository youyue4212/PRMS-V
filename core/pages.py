from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSpacerItem, QSizePolicy
)
from PyQt5.QtSvg import QSvgWidget
from PyQt5.QtGui import QFont

from core.ui_components import DataCard, FONTS, PADDING
from core.icons import get_icon_svg
import time


class OverviewPage(QWidget):
    """Overview page showing radiation data cards and chart - optimized for 1024x600 screen"""
    def __init__(self, parent):
        super().__init__()
        layout = QVBoxLayout()
        # Reduce margins for small screen
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Title - smaller font
        title = QLabel("Gamma-ray Spectrometer")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 18px !important;
                font-weight: bold !important;
                margin-bottom: 8px;
            }
        """)
        layout.addWidget(title)
        
        # Cards row - ensure three cards have equal width
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)
        
        # Radiation card - shows count rate (cps) with larger font, no dose rate
        self.radiation_card = DataCard(
            "Radiation Level",
            "0 cps",
            "Current count rate",  # Show second title
            "",  # Empty subvalue (no dose rate)
            "",  # Empty subtitle
            value_color="#ffffff",
            show_second_title=True,  # Show second title
            larger_font=True  # Use larger font for count rate
        )
        
        # Status card - shows temperature and HV
        self.status_card = DataCard(
            "Status",
            "0 " + chr(176) + "C",
            "Temperature",
            "0 V",
            "HV",
            value_color="#ff8c00"
        )
        
        # Alarm indicator card - optimized for compact
        self.alarm_card = QFrame()
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
        
        self.alarm_title_label = QLabel("ALARM STATUS")
        self.alarm_title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }
        """)
        title_layout.addWidget(self.alarm_title_label)
        title_layout.addStretch()
        
        alarm_layout.addLayout(title_layout)
        
        # Main alarm indicator
        self.alarm_indicator = QSvgWidget()
        self.alarm_indicator.setFixedSize(50, 50)
        self.alarm_indicator.load(get_icon_svg('alarm_inactive'))
        alarm_layout.addWidget(self.alarm_indicator, 0, Qt.AlignCenter)
        
        # Alarm status label
        self.alarm_status_label = QLabel("SYSTEM NORMAL")
        self.alarm_status_label.setStyleSheet("""
            QLabel {
                color: #4caf50;
                font-size: 15px;
                font-weight: bold;
                margin-top: 4px;
                padding: 3px 8px;
                background-color: rgba(76, 175, 80, 0.1);
                border-radius: 8px;
                border: 1px solid rgba(76, 175, 80, 0.3);
            }
        """)
        self.alarm_status_label.setAlignment(Qt.AlignCenter)
        alarm_layout.addWidget(self.alarm_status_label, 0, Qt.AlignCenter)
        
        # Alarm description
        self.alarm_desc_label = QLabel("No alarm detected")
        self.alarm_desc_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                font-weight: normal;
                margin-top: 2px;
                font-style: italic;
            }
        """)
        self.alarm_desc_label.setAlignment(Qt.AlignCenter)
        alarm_layout.addWidget(self.alarm_desc_label, 0, Qt.AlignCenter)
        
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
        
        alarm_layout.addStretch()
        self.alarm_card.setLayout(alarm_layout)

        # Occupancy indicator card - optimized for compact
        self.occupancy_card = QFrame()
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
        
        self.occupancy_title_label = QLabel("CHANNEL STATUS")
        self.occupancy_title_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }
        """)
        occ_title_layout.addWidget(self.occupancy_title_label)
        occ_title_layout.addStretch()
        
        occupancy_layout.addLayout(occ_title_layout)
        
        # Main occupancy indicator
        self.occupancy_indicator = QSvgWidget()
        self.occupancy_indicator.setFixedSize(50, 50)
        self.occupancy_indicator.load(get_icon_svg('occupancy_inactive'))
        occupancy_layout.addWidget(self.occupancy_indicator, 0, Qt.AlignCenter)
        
        # Occupancy status label
        self.occupancy_status_label = QLabel("CHANNEL VACANT")
        self.occupancy_status_label.setStyleSheet("""
            QLabel {
                color: #4caf50;
                font-size: 15px;
                font-weight: bold;
                margin-top: 4px;
                padding: 3px 8px;
                background-color: rgba(76, 175, 80, 0.1);
                border-radius: 8px;
                border: 1px solid rgba(76, 175, 80, 0.3);
            }
        """)
        self.occupancy_status_label.setAlignment(Qt.AlignCenter)
        occupancy_layout.addWidget(self.occupancy_status_label, 0, Qt.AlignCenter)
        
        # Occupancy description
        self.occupancy_desc_label = QLabel("No traffic detected")
        self.occupancy_desc_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                font-weight: normal;
                margin-top: 2px;
                font-style: italic;
            }
        """)
        self.occupancy_desc_label.setAlignment(Qt.AlignCenter)
        occupancy_layout.addWidget(self.occupancy_desc_label, 0, Qt.AlignCenter)
        
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
        
        occupancy_layout.addStretch()
        self.occupancy_card.setLayout(occupancy_layout)
        
        # Add four cards to layout with equal width
        cards_layout.addWidget(self.radiation_card, 1)
        cards_layout.addWidget(self.status_card, 1)
        cards_layout.addWidget(self.alarm_card, 1)
        cards_layout.addWidget(self.occupancy_card, 1)
        
        layout.addLayout(cards_layout)
        
        # Chart section
        chart_title = QLabel("Count Rate Time Series")
        chart_title_font = QFont(FONTS["subtitle"][0], FONTS["subtitle"][1])
        if len(FONTS["subtitle"]) > 2 and "bold" in FONTS["subtitle"][2]:
            chart_title_font.setBold(True)
        chart_title.setFont(chart_title_font)
        chart_title.setStyleSheet("""
            QLabel {
                color: white;
                font-weight: bold;
                font-size: 14px;
                margin-top: 8px;
                margin-bottom: 5px;
            }
        """)
        layout.addWidget(chart_title)
        
        self.chart = parent.create_cps_widget()
        layout.addWidget(self.chart, 1)
        
        self.setLayout(layout)


class SpectrumPage(QWidget):
    """Spectrum page for displaying energy spectrum"""
    def __init__(self, parent):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("Energy Spectrum and Spectrogram")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px !important;
                font-weight: bold !important;
                margin-bottom: 20px;
            }
        """)
        layout.addWidget(title)
        
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


class SettingsPage(QWidget):
    """Settings page for configuration"""
    def __init__(self, parent):
        super().__init__()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("Settings")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px !important;
                font-weight: bold !important;
                margin-bottom: 20px;
            }
        """)
        main_layout.addWidget(title)

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


class ClientsPage(QWidget):
    """Clients page showing detailed information for each connected client"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("Connected Clients")
        title.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 22px !important;
                font-weight: bold !important;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(title)
        
        # Client count summary
        self.client_summary_label = QLabel("No clients connected")
        summary_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        self.client_summary_label.setFont(summary_font)
        self.client_summary_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-weight: normal;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(self.client_summary_label)
        
        # Scroll area for client cards
        scroll_area = QWidget()
        scroll_area.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(scroll_area)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)
        
        # Container for scroll area
        scroll_container = QWidget()
        scroll_container.setLayout(QVBoxLayout())
        scroll_container.layout().addWidget(scroll_area)
        scroll_container.layout().setContentsMargins(0, 0, 0, 0)
        
        # Add scroll area to main layout
        layout.addWidget(scroll_container, 1)
        
        # Add refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(40)
        refresh_btn.setStyleSheet("""
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
        refresh_btn.clicked.connect(self.refresh_client_display)
        layout.addWidget(refresh_btn, 0, Qt.AlignCenter)
        
        self.setLayout(layout)
        
        # Timer to auto-refresh client display
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_client_display)
        self.refresh_timer.start(2000)
        
        # Store client widgets
        self.client_widgets = {}
    
    def refresh_client_display(self):
        """Refresh the client display with current data"""
        # Get client data from parent
        if hasattr(self.parent, 'client_data'):
            client_data = self.parent.client_data
        else:
            client_data = getattr(self.parent, 'client_data', {})
        
        # Update summary
        client_count = len(client_data)
        if client_count == 0:
            self.client_summary_label.setText("No clients connected")
        else:
            self.client_summary_label.setText(f"{client_count} client(s) connected")
        
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
        widget = QFrame()
        widget.setFixedHeight(150)
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
        
        client_id_label = QLabel(f"Client: {client_id}")
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
        status_text = "Active" if time_diff < 5 else "Idle" if time_diff < 15 else "Inactive"
        
        status_label = QLabel(f"Status: {status_text}")
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
        alarm_label = QLabel("ALARM" if alarm_status else "Normal")
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
        occupancy_label = QLabel("Occupied" if occupancy_status else "Free")
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
        faults_label = QLabel("No Faults")
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
        count_rate_label = QLabel("Count Rate:")
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
        temp_label = QLabel("Temperature:")
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
        hv_label = QLabel("High Voltage:")
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
        product_label = QLabel("Product ID:")
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
        
        sensitivity_label = QLabel("Sensitivity:")
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
        status_text = "Active" if time_diff < 5 else "Idle" if time_diff < 15 else "Inactive"
        
        labels['status'].setText(f"Status: {status_text}")
        labels['status'].setStyleSheet(f"""
            QLabel {{
                color: {status_color};
                font-size: 12px;
                font-weight: normal;
            }}
        """)
        
        # Update alarm status
        alarm_status = data.get('alarm', False)
        labels['alarm'].setText("ALARM" if alarm_status else "Normal")
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
        labels['occupancy'].setText("Occupied" if occupancy_status else "Free")
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
                labels['faults'].setText(f"Faults: {faults_str}")
                labels['faults'].setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 12px;
                        font-weight: bold;
                        margin-top: 5px;
                    }
                """)
            else:
                labels['faults'].setText("No Faults")
                labels['faults'].setStyleSheet("""
                    QLabel {
                        color: #4caf50;
                        font-size: 12px;
                        font-weight: bold;
                        margin-top: 5px;
                    }
                """)
