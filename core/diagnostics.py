# -*- coding: gbk -*-
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

    # E5xx: Occupancy Sensor
    E501 = "E501"  # 通道占用传感器异常 / 卡死

    MAP = {
        E101: ("探测器无数据", "配置的探测器未上报数据，请检查网络、IP设置或探测器供电", "ERROR", "探测器连接异常！请检查网线连接，或尝试断电重启设备。若仍异常，请联系维保人员。"),
        E102: ("通信中断", "探测器通信超时，已超过30秒未收到数据包", "ERROR", "1号辐射探头通讯异常 → 请断电重启设备，仍异常联系维保人员。"),
        E201: ("高压未建立", "探测器高压接近0V，可能高压模块未供电或已损坏", "ERROR", "探测器高压异常！设备已自动停止采集，请暂停通道通行，并立即报修。"),
        E202: ("高压偏离设定", "检测到高压与设定值偏差过大，请检查高压模块或稳谱设置", "WARNING", "高压模块过压/欠压保护 → 设备自动停机，禁止通行，立即报修。"),
        E203: ("高压突然跌落", "高压在短时间内大幅度下降，可能存在过流保护或硬件故障", "ERROR", "探测器高压异常！设备已自动停止采集，请暂停通道通行，并立即报修。"),
        E301: ("温度超闪烁体上限", "探测器温度超过塑料闪烁体承受温度(>55°C)", "ERROR", "探测器温度超限！请检查环境散热，暂停使用，并联系维保人员。"),
        E302: ("温度超PMT范围", "温度超出光电倍增管正常工作范围(-20°C ~ 50°C)", "WARNING", "探测器温度异常！请检查环境散热，暂停使用，并联系维保人员。"),
        E303: ("温度传感器故障", "温度在短时间内出现大幅度跳变(>8°C)，可能传感器接触不良", "ERROR", "通道温度传感器故障 → 无法准确读取温度，请联系维保人员。"),
        E304: ("温度读数异常", "温度读数极值或恒定异常，可能温度传感器损坏", "WARNING", "通道温度传感器故障 → 无法准确读取温度，请联系维保人员。"),
        E401: ("计数率异常波动", "计数率(CPS)出现非正常的突发性大幅度波动，可能前端受电磁干扰", "WARNING", "探测器信号不稳定！请检查周边是否有强电磁干扰，或重启设备。"),
        E501: ("占用传感器异常", "通道占用传感器状态持续异常或卡死，请检查接线", "WARNING", "通道人体感应故障 → 无法识别行人，暂停使用，请联系维保人员。"),
    }

    @classmethod
    def get_info(cls, code: str) -> Tuple[str, str, str, str]:
        return cls.MAP.get(code, ("未知故障", "未知的系统故障", "WARNING", "系统出现未知故障，请联系维保人员。"))


class DiagnosticsManager:
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
        
        # Occupancy stuck detection
        self.occupancy_start_time: Dict[str, float] = {}

    def start_acquisition(self):
        self.acquisition_start_time = time.time()
        self.is_acquiring = True
        self.active_faults.clear()
        self.temp_history.clear()
        self.hv_history.clear()
        self.cps_history.clear()
        self.last_packet_time.clear()
        self.occupancy_start_time.clear()

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
        if client_id in self.occupancy_start_time:
            del self.occupancy_start_time[client_id]

    def add_fault(self, client_id: str, code: str):
        self.register_client(client_id)
        if code not in self.active_faults[client_id]:
            self.active_faults[client_id][code] = time.time()

    def remove_fault(self, client_id: str, code: str):
        if client_id in self.active_faults and code in self.active_faults[client_id]:
            del self.active_faults[client_id][code]

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

        # 1. High Voltage (高压) Diagnostics
        hv = float(packet.HV)
        hv_set = float(self.config.hv)
        
        # E201: No High Voltage (HV < 200V)
        if hv < 200.0:
            self.add_fault(client_id, FaultCode.E201)
            self.remove_fault(client_id, FaultCode.E202)
            self.remove_fault(client_id, FaultCode.E203)
        else:
            self.remove_fault(client_id, FaultCode.E201)
            
            # E202: HV deviation from setpoint (> 80V)
            if abs(hv - hv_set) > 80.0:
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
                        
        # E304: Temperature讀数异常 (e.g., exactly 0.0 or extreme static value)
        # Check if temperature is exactly -128 or 127 (sensor disconnect values for some ICs)
        if temp == -128.0 or temp == 127.0 or temp == 0.0:
            # Note: 0.0 is possible but rare, we flag it if it stays exactly 0.0 for 10 packets
            if len(self.temp_history[client_id]) == 10 and all(t == 0.0 for t in self.temp_history[client_id]):
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

        # 4. Occupancy Sensor (通道占用) Diagnostics
        # device_status bit5: 0=Free, 1=Occupied
        is_occupied = (packet.device_status & 0b100000) != 0
        if is_occupied:
            if client_id not in self.occupancy_start_time:
                self.occupancy_start_time[client_id] = now
            else:
                # E501: Occupancy stuck (occupied for more than 5 minutes / 300 seconds)
                if now - self.occupancy_start_time[client_id] > 300.0:
                    self.add_fault(client_id, FaultCode.E501)
        else:
            self.occupancy_start_time[client_id] = 0.0
            self.remove_fault(client_id, FaultCode.E501)

        return list(self.active_faults[client_id].keys())

    def run_periodic_checks(self, connected_clients: List[str]) -> Dict[str, List[str]]:
        """
        Run periodic diagnostics (e.g., connection timeouts).
        Should be called every 1 second.
        Returns a dictionary of active faults per client.
        """
        now = time.time()
        
        if not self.is_acquiring or not self.acquisition_start_time:
            return {}

        # 1. Check for E101 (开机无数据)
        # If acquisition has been running for more than 15 seconds, and we have no data from expected clients
        time_since_start = now - self.acquisition_start_time
        
        # If no clients are connected at all in TCP mode, or serial is not receiving
        if not connected_clients:
            # If we are in serial mode or TCP is enabled
            # Let's flag a general E101 on "system"
            if time_since_start > 15.0:
                self.add_fault("system", FaultCode.E101)
        else:
            self.remove_fault("system", FaultCode.E101)
            
            # Check each connected client
            for client_id in connected_clients:
                self.register_client(client_id)
                last_seen = self.last_packet_time.get(client_id, 0.0)
                
                if last_seen == 0.0:
                    # Connected but never sent a packet
                    if time_since_start > 15.0:
                        self.add_fault(client_id, FaultCode.E101)
                else:
                    self.remove_fault(client_id, FaultCode.E101)
                    
                    # E102: Communication timeout (no packet for > 30 seconds)
                    if now - last_seen > 30.0:
                        self.add_fault(client_id, FaultCode.E102)
                    else:
                        self.remove_fault(client_id, FaultCode.E102)

        # Clean up faults for clients that are no longer in connected_clients list
        # (except "system" and clients that timed out)
        for client_id in list(self.active_faults.keys()):
            if client_id != "system" and client_id not in connected_clients:
                # If they timed out, keep E102 active
                if FaultCode.E102 in self.active_faults[client_id]:
                    continue
                self.remove_client(client_id)

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
