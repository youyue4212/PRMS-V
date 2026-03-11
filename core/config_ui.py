import sys
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QComboBox, QTextEdit, QGroupBox, QMessageBox)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

def search_serial_devices():
    available_ports_info = serial.tools.list_ports.comports()
    detected_port = None
    for port_info in available_ports_info:
        # Check if it's a CH340 device
        if port_info.vid == 0x1a86 and port_info.pid == 0x7523:  # CH340 VID:PID
            try:
                detected_port=port_info
                s = serial.Serial(port_info.device, timeout=1)
                s.close()
            except (OSError, serial.SerialException):
                pass
    #print('detected_port:',detected_port)
    return detected_port

class ESP32ConfigGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.usb_mode_timer = None
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('ESP32 UART Configuration Tool')
        self.setGeometry(100, 100, 700, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # Serial Port Section
        port_group = QGroupBox("Serial Port")
        port_layout = QHBoxLayout()
        self.port_found = search_serial_devices()

        
        self.port_combo = QComboBox()
        port_layout.addWidget(QLabel("Port:"))
        port_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_layout.addWidget(self.refresh_btn)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        port_layout.addWidget(self.connect_btn)
        
        port_group.setLayout(port_layout)
        layout.addWidget(port_group)
        
        # Configuration Section
        config_group = QGroupBox("Device Configuration")
        config_layout = QVBoxLayout()
        
        # WiFi SSID
        wifi_layout = QHBoxLayout()
        wifi_layout.addWidget(QLabel("WiFi SSID:"))
        self.ssid_input = QLineEdit()
        self.ssid_input.setPlaceholderText("Enter WiFi network name")
        wifi_layout.addWidget(self.ssid_input)
        config_layout.addLayout(wifi_layout)
        
        # WiFi Password
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(QLabel("WiFi Password:"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter WiFi password")
        self.password_input.setEchoMode(QLineEdit.Password)
        pass_layout.addWidget(self.password_input)
        config_layout.addLayout(pass_layout)
        
        # Server IP
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("CoAP Server IP:"))
        self.server_input = QLineEdit()
        self.server_input.setText('18.159.187.228')
        self.server_input.setPlaceholderText("e.g., 192.168.1.100")
        server_layout.addWidget(self.server_input)
        config_layout.addLayout(server_layout)
        
        # Device ID
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("Device ID:"))
        self.deviceid_input = QLineEdit()
        self.deviceid_input.setText('0x1236')
        self.deviceid_input.setPlaceholderText("e.g., 0x1234 or 4660")
        id_layout.addWidget(self.deviceid_input)
        config_layout.addLayout(id_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Action Buttons Section
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()
        
        # Row 1: Individual config buttons
        btn_row1 = QHBoxLayout()
        self.send_wifi_btn = QPushButton("Send WiFi Config")
        self.send_wifi_btn.clicked.connect(self.send_wifi_config)
        btn_row1.addWidget(self.send_wifi_btn)
        
        self.send_server_btn = QPushButton("Send Server IP")
        self.send_server_btn.clicked.connect(self.send_server_config)
        btn_row1.addWidget(self.send_server_btn)
        
        self.send_deviceid_btn = QPushButton("Send Device ID")
        self.send_deviceid_btn.clicked.connect(self.send_deviceid_config)
        btn_row1.addWidget(self.send_deviceid_btn)
        action_layout.addLayout(btn_row1)
        
        # Row 2: Send all and reboot buttons
        btn_row2 = QHBoxLayout()
        self.send_all_btn = QPushButton("Send All Configs")
        self.send_all_btn.clicked.connect(self.send_all_config)
        self.send_all_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        btn_row2.addWidget(self.send_all_btn)
        
        self.reboot_btn = QPushButton("Reboot Device")
        self.reboot_btn.clicked.connect(self.reboot_device)
        btn_row2.addWidget(self.reboot_btn)
        
        self.usb_mode_btn = QPushButton("Start USB Mode")
        self.usb_mode_btn.clicked.connect(self.start_usb_mode)
        self.usb_mode_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        btn_row2.addWidget(self.usb_mode_btn)
        action_layout.addLayout(btn_row2)
        
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)
        
        # Log Section
        log_group = QGroupBox("Communication Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier", 9))
        log_layout.addWidget(self.log_text)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Disable action buttons initially
        self.set_buttons_enabled(False)

        if self.port_found:
            self.port_combo.addItem(f"{self.port_found.device}")


        
    def refresh_ports(self):
        self.port_combo.clear()
        self.port_found = search_serial_devices()
        ports = [self.port_found]
        for port in ports:
            if port:
                self.port_combo.addItem(f"{port.device}")
    
    def toggle_connection(self):
        if self.serial_port and self.serial_port.is_open:
            self.disconnect()
        else:
            self.connect()
    
    def connect(self):
        try:
            port_text = self.port_combo.currentText()
            if not port_text:
                QMessageBox.warning(self, "Error", "No port selected")
                return
            
            port_name = port_text.split(" - ")[0]
            self.serial_port = serial.Serial(port_name, 115200, timeout=1)
            self.log(f"✓ Connected to {port_name}")
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setStyleSheet("background-color: #f44336; color: white;")
            self.set_buttons_enabled(True)
            
            # Start reading from serial
            self.read_timer = QTimer()
            self.read_timer.timeout.connect(self.read_serial)
            self.read_timer.start(100)
            
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            self.log(f"✗ Connection failed: {e}")
    
    def disconnect(self):
        if self.serial_port:
            self.read_timer.stop()
            self.serial_port.close()
            self.serial_port = None
            self.log("✓ Disconnected")
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet("")
            self.set_buttons_enabled(False)
    
    def set_buttons_enabled(self, enabled):
        self.send_wifi_btn.setEnabled(enabled)
        self.send_server_btn.setEnabled(enabled)
        self.send_deviceid_btn.setEnabled(enabled)
        self.send_all_btn.setEnabled(enabled)
        self.reboot_btn.setEnabled(enabled)
        self.usb_mode_btn.setEnabled(enabled)
    
    def send_command(self, command):
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "Error", "Not connected to device")
            return False
        
        try:
            self.serial_port.write((command + "\n").encode())
            self.log(f"→ Sent: {command}")
            return True
        except Exception as e:
            self.log(f"✗ Send failed: {e}")
            QMessageBox.critical(self, "Send Error", str(e))
            return False
    
    def send_wifi_config(self):
        ssid = self.ssid_input.text().strip()
        password = self.password_input.text().strip()
        
        if not ssid or not password:
            QMessageBox.warning(self, "Input Error", "Please enter both WiFi SSID and password")
            return
        
        command = f"wifi:{ssid},{password}"
        self.send_command(command)
    
    def send_server_config(self):
        server = self.server_input.text().strip()
        
        if not server:
            QMessageBox.warning(self, "Input Error", "Please enter server IP address")
            return
        
        command = f"server:{server}"
        self.send_command(command)
    
    def send_deviceid_config(self):
        device_id = self.deviceid_input.text().strip()
        
        if not device_id:
            QMessageBox.warning(self, "Input Error", "Please enter device ID")
            return
        
        command = f"deviceid:{device_id}"
        self.send_command(command)
    
    def send_all_config(self):
        success = True
        
        if self.ssid_input.text().strip() and self.password_input.text().strip():
            success &= self.send_command(f"wifi:{self.ssid_input.text().strip()},{self.password_input.text().strip()}")
            QTimer.singleShot(200, lambda: None)  # Small delay
        
        if self.server_input.text().strip():
            success &= self.send_command(f"server:{self.server_input.text().strip()}")
            QTimer.singleShot(200, lambda: None)
        
        if self.deviceid_input.text().strip():
            success &= self.send_command(f"deviceid:{self.deviceid_input.text().strip()}")
        
        if success:
            self.log("✓ All configurations sent")
    
    def reboot_device(self):
        reply = QMessageBox.question(self, "Confirm Reboot", 
                                     "Are you sure you want to reboot the device?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.send_command("reboot")
    
    def start_usb_mode(self):
        self.log("Starting USB mode sequence...")
        self.send_command("mode:usb")
        self.log("✓ USB mode command sent")
    
    def read_serial(self):
        if self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                    if data:
                        self.log(f"← {data}")
            except Exception as e:
                self.log(f"✗ Read error: {e}")
    
    def log(self, message):
        self.log_text.append(message)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def closeEvent(self, event):
        if self.serial_port and self.serial_port.is_open:
            self.disconnect()
        event.accept()

def main():
    app = QApplication(sys.argv)
    gui = ESP32ConfigGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
