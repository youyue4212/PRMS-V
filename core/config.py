from PyQt5.QtCore import QSettings

class ConfigManager:
    def __init__(self):
        self.settings = QSettings("Raysen", "Spectrometer")
        self.load_settings()

    def load_settings(self):
        # Default values if settings are not found
        self.baudrate = self.settings.value("BAUDRATE", 115200, int)
        self.device = self.settings.value("device", "/dev/ttyUSB0", str)
        self.adc_channels = self.settings.value("ADC_CHANNELS", 4096, int)
        self.hv = self.settings.value("HV", 1120, float)
        self.threshold = self.settings.value("THRESHOLD", 30, int)
        self.sensitivity = self.settings.value("SENSITIVITY", 3, int)
        
        # TCP/IP settings
        self.tcp_enabled = self.settings.value("TCP_ENABLED", False, bool)
        self.tcp_mode = self.settings.value("TCP_MODE", "server", str)  # "server" or "client"
        self.tcp_host = self.settings.value("TCP_HOST", "0.0.0.0", str)
        self.tcp_port = self.settings.value("TCP_PORT", 5000, int)
        self.tcp_client_host = self.settings.value("TCP_CLIENT_HOST", "192.168.0.201", str)
        self.tcp_client_port = self.settings.value("TCP_CLIENT_PORT", 8234, int)

    def update_settings(self, baudrate=None, device=None, adc_channels=None, hv=None, threshold=None, sensitivity=None,
                       tcp_enabled=None, tcp_mode=None, tcp_host=None, tcp_port=None,
                       tcp_client_host=None, tcp_client_port=None):
        if baudrate is not None:
            self.baudrate = baudrate
            self.settings.setValue("BAUDRATE", baudrate)
        if device is not None:
            self.device = device
            self.settings.setValue("device", device)
        if adc_channels is not None:
            self.adc_channels = adc_channels
            self.settings.setValue("ADC_CHANNELS", adc_channels)
        if hv is not None:
            self.hv = hv
            self.settings.setValue("HV", hv)
        if threshold is not None:
            self.threshold = threshold
            self.settings.setValue("THRESHOLD", threshold)
        if sensitivity is not None:
            self.sensitivity = sensitivity
            self.settings.setValue("SENSITIVITY", sensitivity)
        
        # TCP/IP settings
        if tcp_enabled is not None:
            self.tcp_enabled = tcp_enabled
            self.settings.setValue("TCP_ENABLED", tcp_enabled)
        if tcp_mode is not None:
            self.tcp_mode = tcp_mode
            self.settings.setValue("TCP_MODE", tcp_mode)
        if tcp_host is not None:
            self.tcp_host = tcp_host
            self.settings.setValue("TCP_HOST", tcp_host)
        if tcp_port is not None:
            self.tcp_port = tcp_port
            self.settings.setValue("TCP_PORT", tcp_port)
        if tcp_client_host is not None:
            self.tcp_client_host = tcp_client_host
            self.settings.setValue("TCP_CLIENT_HOST", tcp_client_host)
        if tcp_client_port is not None:
            self.tcp_client_port = tcp_client_port
            self.settings.setValue("TCP_CLIENT_PORT", tcp_client_port)

    def save_settings(self):
        self.settings.sync()
