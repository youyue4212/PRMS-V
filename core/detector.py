#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixed detector module with safe serial communication
Prevents microcontroller deadlock by avoiding data transmission to unknown devices
"""

import sys
import glob
import time
import serial
from PyQt5.QtCore import QThread, QTimer, QMutex, pyqtSignal, Qt, QObject
from dataclasses import dataclass
from typing import Optional
import struct

from core.config import ConfigManager

CMD_FEEDBACK_SIZE = 10
DEV_MESSAGE_SIZE = 9  # 2+4+1+2 bytes from struct definition
CMD_FEEDBACK_ID = 0x4346
SPECTRUM_PACKET_ID = 0x5350
DEV_MESSAGE_ID = 0x7783  # New packet ID

@dataclass
class CmdFeedback:
    id: int
    timestamp: float
    control_code: int
    status: int
    value: int


@dataclass
class SpectrumPacket:
    id: int
    seq: int
    device_status: int
    timestamp: float
    temperature: int
    HV: int
    counter: int
    product_id: int  # 产品ID
    sen_coef: int    # 灵敏度系数(1-100)
    adc_channels: int 
    ADC: list


@dataclass
class DevMessage:
    id: int
    timestamp: int
    message_type: int
    value: int


def search_serial_devices():
    """
    Search for available serial devices with two-stage strategy:
    1. First try VID/PID detection for CH340 device (fast and precise)
    2. If not found, fallback to generic platform-specific detection

    Returns: list of available port device strings
    """
    import serial.tools.list_ports

    VID_CH340 = 0x1A86
    PID_CH340 = 0x7523

    available_ports = []

    # Stage 1: Try VID/PID detection for CH340
    for port_info in serial.tools.list_ports.comports():
        if port_info.vid == VID_CH340 and port_info.pid == PID_CH340:
            try:
                s = serial.Serial(port_info.device, timeout=0.1)
                s.close()
                available_ports.append(port_info.device)
            except (OSError, serial.SerialException):
                pass

    # If CH340 found, return immediately
    if available_ports:
        return available_ports

    # Stage 2: Fallback to generic detection
    ports = []
    if sys.platform.startswith('linux'):
        # 搜索串口树莓派专用串口设备
        # 注意：/dev/serial 是一个记录可用串口设备的目录
        # 应该对应 /dev/serial/by-id/* 和 /dev/serial/by-path/* 下的 /dev/serial 目录
        ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/rfcomm*') + \
                glob.glob('/dev/ttyAMA*') + glob.glob('/dev/ttyS*') + \
                glob.glob('/dev/serial/by-id/*') + glob.glob('/dev/serial/by-path/*')

        # 兼容模式：树莓派串口设备
        # 树莓派5上有不同的串口设备
        ports += ['/dev/ttyAMA0', '/dev/ttyAMA1', '/dev/ttyAMA2', '/dev/ttyAMA3',
                  '/dev/ttyAMA4', '/dev/ttyAMA5', '/dev/ttyAMA6', '/dev/ttyAMA7',
                  '/dev/ttyAMA8', '/dev/ttyAMA9', '/dev/ttyAMA10']

        # 去重
        ports = list(set(ports))
    elif sys.platform.startswith('win'):
        ports = ['COM' + str(i + 1) for i in range(16)]
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')

    for port in ports:
        try:
            # 检查目录，只处理文件
            import os
            if os.path.isdir(port):
                continue

            # Only test if port can be opened, don't send any data
            # Reduced timeout from 0.5 to 0.1 seconds for faster scanning
            s = serial.Serial(port, timeout=0.1)
            s.close()
            available_ports.append(port)
        except (OSError, serial.SerialException) as e:
            # 记录错误信息，忽略显示失败的端口
            pass

    # 如果没有找到可用端口，返回一个包含常见端口的默认列表供用户选择
    if not available_ports:
        # 返回可能的常见端口，基于平台目录
        if sys.platform.startswith('linux'):
            available_ports = ['/dev/ttyUSB0', '/dev/ttyAMA0', '/dev/ttyS0']
        elif sys.platform.startswith('win'):
            available_ports = ['COM1', 'COM2', 'COM3', 'COM4']
        elif sys.platform.startswith('darwin'):
            available_ports = ['/dev/tty.usbserial', '/dev/tty.usbmodem']

    return available_ports

class SerialPacketWorker(QObject):
    cmd_feedback_received = pyqtSignal(CmdFeedback)
    spectrum_packet_received = pyqtSignal(SpectrumPacket)
    dev_message_received = pyqtSignal(DevMessage)  # New signal for DevMessage
    connection_status_changed = pyqtSignal(bool, str)
    error_occurred = pyqtSignal(str)
    has_log = pyqtSignal(str, str)
    # buffer_status_changed = pyqtSignal(int)
    command_sent = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.ser = None
        self.buffer = bytearray()
        self.is_running = False
        self.mutex = QMutex()
        self.config = ConfigManager()
        self.raw_logger = None
        
        # Buffer size limit - prevent memory overflow
        self.max_buffer_size = 1024 * 1024  # 1MB maximum buffer size
        
        # Timeout control
        self.last_packet_time = time.time()
        self.timeout_threshold = 5.0  # seconds without data (align with E102)
        
        self.stats = {
            'cmd_packets': 0,
            'spectrum_packets': 0,
            'dev_messages': 0,  # New counter for DevMessage packets
            'errors': 0,
            'bytes_received': 0,
            'buffer_overflows': 0,  # Added: buffer overflow count
            'timeouts': 0  # Added: timeout count
        }

    def set_logger(self, log):
        self.raw_logger = log
    
    def get_stats(self):
        return self.stats
    
    def connect_serial(self, port: str, baudrate: int):
        max_retries = 1  # 尝试一次（原来是2次的1次），当没有USB设备时快速返回（不等待）
        retry_delay = 0.2  # 秒，快速重试延迟从0.5降到0.2
        
        for attempt in range(max_retries):
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                
                # 减少超时时间从1.0到0.5，加快连接恢复
                self.ser = serial.Serial(port, baudrate, timeout=0.5, write_timeout=0.5)
                
                # 减少等待时间从0.1降到0.05秒
                time.sleep(0.05)
                
                self.connection_status_changed.emit(True, f"Connected to {port} (attempt {attempt + 1}/{max_retries})")
                self.has_log.emit(f"Connected to {port} (attempt {attempt + 1}/{max_retries})", 'INFO')
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    self.has_log.emit(f"Connection attempt {attempt + 1} failed: {str(e)}, retrying...", 'WARNING')
                    time.sleep(retry_delay)
                else:
                    self.connection_status_changed.emit(False, f"Failed to connect after {max_retries} attempts: {str(e)}")
                    self.has_log.emit(f"Failed to connect after {max_retries} attempts: {str(e)}", 'ERROR')
                    self.error_occurred.emit(f"Serial connection error: {str(e)}")
        
        return False
    
    def disconnect_serial(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connection_status_changed.emit(False, "Disconnected")
        self.has_log.emit("Disconnected", 'INFO')
    
    def start_reading(self):
        self.is_running = True
        self.has_log.emit("Start reading...", 'DEBUG')
        # self.set_threshold
        self.read_serial_loop()
    
    def stop_reading(self):
        self.is_running = False
        self.has_log.emit("Stop.", 'INFO')
    
    def read_serial_loop(self):
        if not self.ser or not self.ser.is_open or not self.is_running:
            return
        
        try:
            # Check timeout
            current_time = time.time()
            if current_time - self.last_packet_time > self.timeout_threshold:
                self.stats['timeouts'] += 1
                self.error_occurred.emit("Serial communication timeout - no data received")
                self.last_packet_time = current_time  # Reset timeout timer
            
            if self.ser.in_waiting > 0:
                data = self.ser.read(self.ser.in_waiting)
                if data:
                    # Update last packet time
                    self.last_packet_time = time.time()

                    if self.raw_logger:
                        self.raw_logger.write(data)

                    self.mutex.lock()
                    
                    # Check buffer size limit
                    if len(self.buffer) + len(data) > self.max_buffer_size:
                        # Buffer overflow, clear buffer and log error
                        self.buffer.clear()
                        self.stats['buffer_overflows'] += 1
                        self.error_occurred.emit(f"Buffer overflow - cleared buffer (max size: {self.max_buffer_size} bytes)")
                    
                    self.buffer.extend(data)
                    self.stats['bytes_received'] += len(data)
                    buffer_size = len(self.buffer)
                    self.mutex.unlock()
                    
                    # self.buffer_status_changed.emit(buffer_size)
                    self.parse_packets()
        except Exception as e:
            self.error_occurred.emit(f"Read error: {str(e)}")
    
    
    def parse_cmd_feedback(self, data: bytes) -> Optional[CmdFeedback]:
        if len(data) < CMD_FEEDBACK_SIZE:
            return None
        
        try:
            unpacked = struct.unpack('<HIBBH', data[:CMD_FEEDBACK_SIZE])
            return CmdFeedback(
                id=unpacked[0],
                timestamp=unpacked[1],  # tick to sec
                control_code=unpacked[2],
                status=unpacked[3],
                value=unpacked[4]
            )
        except struct.error:
            return None
    
    def parse_dev_message(self, data: bytes) -> Optional[DevMessage]:
        if len(data) < DEV_MESSAGE_SIZE:
            return None
        
        try:
            # Unpack according to the struct: uint16_t id, uint32_t timestamp, uint8_t message_type, uint16_t value
            unpacked = struct.unpack('<HIBH', data[:DEV_MESSAGE_SIZE])
            return DevMessage(
                id=unpacked[0],
                timestamp=unpacked[1],  # HAL_GetTick() value
                message_type=unpacked[2],
                value=unpacked[3]
            )
        except struct.error:
            return None
    
    def find_packet_start(self) -> Optional[tuple]:
        if len(self.buffer) < 2:
            return None

        for i in range(len(self.buffer) - 1):
            try:
                packet_id = struct.unpack('<H', self.buffer[i:i+2])[0]
                if packet_id in [CMD_FEEDBACK_ID, SPECTRUM_PACKET_ID, DEV_MESSAGE_ID]:
                    return (i, packet_id)
            except struct.error:
                continue
        return None


    def get_expected_packet_size(self, packet_id: int, data: bytes = b'') -> int:
        if packet_id == CMD_FEEDBACK_ID:
            return CMD_FEEDBACK_SIZE
        elif packet_id == DEV_MESSAGE_ID:
            return DEV_MESSAGE_SIZE
        elif packet_id == SPECTRUM_PACKET_ID:
            # 只支持最新的数据包格式
            header_format = '<HHIHhHIHBBH'  # 新格式：包含product_id, sen_coef, reserved
            header_size = struct.calcsize(header_format)
            
            if len(data) >= header_size:
                try:
                    header = struct.unpack(header_format, data[:header_size])
                    adc_channels = header[10]  # 第11个字段是adc_channels
                    spectrum_size = adc_channels * 4  # 固定大小：spectrum数组：adc_channels * 4字节
                    return header_size + spectrum_size
                except struct.error:
                    return 0
            
            return 0  # not enough data yet to determine size

        return 0


    def parse_spectrum_packet(self, data: bytes) -> Optional[SpectrumPacket]:
        # 只支持最新的数据包格式
        # 格式: <HHIHhHIHBBH + 固定大小的spectrum数组
        # id, seq, timestamp, device_status, temperature, HV, counter, product_id, sen_coef, reserved, adc_channels
        
        header_format = '<HHIHhHIHBBH'  # 新格式：包含product_id, sen_coef, reserved
        header_size = struct.calcsize(header_format)
        
        if len(data) < header_size:
            return None  # 数据不够header长度
        
        try:
            header = struct.unpack(header_format, data[:header_size])
            adc_channels = header[-1]
            adc_start = header_size
            byte_length = adc_channels * 4
            
            if len(data) < header_size + byte_length:
                return None  # 数据不够spectrum长度

            # 解析spectrum数据
            adc_data = [0] * self.config.adc_channels
            if adc_channels > 0:
                # spectrum数据是连续的地址和积分值
                spectrum_format = '<' + 'H' * adc_channels * 2
                spectrum_values = struct.unpack(spectrum_format, data[header_size:header_size + byte_length])
                
                # 将spectrum数据分配到adc_data中
                for i in range(adc_channels):
                    index = spectrum_values[2*i]
                    value = spectrum_values[2*i+1]
                    if index < len(adc_data):
                        adc_data[index] = value

            return SpectrumPacket(
                id=header[0],
                seq=header[1],
                timestamp=header[2],
                device_status=header[3],
                temperature=header[4],  # 有符号值
                HV=header[5],
                counter=header[6],
                product_id=header[7],   # 产品ID
                sen_coef=header[8],     # 灵敏度系数
                adc_channels=adc_channels,
                ADC=list(adc_data)
            )
        except struct.error:
            return None  # 解析失败

    def parse_packets(self):
        self.mutex.lock()
        try:
            while True:
                packet_info = self.find_packet_start()
                # print(packet_info)
                
                if packet_info is None:
                    if len(self.buffer) > 1:
                        self.buffer = self.buffer[-1:]
                    break
                
                start_pos, packet_id = packet_info
                if start_pos > 0:
                    self.buffer = self.buffer[start_pos:]
                
                expected_size = self.get_expected_packet_size(packet_id, self.buffer)
                # print('expected size', expected_size)

                if expected_size == 0:
                    self.buffer = self.buffer[1:]
                    continue
                
                if len(self.buffer) < expected_size:
                    break
                
                packet_data = bytes(self.buffer[:expected_size])
                
                parsed_packet = None
                if packet_id == CMD_FEEDBACK_ID:
                    parsed_packet = self.parse_cmd_feedback(packet_data)
                elif packet_id == SPECTRUM_PACKET_ID:
                    parsed_packet = self.parse_spectrum_packet(packet_data)
                elif packet_id == DEV_MESSAGE_ID:
                    parsed_packet = self.parse_dev_message(packet_data)
                
                if parsed_packet:
                    self.buffer = self.buffer[expected_size:]
                    if isinstance(parsed_packet, CmdFeedback):
                        self.stats['cmd_packets'] += 1
                        self.cmd_feedback_received.emit(parsed_packet)
                    elif isinstance(parsed_packet, SpectrumPacket):
                        self.stats['spectrum_packets'] += 1
                        self.spectrum_packet_received.emit(parsed_packet)
                    elif isinstance(parsed_packet, DevMessage):
                        self.stats['dev_messages'] += 1
                        self.dev_message_received.emit(parsed_packet)
                else:
                    self.buffer = self.buffer[1:]
                    self.stats['errors'] += 1
        finally:
            self.mutex.unlock()
    
    def calculate_xor_checksum(self, data: list) -> int:
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum
    
    def is_serial_ready(self):
        return self.ser and self.ser.is_open
    
    def try_connection(self):
        """Try to establish connection and return status - optimized for faster failure when no USB device is connected"""
        if self.ser and self.ser.is_open:
            return True
        if self.config.device:
            return bool(self.connect_serial(self.config.device, self.config.baudrate))
        # 不自动改连其它 COM，避免工控机多串口时采到错误设备
        return False

    def send_command(self, command_data: list, description: str = ""):
        if not self.ser or not self.ser.is_open:
            self.error_occurred.emit("Serial port not connected")
            return False
        
        max_retries = 2
        retry_delay = 0.1  # 秒
        
        for attempt in range(max_retries):
            try:
                command_bytes = bytes(command_data)
                self.ser.write(command_bytes)
                
                # Check if this is a parameter setting command (requires Flash write time)
                # Control codes: 0x07=HV set, 0x08=Threshold set, 0x0C=Sensitivity coefficient set, 0x0E=Product ID set
                if len(command_data) >= 4:
                    control_code = command_data[3]
                    if control_code in [0x07, 0x08, 0x0C, 0x0E, 0x14]:
                        # Parameter setting command, needs longer wait time for Flash write completion
                        time.sleep(0.15)  # 150ms wait for Flash write
                        self.has_log.emit(f"Parameter setting command 0x{control_code:02X} sent, waiting for Flash write completion...", 'INFO')
                    else:
                        # Other commands, short wait time
                        time.sleep(0.05)
                else:
                    # Default wait time
                    time.sleep(0.05)
                
                self.command_sent.emit(f"Sent: {description} - {' '.join(f'0x{b:02X}' for b in command_data)} (attempt {attempt + 1}/{max_retries})")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    self.has_log.emit(f"Command send attempt {attempt + 1} failed: {str(e)}, retrying...", 'WARNING')
                    time.sleep(retry_delay)
                else:
                    self.error_occurred.emit(f"Command send error after {max_retries} attempts: {str(e)}")
                    self.has_log.emit(f"Command send error after {max_retries} attempts: {str(e)}", 'ERROR')
        
        return False
    
    def set_input_signal_source(self, from_internal=True):
        # Fixed command format: according to user description, 6th byte should be 0x01 for external, 0x00 for internal
        # Command format: 0x55 0xAA 0x03 0x05 0x01 [source] [checksum]
        # source: 0x01 = external, 0x00 = internal
        source_byte = 0x00 if from_internal else 0x01
        data = [0x55, 0xAA, 0x03, 0x05, 0x01, source_byte]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set input signal source to {'internal' if from_internal else 'external'}")

    def control_single_relay(self, relay_num: int, state: bool):
        """Control single relay (relay_num: 0-2, state: True=ON, False=OFF)"""
        # Command format: 0x55 0xAA 0x03 0x06 [relay_num] [state] [checksum]
        # According to C macro: RELAY_CTRL_CODE = 0x06
        if relay_num < 0 or relay_num > 2:
            self.error_occurred.emit(f"Invalid relay number: {relay_num}, must be 0-2")
            return False
        state_byte = 0x01 if state else 0x00
        data = [0x55, 0xAA, 0x03, 0x06, relay_num, state_byte]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set relay {relay_num} to {'ON' if state else 'OFF'}")

    def control_multiple_relays(self, relay_mask: int):
        """Control multiple relays using bitmask (bit0: relay0, bit1: relay1, bit2: relay2)"""
        # Command format: 0x55 0xAA 0x03 0x11 [relay_mask] 0x00 [checksum]
        if relay_mask < 0 or relay_mask > 0x07:
            self.error_occurred.emit(f"Invalid relay mask: 0x{relay_mask:02X}, must be 0x00-0x07")
            return False
        data = [0x55, 0xAA, 0x03, 0x11, relay_mask, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set relay mask to 0x{relay_mask:02X}")

    def set_sensitivity_coefficient(self, coefficient):
        """Set alarm sensitivity M (1.0~10.0); TCP 0x0C 与固件一致（×10 或整数 1~10）。"""
        from core.sensitivity_m import clamp_m, encode_0x0c_bytes, format_m_display

        m = clamp_m(coefficient)
        b4, b5 = encode_0x0c_bytes(m)
        data = [0x55, 0xAA, 0x03, 0x0C, b4, b5]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set sensitivity M to {format_m_display(m)}")

    def read_sensitivity_coefficient(self, flag: bool):
        """Read alarm sensitivity coefficient (NOTE: Primary source is SpectrumPacket.sen_coef)"""
        # Command format: 0x55 0xAA 0x03 0x0F [flag] 0x00 [checksum]
        flag_byte = 0x01 if flag else 0x00
        data = [0x55, 0xAA, 0x03, 0x0F, flag_byte, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Read sensitivity coefficient {flag}"
        return self.send_command(data, description)

    def set_product_id(self, product_id: int):
        """Set product ID (0-65535)"""
        # Command format: 0x55 0xAA 0x03 0x0E [id_high] [id_low] [checksum]
        if product_id < 0 or product_id > 65535:
            self.error_occurred.emit(f"Invalid product ID: {product_id}, must be 0-65535")
            return False
        id_low = product_id & 0xFF
        id_high = (product_id >> 8) & 0xFF
        data = [0x55, 0xAA, 0x03, 0x0E, id_high, id_low]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set product ID to {product_id}")

    def read_product_id(self, flag: bool):
        """Read product ID (NOTE: Primary source is SpectrumPacket.product_id)"""
        # Command format: 0x55 0xAA 0x03 0x0D [flag] 0x00 [checksum]
        flag_byte = 0x01 if flag else 0x00
        data = [0x55, 0xAA, 0x03, 0x0D, flag_byte, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Read product ID {flag}"    
        return self.send_command(data, description)

    def read_relay_status(self, flag: bool):
        """Read relay status (returns bitmask of relay states) (NOTE: Primary source is SpectrumPacket.device_status bits 0-2)"""
        # Command format: 0x55 0xAA 0x03 0x12 [flag] 0x00 [checksum]
        flag_byte = 0x01 if flag else 0x00
        data = [0x55, 0xAA, 0x03, 0x12, flag_byte, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Read relay status {flag}"
        return self.send_command(data, description)
    def read_alarm_status(self, flag: bool):
        """Read alarm status (returns bit4 of device status) (NOTE: Primary source is SpectrumPacket.device_status bit 4)"""
        # Command format: 0x55 0xAA 0x03 0x13 [flag] 0x00 [checksum]
        flag_byte = 0x01 if flag else 0x00
        data = [0x55, 0xAA, 0x03, 0x13, flag_byte, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Read alarm status {flag}"
        return self.send_command(data, description)
    def set_high_voltage(self, voltage: float):
        #voltage_raw = int(voltage * 100)//�����֮ǰ�İ汾����Ϊ���ڵĵ�ѹ��λ��0.1V
        voltage_raw = int(voltage )   
        high_byte = (voltage_raw >> 8) & 0xFF
        low_byte = voltage_raw & 0xFF
        data = [0x55, 0xAA, 0x03, 0x07, high_byte, low_byte]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Set HV to 0x{voltage_raw:04X} ({voltage_raw})"
        return self.send_command(data, description)

    def set_threshold(self, threshold: int):
        level_raw = int(threshold * 100)
        high_byte = (level_raw >> 8) & 0xFF
        low_byte = level_raw & 0xFF
        data = [0x55, 0xAA, 0x03, 0x08, high_byte, low_byte]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Set Threshold to 0x{level_raw:04X} ({level_raw})"
        return self.send_command(data, description)
    def set_gain_stabilizer_flag(self, flag: bool):
        data = [0x55, 0xAA, 0x03, 0x0B, 0x01 if flag else 0x00, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Gain stabilizer set to {flag}"
        return self.send_command(data, description)
    def set_operation_mode(self, mode: str):
        # NOMINAL or standby
        # standby: no HV
        data = [0x55, 0xAA, 0x03, 0x09, 0x00 if mode == 'NOMINAL' else 0x01, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = "Operation"
        return self.send_command(data, description)

    def reset_spectrum_data(self):
        """Reset spectrum data (clear histogram)"""
        # Command format: 0x55 0xAA 0x03 0x0A [checksum]
        data = [0x55, 0xAA, 0x01, 0x0A]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, "Reset spectrum data")

    def reset_factory_defaults(self):
        """Restore probe defaults (HV / trigger / sen_coef). Command 0x14."""
        data = [0x55, 0xAA, 0x03, 0x14, 0xA5, 0x5A]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, "Reset factory defaults (0x14)")

    def control_multiple_leds(self, led_mask: int):
        """Control multiple LEDs using bitmask (bit0: LED0, bit1: LED1, bit2: LED2, bit3: LED3)"""
        # Command format: 0x55 0xAA 0x03 0x10 [led_mask] 0x00 [checksum]
        if led_mask < 0 or led_mask > 0x0F:
            self.error_occurred.emit(f"Invalid LED mask: 0x{led_mask:02X}, must be 0x00-0x0F")
            return False
        data = [0x55, 0xAA, 0x03, 0x10, led_mask, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set LED mask to 0x{led_mask:02X}")