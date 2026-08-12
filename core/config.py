import json
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
        # 多探头各自高压设定：{probe_key(IP): voltage}（E202 用）
        self.client_hv_setpoints = self._load_json_dict("CLIENT_HV_SETPOINTS", float)
        self.threshold = self.settings.value("THRESHOLD", 30, int)
        self.sensitivity = self.settings.value("SENSITIVITY", 3, int)
        # 多探头面板参数：{ip: {hv, threshold, sensitivity, product_id}}
        self.client_probe_settings = self._load_probe_settings()
        self.language = self.settings.value("LANGUAGE", "zh", str)  # "zh" or "en"
        # UI shell: tablet (7" HMI) | control_room (PC overview wall)
        raw_mode = str(self.settings.value("UI_MODE", "tablet", str) or "tablet").strip().lower()
        self.ui_mode = raw_mode if raw_mode in ("tablet", "control_room") else "tablet"

        # TCP/IP settings
        self.tcp_enabled = self.settings.value("TCP_ENABLED", False, bool)
        self.tcp_mode = self.settings.value("TCP_MODE", "server", str)  # "server" or "client"
        self.tcp_host = self.settings.value("TCP_HOST", "0.0.0.0", str)
        self.tcp_port = self.settings.value("TCP_PORT", 5000, int)
        self.tcp_client_host = self.settings.value("TCP_CLIENT_HOST", "192.168.0.201", str)
        self.tcp_client_port = self.settings.value("TCP_CLIENT_PORT", 8234, int)
        # 期望探头数量：在线数 < 期望则报缺；>= 期望则清除旧离线 E102（支持换 IP）
        # 0 = 未配置，回退为本轮峰值在线数（调试兜底）
        self.expected_probe_count = self.settings.value("EXPECTED_PROBE_COUNT", 2, int)
        try:
            self.expected_probe_count = max(0, min(16, int(self.expected_probe_count)))
        except (TypeError, ValueError):
            self.expected_probe_count = 2

        # Home probe slot location labels (editable in Settings).
        # Empty list → HomePage uses translation defaults (zh/en).
        self._default_probe_slot_locations = [
            "左侧 · 上",
            "右侧 · 上",
            "左侧 · 下",
            "右侧 · 下",
        ]
        raw_locs = self.settings.value("PROBE_SLOT_LOCATIONS", "", str)
        self.probe_slot_locations = []
        if raw_locs:
            try:
                parsed = json.loads(raw_locs) if isinstance(raw_locs, str) else raw_locs
                if isinstance(parsed, list):
                    self.probe_slot_locations = [str(x).strip() for x in parsed]
            except Exception:
                self.probe_slot_locations = []
        # Previously auto-persisted stock labels → clear so language defaults apply
        if self.probe_slot_locations:
            en_stock = ["Left · Upper", "Right · Upper", "Left · Lower", "Right · Lower"]
            # Normalize length for stock compare
            locs4 = list(self.probe_slot_locations) + [""] * 4
            locs4 = locs4[:4]
            if locs4 == self._default_probe_slot_locations or locs4 == en_stock:
                self.probe_slot_locations = []
                self.settings.remove("PROBE_SLOT_LOCATIONS")
            elif not any(locs4):
                self.probe_slot_locations = []
                self.settings.remove("PROBE_SLOT_LOCATIONS")
            else:
                # Keep full custom list (may be >4); only normalize empty tails lightly
                self.probe_slot_locations = [
                    str(x).strip() for x in self.probe_slot_locations
                ][:16]

        # Home probe card display order (client_id list). Empty → default sort.
        raw_order = self.settings.value("PROBE_DISPLAY_ORDER", "", str)
        self.probe_display_order = []
        if raw_order:
            try:
                parsed = json.loads(raw_order) if isinstance(raw_order, str) else raw_order
                if isinstance(parsed, list):
                    self.probe_display_order = [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                self.probe_display_order = []

        # 计数率图时间窗口（分钟）：1 / 5 / 15，默认 5
        self.cps_window_minutes = self.settings.value("CPS_WINDOW_MINUTES", 5, int)
        try:
            self.cps_window_minutes = int(self.cps_window_minutes)
        except (TypeError, ValueError):
            self.cps_window_minutes = 5
        if self.cps_window_minutes not in (1, 5, 15):
            self.cps_window_minutes = 5

    @staticmethod
    def _to_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _load_json_dict(self, key, value_cast=float):
        raw = self.settings.value(key, "", str)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            out = {}
            for k, v in data.items():
                try:
                    out[str(k)] = value_cast(v)
                except (TypeError, ValueError):
                    continue
            return out
        except Exception:
            return {}

    def mark_hv_user_set(self, voltage=None):
        """用户主动设置高压后调用（全局默认/串口）；多探头请再用 mark_client_hv_setpoint。"""
        if voltage is not None:
            self.hv = float(voltage)
            self.settings.setValue("HV", self.hv)
        self.hv_user_set = True
        self.settings.setValue("HV_USER_SET", True)

    def mark_client_hv_setpoint(self, probe_key: str, voltage: float):
        """按探头(IP)记录高压设定，供 E202 分探头判断。"""
        if not probe_key:
            return
        self.client_hv_setpoints[str(probe_key)] = float(voltage)
        self.settings.setValue("CLIENT_HV_SETPOINTS", json.dumps(self.client_hv_setpoints))
        # 同步全局默认 + 面板参数
        self.mark_hv_user_set(voltage)
        self.update_probe_settings(probe_key, hv=float(voltage))

    def _load_probe_settings(self) -> dict:
        """Load per-probe panel settings; migrate legacy HV setpoints if needed."""
        raw = self.settings.value("CLIENT_PROBE_SETTINGS", "", str)
        out = {}
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            out[str(k)] = dict(v)
            except Exception:
                out = {}
        # 兼容旧版仅保存了高压设定
        for ip, hv in (self.client_hv_setpoints or {}).items():
            entry = out.setdefault(str(ip), {})
            if "hv" not in entry:
                entry["hv"] = float(hv)
        return out

    def get_probe_settings(self, probe_key: str) -> dict:
        """Return settings for a probe, falling back to global defaults."""
        key = str(probe_key or "")
        stored = (self.client_probe_settings or {}).get(key, {}) if key else {}
        return {
            "hv": float(stored.get("hv", self.hv)),
            "threshold": int(stored.get("threshold", self.threshold)),
            "sensitivity": int(stored.get("sensitivity", self.sensitivity)),
            "product_id": stored.get("product_id", None),
        }

    def update_probe_settings(self, probe_key: str, hv=None, threshold=None,
                              sensitivity=None, product_id=None):
        """Update and persist panel settings for one probe (keyed by IP)."""
        if not probe_key:
            return
        key = str(probe_key)
        entry = dict(self.client_probe_settings.get(key, {}))
        if hv is not None:
            entry["hv"] = float(hv)
            self.hv = float(hv)
            self.settings.setValue("HV", self.hv)
        if threshold is not None:
            entry["threshold"] = int(threshold)
            self.threshold = int(threshold)
            self.settings.setValue("THRESHOLD", self.threshold)
        if sensitivity is not None:
            entry["sensitivity"] = int(sensitivity)
            self.sensitivity = int(sensitivity)
            self.settings.setValue("SENSITIVITY", self.sensitivity)
        if product_id is not None:
            try:
                entry["product_id"] = int(product_id)
            except (TypeError, ValueError):
                pass
        self.client_probe_settings[key] = entry
        self.settings.setValue("CLIENT_PROBE_SETTINGS", json.dumps(self.client_probe_settings))

    def update_settings(self, baudrate=None, device=None, adc_channels=None, hv=None, threshold=None, sensitivity=None,
                       tcp_enabled=None, tcp_mode=None, tcp_host=None, tcp_port=None,
                       tcp_client_host=None, tcp_client_port=None, language=None,
                       hv_user_set=None,
                       expected_probe_count=None, cps_window_minutes=None,
                       ui_mode=None):
        if language is not None:
            self.language = language
            self.settings.setValue("LANGUAGE", language)
        if ui_mode is not None:
            mode = str(ui_mode).strip().lower()
            if mode not in ("tablet", "control_room"):
                mode = "tablet"
            self.ui_mode = mode
            self.settings.setValue("UI_MODE", self.ui_mode)
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
        if expected_probe_count is not None:
            try:
                self.expected_probe_count = max(0, min(16, int(expected_probe_count)))
            except (TypeError, ValueError):
                self.expected_probe_count = 0
            self.settings.setValue("EXPECTED_PROBE_COUNT", self.expected_probe_count)
        if cps_window_minutes is not None:
            try:
                m = int(cps_window_minutes)
            except (TypeError, ValueError):
                m = 5
            if m not in (1, 5, 15):
                m = 5
            self.cps_window_minutes = m
            self.settings.setValue("CPS_WINDOW_MINUTES", self.cps_window_minutes)
        
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

    def set_probe_slot_locations(self, locations):
        """Persist home HMI probe slot location labels. Empty/None clears override."""
        if locations is None:
            self.probe_slot_locations = []
            self.settings.remove("PROBE_SLOT_LOCATIONS")
            return
        cleaned = [str(x).strip() for x in list(locations)]
        # Keep slot index alignment; allow up to 16 home tiles
        if len(cleaned) > 16:
            cleaned = cleaned[:16]
        if not any(cleaned):
            self.probe_slot_locations = []
            self.settings.remove("PROBE_SLOT_LOCATIONS")
            return
        self.probe_slot_locations = cleaned
        self.settings.setValue(
            "PROBE_SLOT_LOCATIONS",
            json.dumps(self.probe_slot_locations, ensure_ascii=False),
        )

    def set_probe_display_order(self, order):
        """Persist home HMI probe card order by client_id (or slot:N)."""
        if order is None:
            self.probe_display_order = []
            self.settings.remove("PROBE_DISPLAY_ORDER")
            return
        cleaned = [str(x).strip() for x in list(order) if str(x).strip()]
        self.probe_display_order = cleaned
        if not cleaned:
            self.settings.remove("PROBE_DISPLAY_ORDER")
            return
        self.settings.setValue(
            "PROBE_DISPLAY_ORDER",
            json.dumps(self.probe_display_order, ensure_ascii=False),
        )

