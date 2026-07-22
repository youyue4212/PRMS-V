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
        # 仅当用户在设置页点击「设置高压」后为 True；未设置时不按默认 1120 判 E202
        self.hv_user_set = self._to_bool(self.settings.value("HV_USER_SET", False))
        self.threshold = self.settings.value("THRESHOLD", 30, int)
        self.sensitivity = self.settings.value("SENSITIVITY", 3, int)
        self.language = self.settings.value("LANGUAGE", "zh", str)  # "zh" or "en"
        
        # TCP/IP settings
        self.tcp_enabled = self.settings.value("TCP_ENABLED", False, bool)
        self.tcp_mode = self.settings.value("TCP_MODE", "server", str)  # "server" or "client"
        self.tcp_host = self.settings.value("TCP_HOST", "0.0.0.0", str)
        self.tcp_port = self.settings.value("TCP_PORT", 5000, int)
        self.tcp_client_host = self.settings.value("TCP_CLIENT_HOST", "192.168.0.201", str)
        self.tcp_client_port = self.settings.value("TCP_CLIENT_PORT", 8234, int)
        # 通道占用传感器：未接线时 bit5 可能浮空误报，默认关闭直到现场启用
        self.occupancy_sensor_enabled = self.settings.value("OCCUPANCY_SENSOR_ENABLED", False, bool)

    @staticmethod
    def _to_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def mark_hv_user_set(self, voltage=None):
        """用户主动设置高压后调用，启用 E202 相对设定值的偏差检测。"""
        if voltage is not None:
            self.hv = float(voltage)
            self.settings.setValue("HV", self.hv)
        self.hv_user_set = True
        self.settings.setValue("HV_USER_SET", True)

    def update_settings(self, baudrate=None, device=None, adc_channels=None, hv=None, threshold=None, sensitivity=None,
                       tcp_enabled=None, tcp_mode=None, tcp_host=None, tcp_port=None,
                       tcp_client_host=None, tcp_client_port=None, language=None,
                       occupancy_sensor_enabled=None, hv_user_set=None):
        if language is not None:
            self.language = language
            self.settings.setValue("LANGUAGE", language)
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
        if hv_user_set is not None:
            self.hv_user_set = bool(hv_user_set)
            self.settings.setValue("HV_USER_SET", self.hv_user_set)
        if threshold is not None:
            self.threshold = threshold
            self.settings.setValue("THRESHOLD", threshold)
        if sensitivity is not None:
            self.sensitivity = sensitivity
            self.settings.setValue("SENSITIVITY", sensitivity)
        if occupancy_sensor_enabled is not None:
            self.occupancy_sensor_enabled = bool(occupancy_sensor_enabled)
            self.settings.setValue("OCCUPANCY_SENSOR_ENABLED", self.occupancy_sensor_enabled)
        
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
