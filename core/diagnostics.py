# -*- coding: utf-8 -*-
"""
Diagnostics and Self-Check Module for Radiation Detection System
Manages self-check (POST) and runtime fault detection.
"""

import time
from collections import deque
from typing import Dict, List, Tuple, Optional

class FaultCode:
    # E1xx: Connection & Communication
    E101 = "E101"  # 探测器无数据 / 未连接
    E102 = "E102"  # 通信中断 / 超时
    E103 = "E103"  # 探头数量不足（在线 < 期望）

    # M1xx: Master Controller
    M101 = "M101"  # 主控未连接 / 无数据
    M102 = "M102"  # 主控通信中断
    M103 = "M103"  # 主控 L2 无效 / CRC持续异常
    M104 = "M104"  # 主控系统故障

    # E2xx: High Voltage (HV)
    E201 = "E201"  # 高压未建立 / 未供电
    E202 = "E202"  # 高压偏离设定值
    E203 = "E203"  # 高压突然跌落

    # E3xx: Temperature
    E301 = "E301"  # 温度超塑料闪烁体上限
    E302 = "E302"  # 温度超光电倍增管范围
    E303 = "E303"  # 温度传感器故障 (突然大部幅度跳变)
    E304 = "E304"  # 温度读数异常 (极值或无效)

    # E4xx: Count Rate (CPS)
    E401 = "E401"  # 计数率突然大幅波动

    # E5xx: 探头占用传感器（已弃用，通道占用改由主控 GPIO；保留码表兼容旧日志）
    E501 = "E501"

    MAP = {
        E101: ("探测器无数据", "配置的探测器未上报数据，请检查网络、IP设置或探测器供电", "ERROR", "探测器连接异常！请检查网线连接，或尝试断电重启设备。若仍异常，请联系维保人员。"),
        E102: ("通信中断", "探测器通信超时，已超过5秒未收到数据包", "ERROR", "辐射探头通讯异常 → 请断电重启设备，仍异常联系维保人员。"),
        E103: ("探头数量不足", "在线探头数少于设置的期望路数", "ERROR", "探头数量不足，请检查未在线探头的供电与网线。"),
        E201: ("高压未建立", "探测器高压接近0V，可能高压模块未供电或已损坏", "ERROR", "探测器高压异常！设备已自动停止采集，请暂停通道通行，并立即报修。"),
        E202: ("高压偏离设定", "检测到高压与设定值偏差过大（仅在用户主动设置高压且稳谱关闭时检测）", "WARNING", "高压模块过压/欠压保护 → 设备自动停机，禁止通行，立即报修。"),
        E203: ("高压突然跌落", "高压在短时间内大幅度下降，可能存在过流保护或硬件故障", "ERROR", "探测器高压异常！设备已自动停止采集，请暂停通道通行，并立即报修。"),
        E301: ("温度超闪烁体上限", "探测器温度超过塑料闪烁体承受温度(>55°C)", "ERROR", "探测器温度超限！请检查环境散热，暂停使用，并联系维保人员。"),
        E302: ("温度超PMT范围", "温度超出光电倍增管正常工作范围(-20°C ~ 50°C)", "WARNING", "探测器温度异常！请检查环境散热，暂停使用，并联系维保人员。"),
        E303: ("温度传感器故障", "温度在短时间内出现大幅度跳变(>8°C)，可能传感器接触不良", "ERROR", "通道温度传感器故障 → 无法准确读取温度，请联系维保人员。"),
        E304: ("温度读数异常", "温度读数极值或恒定异常，可能温度传感器损坏", "WARNING", "通道温度传感器故障 → 无法准确读取温度，请联系维保人员。"),
        E401: ("计数率异常波动", "计数率(CPS)出现非正常的突发性大幅度波动，可能前端受电磁干扰", "WARNING", "探测器信号不稳定！请检查周边是否有强电磁干扰，或重启设备。"),
        E501: ("占用传感器异常(已弃用)", "旧探头占用逻辑已停用；通道占用请检查主控红外/雷达接线", "WARNING", "通道占用已改由主控判定，请检查主控侧传感器。"),
        M101: ("主控无数据", "主控未连接或启动后长时间未收到主控数据", "ERROR", "主控未连接/无数据 → 无法进行辐射报警判定，请检查主控供电、网络与固件。"),
        M102: ("主控通信中断", "主控已连接但超过超时时间未收到数据", "ERROR", "主控通信中断 → 辐射报警判定暂停，请检查主控网络连接。"),
        M103: ("主控L2无效", "主控连接存在，但未收到有效L2（可能CRC错误或协议不匹配）", "ERROR", "主控L2无效 → 收到主控连接但无有效L2，请检查协议版本或CRC。"),
        M104: ("主控系统故障", "主控上报 decision=0xFF 系统故障", "ERROR", "主控系统故障 → 请暂停通行并联系维保人员。"),
    }

    @classmethod
    def get_info(cls, code: str) -> Tuple[str, str, str, str]:
        return cls.MAP.get(code, ("未知故障", "未知的系统故障", "WARNING", "系统出现未知故障，请联系维保人员。"))


class DiagnosticsManager:
    # 通讯中断判定：无数据包超过该秒数即报 E102（原 30s 现场反馈过慢）
    COMM_TIMEOUT_SEC = 5.0
    # 去抖：超过超时阈值后还需再持续一小段时间，避免 1 次调度抖动就报码
    COMM_TIMEOUT_DEBOUNCE_SEC = 1.2
    # 主控 L2 心跳（M102/M103）：比探头更宽，挡住 K2/TCP 偶发数秒空窗误报
    MASTER_COMM_TIMEOUT_SEC = 10.0
    MASTER_COMM_TIMEOUT_DEBOUNCE_SEC = 2.0
    # 开采集后暂缓 M102：给防火墙弹窗确认、首连建立留时间
    MASTER_COMM_STARTUP_GRACE_SEC = 20.0
    PROBE_COUNT_STARTUP_GRACE_SEC = 45.0
    M104_STARTUP_GRACE_SEC = 45.0
    M104_DEBOUNCE_SEC = 3.0
    # 开机后长时间完全无数据报 E101
    NO_DATA_STARTUP_SEC = 8.0

    def __init__(self, config_manager):
        self.config = config_manager
        
        # Active faults per client: {client_id: {fault_code: timestamp}}
        self.active_faults: Dict[str, Dict[str, float]] = {}
        
        # History for jump/fluctuation detection: {client_id: deque}
        self.temp_history: Dict[str, deque] = {}
        self.hv_history: Dict[str, deque] = {}
        self.cps_history: Dict[str, deque] = {}
        
        # Track when client was last seen
        self.last_packet_time: Dict[str, float] = {}
        
        # Track when acquisition started
        self.acquisition_start_time: Optional[float] = None
        self.is_acquiring = False

        # 本轮采集中曾同时在线的最大探头数；用于热替换后清除旧 IP 的粘性 E102
        self.peak_connected_count = 0
        # 最近一次周期检查中因“在线数已恢复”而清除的离线 client_id
        self.purged_offline_clients: List[str] = []
        # 写盘/重 I/O 期间暂缓 E102，避免主线程卡顿导致假超时
        self.comm_timeout_grace_until: float = 0.0
        # 超时去抖起点：{client_id: first_seen_timeout_ts}
        self.timeout_pending_since: Dict[str, float] = {}

        # 分探头高压设定：{probe_key(IP): voltage}；仅对该探头启用 E202
        self.client_hv_setpoints: Dict[str, float] = {}
        self._load_client_hv_setpoints_from_config()

    def _load_client_hv_setpoints_from_config(self):
        stored = getattr(self.config, "client_hv_setpoints", None) or {}
        self.client_hv_setpoints = {str(k): float(v) for k, v in stored.items()}

    def mark_client_hv_setpoint(self, client_id: str, voltage: float):
        """Record per-probe HV setpoint after user clicks「设置高压」."""
        key = self._extract_ip(client_id) or client_id
        if not key or key == "system":
            return
        self.client_hv_setpoints[key] = float(voltage)

    def defer_comm_timeouts(self, seconds: float):
        """Pause E102 injection until UI/I/O catch up (e.g. background autosave)."""
        try:
            sec = max(0.0, float(seconds))
        except (TypeError, ValueError):
            sec = 0.0
        if sec <= 0:
            return
        until = time.time() + sec
        if until > self.comm_timeout_grace_until:
            self.comm_timeout_grace_until = until

    def comm_timeouts_suppressed(self, now: float = None) -> bool:
        ts = time.time() if now is None else float(now)
        return ts < float(self.comm_timeout_grace_until or 0)

    def start_acquisition(self):
        self.acquisition_start_time = time.time()
        self.is_acquiring = True
        self.comm_timeout_grace_until = 0.0
        self.active_faults.clear()
        self.temp_history.clear()
        self.hv_history.clear()
        self.cps_history.clear()
        self.last_packet_time.clear()
        self.peak_connected_count = 0
        self.purged_offline_clients = []
        self.timeout_pending_since.clear()
        # 保留分探头高压设定（不随开停采集清空）
        self._load_client_hv_setpoints_from_config()

    def stop_acquisition(self):
        self.is_acquiring = False
        self.acquisition_start_time = None

    def register_client(self, client_id: str):
        if client_id not in self.active_faults:
            self.active_faults[client_id] = {}
            self.temp_history[client_id] = deque(maxlen=10)
            self.hv_history[client_id] = deque(maxlen=10)
            self.cps_history[client_id] = deque(maxlen=15)

    def remove_client(self, client_id: str):
        if client_id in self.active_faults:
            del self.active_faults[client_id]
        if client_id in self.temp_history:
            del self.temp_history[client_id]
        if client_id in self.hv_history:
            del self.hv_history[client_id]
        if client_id in self.cps_history:
            del self.cps_history[client_id]
        if client_id in self.last_packet_time:
            del self.last_packet_time[client_id]
        self.timeout_pending_since.pop(client_id, None)

    def add_fault(self, client_id: str, code: str):
        self.register_client(client_id)
        # E101（从未收到包）与 E102（曾经有包后中断）互斥，避免断线叠两条通信记录
        if code == FaultCode.E102:
            self.remove_fault(client_id, FaultCode.E101)
        elif code == FaultCode.E101:
            self.remove_fault(client_id, FaultCode.E102)
        if code not in self.active_faults[client_id]:
            self.active_faults[client_id][code] = time.time()

    def remove_fault(self, client_id: str, code: str):
        if client_id in self.active_faults and code in self.active_faults[client_id]:
            del self.active_faults[client_id][code]

    @staticmethod
    def _extract_ip(client_id: str) -> str:
        if not client_id or client_id == "system":
            return ""
        if client_id == "serial_client":
            return "serial"
        if "_" in client_id:
            tail = client_id.split("_")[-1]
            if ":" in tail:
                return tail.split(":")[0]
            parts = tail.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return tail
        return client_id

    def _clear_stale_sessions_for_ip(self, client_id: str):
        ip = self._extract_ip(client_id)
        if not ip:
            return
        for cid in list(self.active_faults.keys()) + list(self.last_packet_time.keys()):
            if cid == client_id or cid == "system":
                continue
            if self._extract_ip(cid) == ip:
                self.remove_client(cid)

    def _timeout_debounced(self, client_id: str, now: float, last_seen: float) -> bool:
        if last_seen <= 0:
            self.timeout_pending_since.pop(client_id, None)
            return False
        overdue = float(now) - float(last_seen) - self.COMM_TIMEOUT_SEC
        if overdue <= 0:
            self.timeout_pending_since.pop(client_id, None)
            return False
        first = self.timeout_pending_since.get(client_id)
        if first is None:
            self.timeout_pending_since[client_id] = float(now)
            return False
        return (float(now) - float(first)) >= self.COMM_TIMEOUT_DEBOUNCE_SEC

    def process_packet(self, client_id: str, packet) -> List[str]:
        """
        Process a received spectrum packet and run diagnostics.
        Returns a list of active fault codes for this client.
        """
        self.register_client(client_id)
        now = time.time()
        self.last_packet_time[client_id] = now
        
        # Clear connection faults since we received data
        self.remove_fault(client_id, FaultCode.E101)
        self.remove_fault(client_id, FaultCode.E102)
        self.timeout_pending_since.pop(client_id, None)
        self._clear_stale_sessions_for_ip(client_id)

        # 1. High Voltage (高压) Diagnostics
        hv = float(packet.HV)
        # device_status bit3: gain stabilizer on/off
        gain_stabilizer_on = ((int(packet.device_status) >> 3) & 0x1) == 1

        # 分探头设定：两台探头可分别 1100/1200，互不影响
        probe_key = self._extract_ip(client_id) or client_id
        per_probe_set = self.client_hv_setpoints.get(probe_key)
        if per_probe_set is not None:
            hv_user_set = True
            hv_set = float(per_probe_set)
        elif client_id == "serial_client" and bool(getattr(self.config, "hv_user_set", False)):
            # 串口单探头：沿用全局设定
            hv_user_set = True
            hv_set = float(self.config.hv)
        else:
            # 该探头从未单独「设置高压」：不判 E202
            hv_user_set = False
            hv_set = float(self.config.hv)
        
        # E201: No High Voltage (HV < 200V)
        if hv < 200.0:
            self.add_fault(client_id, FaultCode.E201)
            self.remove_fault(client_id, FaultCode.E202)
            self.remove_fault(client_id, FaultCode.E203)
        else:
            self.remove_fault(client_id, FaultCode.E201)
            
            # E202: HV deviation from THIS probe's setpoint (> 80V)
            # 防误报：
            # 1) 该探头从未点击「设置高压」时不比较
            # 2) 稳谱开启时设备会主动调压，不报 E202（突降仍由 E203 覆盖）
            # 3) 实际高压回到设定±80V 内自动消警（无需再点按钮）
            if (not hv_user_set) or gain_stabilizer_on:
                self.remove_fault(client_id, FaultCode.E202)
            elif abs(hv - hv_set) > 80.0:
                self.add_fault(client_id, FaultCode.E202)
            else:
                self.remove_fault(client_id, FaultCode.E202)
                
            # E203: Sudden HV drop
            if len(self.hv_history[client_id]) >= 5:
                avg_prev_hv = sum(self.hv_history[client_id]) / len(self.hv_history[client_id])
                if avg_prev_hv > 500.0 and hv < (avg_prev_hv * 0.6):
                    self.add_fault(client_id, FaultCode.E203)
                else:
                    self.remove_fault(client_id, FaultCode.E203)
                    
        self.hv_history[client_id].append(hv)

        # 2. Temperature (温度) Diagnostics
        temp = float(packet.temperature) / 100.0  # Convert to °C
        
        # E301: Scintillator over temp (> 55°C)
        if temp > 55.0:
            self.add_fault(client_id, FaultCode.E301)
        else:
            self.remove_fault(client_id, FaultCode.E301)
            
        # E302: PMT out of range (-20°C ~ 50°C)
        if temp < -20.0 or temp > 50.0:
            self.add_fault(client_id, FaultCode.E302)
        else:
            self.remove_fault(client_id, FaultCode.E302)
            
        # E303: Temperature sudden jump (> 8°C)
        if len(self.temp_history[client_id]) >= 1:
            last_temp = self.temp_history[client_id][-1]
            if abs(temp - last_temp) > 8.0:
                self.add_fault(client_id, FaultCode.E303)
            else:
                # Keep fault active for 10 seconds to allow user to see it, then auto-clear if normal
                if FaultCode.E303 in self.active_faults[client_id]:
                    if now - self.active_faults[client_id][FaultCode.E303] > 10.0:
                        self.remove_fault(client_id, FaultCode.E303)
                        
        # E304: 温度读数异常。-128/127 为部分 IC 断线固定值，立即报；
        # 0.0°C 可能是真实读数，连续 10 次（含当前）才报。见 FAULT_CODES.md。
        if temp in (-128.0, 127.0):
            self.add_fault(client_id, FaultCode.E304)
        elif temp == 0.0:
            samples = list(self.temp_history[client_id]) + [temp]
            if len(samples) >= 10 and all(t == 0.0 for t in samples[-10:]):
                self.add_fault(client_id, FaultCode.E304)
        else:
            self.remove_fault(client_id, FaultCode.E304)

        self.temp_history[client_id].append(temp)

        # 3. Count Rate (计数率) Diagnostics
        cps = float(packet.counter)
        
        # E401: Count rate sudden wild fluctuation
        # If we have enough history, check if current CPS is > 3.5x the moving average AND absolute change > 100 CPS
        # (excluding radiation alarm state to avoid false positives during actual alarms)
        is_radiation_alarm = (packet.device_status & 0b10000) != 0
        if not is_radiation_alarm and len(self.cps_history[client_id]) >= 10:
            avg_cps = sum(self.cps_history[client_id]) / len(self.cps_history[client_id])
            if avg_cps > 10.0:
                if cps > (avg_cps * 3.5) and (cps - avg_cps) > 100.0:
                    self.add_fault(client_id, FaultCode.E401)
                else:
                    if FaultCode.E401 in self.active_faults[client_id]:
                        if now - self.active_faults[client_id][FaultCode.E401] > 10.0:
                            self.remove_fault(client_id, FaultCode.E401)
            else:
                # For very low background, check absolute jump
                if cps > 150.0:
                    self.add_fault(client_id, FaultCode.E401)
                else:
                    if FaultCode.E401 in self.active_faults[client_id]:
                        if now - self.active_faults[client_id][FaultCode.E401] > 10.0:
                            self.remove_fault(client_id, FaultCode.E401)
        else:
            if is_radiation_alarm:
                # Clear fluctuation fault if it's a real radiation alarm
                self.remove_fault(client_id, FaultCode.E401)

        self.cps_history[client_id].append(cps)

        # 通道占用已改由主控 GPIO（L2 io_status）；不再根据探头 bit5 报 E501
        self.remove_fault(client_id, FaultCode.E501)

        return list(self.active_faults[client_id].keys())

    def run_periodic_checks(self, connected_clients: List[str],
                            ignore_clients: List[str] = None) -> Dict[str, List[str]]:
        """
        Run periodic diagnostics (e.g., connection timeouts).
        Should be called every 1 second.
        ignore_clients: e.g. master TCP id — never treat as probe E101/E102.
        Returns a dictionary of active faults per client.
        """
        now = time.time()
        ignore = {c for c in (ignore_clients or []) if c}
        
        if not self.is_acquiring or not self.acquisition_start_time:
            return {}

        # Master / non-probe sockets: drop from probe fault tables
        for cid in list(ignore):
            if cid in self.active_faults or cid in self.last_packet_time:
                self.remove_client(cid)

        # 1. Check for E101 (开机无数据)
        # If acquisition has been running for more than 15 seconds, and we have no data from expected clients
        time_since_start = now - self.acquisition_start_time
        
        # 无客户端：仅监听待机，不报系统 E101（开软件即「无数据」）
        self.remove_fault("system", FaultCode.E101)

        if connected_clients:
            # Check each connected client
            for client_id in connected_clients:
                if client_id in ignore:
                    continue
                self.register_client(client_id)
                last_seen = self.last_packet_time.get(client_id, 0.0)
                
                if last_seen == 0.0:
                    # Connected but never sent a packet
                    if time_since_start > self.NO_DATA_STARTUP_SEC:
                        self.add_fault(client_id, FaultCode.E101)
                else:
                    self.remove_fault(client_id, FaultCode.E101)
                    
                    # E102: Communication timeout (no packet for > COMM_TIMEOUT_SEC)
                    if self.comm_timeouts_suppressed(now):
                        self.timeout_pending_since.pop(client_id, None)
                        self.remove_fault(client_id, FaultCode.E102)
                    elif self._timeout_debounced(client_id, now, last_seen):
                        self.add_fault(client_id, FaultCode.E102)
                    else:
                        self.remove_fault(client_id, FaultCode.E102)
        # Offline/reconnect by probe IP:
        # - target count = expected_probe_count (>0) else peak this acquisition
        # - keep sticky E102 while online < target
        # - clear when same IP reconnects, or when online >= target (hot-swap new IP)
        connected_set = set(connected_clients)
        connected_ips = {self._extract_ip(c) for c in connected_clients}
        connected_ips.discard("")
        n_conn = len(connected_clients)
        if n_conn > self.peak_connected_count:
            self.peak_connected_count = n_conn

        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        if expected > 0:
            target = expected
        else:
            target = self.peak_connected_count

        slots_restored = target > 0 and n_conn >= target
        self.purged_offline_clients = []

        known_ids = set(self.active_faults.keys()) | set(self.last_packet_time.keys())
        for client_id in list(known_ids):
            if client_id == "system" or client_id in connected_set or client_id in ignore:
                continue
            ip = self._extract_ip(client_id)
            if ip and ip in connected_ips:
                self.remove_client(client_id)
                continue
            if slots_restored:
                # 在线数已达到期望（或峰值）→ 清除旧离线 E102（支持换 IP 热替换）
                self.purged_offline_clients.append(client_id)
                self.remove_client(client_id)
                continue
            if self.comm_timeouts_suppressed(now):
                continue
            if client_id in self.last_packet_time or FaultCode.E102 in self.active_faults.get(client_id, {}):
                self.add_fault(client_id, FaultCode.E102)
            else:
                self.remove_client(client_id)

        has_fresh_data = any(
            (now - self.last_packet_time.get(cid, 0.0)) <= self.COMM_TIMEOUT_SEC
            for cid in connected_clients
            if cid not in ignore
        )
        if has_fresh_data:
            self.remove_fault("system", FaultCode.E101)

        return {cid: list(faults.keys()) for cid, faults in self.active_faults.items()}

    def get_all_active_faults(self) -> List[Tuple[str, str, str, str, str, str]]:
        """
        Get a list of all active faults across all clients.
        Returns: List of (client_id, fault_code, name, description, severity, operator_message)
        """
        results = []
        for client_id, faults in self.active_faults.items():
            for code in faults.keys():
                name, desc, severity, op_msg = FaultCode.get_info(code)
                results.append((client_id, code, name, desc, severity, op_msg))
        return results
