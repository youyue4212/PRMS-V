#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TCP/IP detector module for receiving data over TCP/IP instead of serial port.
Provides the same interface as SerialPacketWorker for seamless integration.
Version supporting multiple client connections.
"""

import sys
import time
import socket
import threading
from PyQt5.QtCore import QThread, QTimer, QMutex, pyqtSignal, Qt, QObject
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import struct

from core.config import ConfigManager

# Reuse packet definitions and constants from detector module
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
    product_id: int  # Added: product ID
    sen_coef: int    # Added: alarm sensitivity coefficient (1-100)
    adc_channels: int 
    ADC: list


@dataclass
class ClientInfo:
    """Client information data structure"""
    client_id: str
    ip_address: str
    port: int
    connect_time: float
    last_active: float
    bytes_received: int
    packets_received: int


@dataclass
class DevMessage:
    id: int
    timestamp: int
    message_type: int
    value: int


class TcpPacketWorker(QObject):
    """
    TCP/IP worker class that provides the same interface as SerialPacketWorker
    but communicates over TCP/IP instead of serial port.
    Version supporting multiple client connections.
    """
    cmd_feedback_received = pyqtSignal(CmdFeedback)
    spectrum_packet_received = pyqtSignal(SpectrumPacket, str)  # Added client_id parameter
    dev_message_received = pyqtSignal(DevMessage)  # New signal for DevMessage
    connection_status_changed = pyqtSignal(bool, str)
    error_occurred = pyqtSignal(str)
    has_log = pyqtSignal(str, str)
    command_sent = pyqtSignal(str)
    client_connected = pyqtSignal(str)  # New signal: client connected
    client_disconnected = pyqtSignal(str)  # New signal: client disconnected
    
    def __init__(self):
        super().__init__()
        self.server_socket = None  # Listening socket (server mode)
        self.client_sockets = {}  # Client socket dictionary {client_id: socket}
        self.client_buffers = {}  # Buffer for each client {client_id: bytearray}
        self.client_infos = {}    # Client information dictionary {client_id: ClientInfo}
        self.client_counter = 0  # Client counter for generating unique IDs
        self.buffer = bytearray()  # Main buffer (backward compatibility)
        self.is_running = False
        self.mutex = QMutex()
        self.config = ConfigManager()
        self.raw_logger = None
        
        # Initialize is_server_mode attribute
        self.is_server_mode = False
        
        # Buffer size limit - prevent memory overflow
        self.max_buffer_size = 1024 * 1024  # 1MB maximum buffer size
        
        # Timeout control
        self.last_packet_time = time.time()
        self.timeout_threshold = 30.0  # 30 second timeout
        
        # TCP socket settings
        self.receive_buffer_size = 4096  # Size of receive buffer
        
        self.stats = {
            'cmd_packets': 0,
            'spectrum_packets': 0,
            'dev_messages': 0,  # New counter for DevMessage packets
            'errors': 0,
            'bytes_received': 0,
            'buffer_overflows': 0,  # Added: buffer overflow count
            'timeouts': 0,  # Added: timeout count
            'clients_connected': 0,  # Added: connected clients count
            'clients_disconnected': 0  # Added: disconnected clients count
        }

    def set_logger(self, logger):
        """
        Set raw logger for packet logging
        Args:
            logger: RawLogger instance
        """
        self.raw_logger = logger
    
    def get_stats(self):
        return self.stats
    
    def connect_tcp(self, host: str, port: int, mode: str = "client"):
        """
        Connect to TCP server or start TCP server
        Args:
            host: TCP server hostname or IP address (for client mode) or bind address (for server mode)
            port: TCP server port
            mode: "client" to connect as client, "server" to listen as server
        Returns:
            bool: True if connection successful, False otherwise
        """
        max_retries = 3
        retry_delay = 0.5  # seconds
        
        self.has_log.emit(f"connect_tcp called with host={host}, port={port}, mode={mode}", 'DEBUG')
        
        for attempt in range(max_retries):
            try:
                # Clean up existing connections
                self._cleanup_all_sockets()
                
                if mode == "client":
                    # Client mode: connect to server
                    self.has_log.emit(f"Creating client socket to connect to {host}:{port}", 'DEBUG')
                    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    client_socket.settimeout(5.0)  # Connection timeout
                    
                    # Connect to server
                    self.has_log.emit(f"Attempting to connect to {host}:{port} (attempt {attempt + 1}/{max_retries})", 'DEBUG')
                    client_socket.connect((host, port))
                    
                    # Set socket to non-blocking for reading
                    client_socket.setblocking(False)
                    
                    # Add to client list
                    client_id = f"client_{self.client_counter}"
                    self.client_counter += 1
                    self.client_sockets[client_id] = client_socket
                    self.client_buffers[client_id] = bytearray()
                    self.stats['clients_connected'] += 1
                    
                    self.connection_status_changed.emit(True, f"Connected to {host}:{port} (attempt {attempt + 1}/{max_retries})")
                    self.has_log.emit(f"Connected to {host}:{port} (attempt {attempt + 1}/{max_retries})", 'INFO')
                    self.client_connected.emit(client_id)
                    return True
                else:
                    # Server mode: listen for connections
                    self.has_log.emit(f"Creating server socket to listen on {host}:{port}", 'DEBUG')
                    self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.server_socket.settimeout(5.0)  # Accept timeout
                    
                    # Bind to address and port
                    self.has_log.emit(f"Binding to {host}:{port}", 'DEBUG')
                    self.server_socket.bind((host, port))
                    self.server_socket.listen(5)  # Listen for up to 5 connections
                    
                    # Set socket to non-blocking for accepting connections
                    self.server_socket.setblocking(False)
                    
                    self.connection_status_changed.emit(True, f"Listening on {host}:{port} (attempt {attempt + 1}/{max_retries})")
                    self.has_log.emit(f"Listening on {host}:{port} (attempt {attempt + 1}/{max_retries})", 'INFO')
                    self.is_server_mode = True
                    self.has_log.emit(f"Server socket created: {self.server_socket}, is_server_mode={self.is_server_mode}", 'DEBUG')
                    return True
                    
            except socket.timeout:
                error_msg = f"Connection timeout to {host}:{port}"
                if attempt < max_retries - 1:
                    self.has_log.emit(f"Connection attempt {attempt + 1} failed: {error_msg}, retrying...", 'WARNING')
                    time.sleep(retry_delay)
                else:
                    self.connection_status_changed.emit(False, f"Failed to connect after {max_retries} attempts: {error_msg}")
                    self.has_log.emit(f"Failed to connect after {max_retries} attempts: {error_msg}", 'ERROR')
                    self.error_occurred.emit(f"TCP connection error: {error_msg}")
            except Exception as e:
                if attempt < max_retries - 1:
                    self.has_log.emit(f"Connection attempt {attempt + 1} failed: {str(e)}, retrying...", 'WARNING')
                    time.sleep(retry_delay)
                else:
                    self.connection_status_changed.emit(False, f"Failed to connect after {max_retries} attempts: {str(e)}")
                    self.has_log.emit(f"Failed to connect after {max_retries} attempts: {str(e)}", 'ERROR')
                    self.error_occurred.emit(f"TCP connection error: {str(e)}")
        
        self.has_log.emit(f"connect_tcp failed after {max_retries} attempts", 'ERROR')
        return False
    
    def _cleanup_all_sockets(self):
        """Clean up all socket connections"""
        # Close all client sockets
        for client_id, sock in list(self.client_sockets.items()):
            try:
                sock.close()
                self.client_disconnected.emit(client_id)
            except:
                pass
        self.client_sockets.clear()
        self.client_buffers.clear()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None
    
    def disconnect_tcp(self):
        """Disconnect from TCP server"""
        self._cleanup_all_sockets()
        self.connection_status_changed.emit(False, "Disconnected")
        self.has_log.emit("Disconnected", 'INFO')
    
    def start_reading(self):
        """Start reading from TCP socket"""
        self.is_running = True
        self.has_log.emit("Start reading...", 'DEBUG')
    
    def stop_reading(self):
        """Stop reading from TCP socket"""
        self.is_running = False
        self.has_log.emit("Stop.", 'INFO')
    
    def read_tcp_loop(self):
        """
        Read data from TCP socket - should be called from QTimer
        This method replaces read_serial_loop
        Version supporting multiple client connections
        """
        if not self.is_running:
            self.has_log.emit(f"Not running: is_running={self.is_running}", 'DEBUG')
            return
        
        try:
            # Check timeout
            current_time = time.time()
            if current_time - self.last_packet_time > self.timeout_threshold:
                self.stats['timeouts'] += 1
                self.error_occurred.emit("TCP communication timeout - no data received")
                self.last_packet_time = current_time  # Reset timeout timer
            
            # For server mode: accept incoming connections
            if hasattr(self, 'is_server_mode') and self.is_server_mode and self.server_socket:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    client_id = f"client_{self.client_counter}_{client_address[0]}:{client_address[1]}"
                    self.client_counter += 1
                    
                    # Set socket to non-blocking
                    client_socket.setblocking(False)
                    
                    # Add to client list
                    self.client_sockets[client_id] = client_socket
                    self.client_buffers[client_id] = bytearray()
                    
                    # Create client info
                    client_info = ClientInfo(
                        client_id=client_id,
                        ip_address=client_address[0],
                        port=client_address[1],
                        connect_time=time.time(),
                        last_active=time.time(),
                        bytes_received=0,
                        packets_received=0
                    )
                    self.client_infos[client_id] = client_info
                    
                    self.stats['clients_connected'] += 1
                    
                    self.has_log.emit(f"Accepted connection from {client_address} as {client_id}", 'INFO')
                    self.client_connected.emit(client_id)
                    self.connection_status_changed.emit(True, f"{len(self.client_sockets)} client(s) connected")
                    
                except socket.error as e:
                    # No incoming connections (non-blocking socket)
                    if e.errno != socket.EWOULDBLOCK and e.errno != socket.EAGAIN:
                        self.has_log.emit(f"Socket accept error: {str(e)}", 'ERROR')
            
            # Try to receive data from all clients
            disconnected_clients = []
            for client_id, client_socket in list(self.client_sockets.items()):
                try:
                    data = client_socket.recv(self.receive_buffer_size)
                    if data:
                        # Log raw data in hex format for debugging
                        hex_data = ' '.join(f'{b:02X}' for b in data[:min(32, len(data))])
                        if len(data) > 32:
                            hex_data += f' ... (+{len(data)-32} more bytes)'
                        
                        self.has_log.emit(f"Received {len(data)} bytes from {client_id}: {hex_data}", 'DEBUG')
                        # Update last packet time
                        self.last_packet_time = time.time()

                        # Log raw data if logger is enabled
                        if self.raw_logger:
                            self.raw_logger.write(data)

                        self.mutex.lock()
                        self.stats['bytes_received'] += len(data)

                        if client_id in self.client_buffers:
                            client_buffer = self.client_buffers[client_id]
                            if len(client_buffer) + len(data) > self.max_buffer_size:
                                client_buffer.clear()
                                self.stats['buffer_overflows'] += 1
                                self.error_occurred.emit(
                                    f"Buffer overflow for {client_id} - cleared buffer (max size: {self.max_buffer_size} bytes)"
                                )
                            client_buffer.extend(data)

                        if client_id in self.client_infos:
                            self.client_infos[client_id].bytes_received += len(data)
                            self.client_infos[client_id].last_active = time.time()

                        self.mutex.unlock()
                        
                        # Parse packets from this client's own buffer.
                        self.parse_packets_with_client_id(client_id)
                    else:
                        # No data received (empty bytes) - connection closed
                        disconnected_clients.append(client_id)
                        
                except socket.error as e:
                    # No data available (non-blocking socket)
                    if e.errno != socket.EWOULDBLOCK and e.errno != socket.EAGAIN:
                        self.has_log.emit(f"Socket error from {client_id}: {str(e)}", 'ERROR')
                        disconnected_clients.append(client_id)
            
            # Remove disconnected clients
            for client_id in disconnected_clients:
                self._remove_client(client_id)
                
        except Exception as e:
            self.error_occurred.emit(f"TCP read error: {str(e)}")
    
    def _remove_client(self, client_id):
        """Remove disconnected client"""
        if client_id in self.client_sockets:
            try:
                self.client_sockets[client_id].close()
            except:
                pass
            del self.client_sockets[client_id]
            
        if client_id in self.client_buffers:
            del self.client_buffers[client_id]
            
        if client_id in self.client_infos:
            del self.client_infos[client_id]
            
        self.stats['clients_disconnected'] += 1
        self.has_log.emit(f"Client {client_id} disconnected", 'INFO')
        self.client_disconnected.emit(client_id)
        connected = len(self.client_sockets) > 0
        message = f"{len(self.client_sockets)} client(s) connected" if connected else "Listening, no clients connected"
        self.connection_status_changed.emit(connected, message)
    
    def get_client_info(self, client_id: str) -> Optional[ClientInfo]:
        """Get client information by client ID"""
        return self.client_infos.get(client_id)
    
    def get_all_client_infos(self) -> List[ClientInfo]:
        """Get information for all connected clients"""
        return list(self.client_infos.values())
    
    def get_client_list(self) -> List[str]:
        """Get list of all connected client IDs"""
        return list(self.client_sockets.keys())
    
    def send_command_to_client(self, client_id: str, command_type: str, command_value, description: str = "") -> bool:
        """
        Send command to specific client
        Args:
            client_id: ID of the client to send command to
            command_type: Type of command ('set_hv', 'set_threshold', 'set_operation_mode', 
                          'set_product_id', 'set_sensitivity_coefficient', 'control_single_relay')
            command_value: Value for the command (float for HV, int for threshold, etc.)
            description: Description for logging
        Returns:
            bool: True if command was sent successfully, False otherwise
        """
        if client_id not in self.client_sockets:
            self.error_occurred.emit(f"Client {client_id} not found")
            return False
        
        # Convert command type to appropriate command data
        command_data = []
        
        if command_type == 'set_hv':
            # Set high voltage command
            voltage = float(command_value)
            voltage_raw = int(voltage)
            high_byte = (voltage_raw >> 8) & 0xFF
            low_byte = voltage_raw & 0xFF
            command_data = [0x55, 0xAA, 0x03, 0x07, high_byte, low_byte]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set HV to {voltage}V"
            
        elif command_type == 'set_threshold':
            # Set threshold command
            threshold = int(command_value)
            level_raw = int(threshold * 100)
            high_byte = (level_raw >> 8) & 0xFF
            low_byte = level_raw & 0xFF
            command_data = [0x55, 0xAA, 0x03, 0x08, high_byte, low_byte]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set threshold to {threshold}mV"
            
        elif command_type == 'set_operation_mode':
            # Set operation mode command
            mode = str(command_value)
            mode_byte = 0x00 if mode == 'NOMINAL' else 0x01
            command_data = [0x55, 0xAA, 0x03, 0x09, mode_byte, 0x00]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set operation mode to {mode}"
            
        elif command_type == 'set_product_id':
            # Set product ID command
            product_id = int(command_value)
            if product_id < 0 or product_id > 65535:
                self.error_occurred.emit(f"Invalid product ID: {product_id}, must be 0-65535")
                return False
            id_low = product_id & 0xFF
            id_high = (product_id >> 8) & 0xFF
            command_data = [0x55, 0xAA, 0x03, 0x0E, id_high, id_low]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set product ID to {product_id}"
            
        elif command_type == 'set_sensitivity_coefficient':
            # Set sensitivity coefficient command
            coefficient = int(command_value)
            if coefficient < 1 or coefficient > 100:
                self.error_occurred.emit(f"Invalid sensitivity coefficient: {coefficient}, must be 1-100")
                return False
            command_data = [0x55, 0xAA, 0x03, 0x0C, coefficient, 0x00]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set sensitivity coefficient to {coefficient}"
            
        elif command_type == 'control_single_relay':
            # Control single relay command
            if isinstance(command_value, tuple) and len(command_value) == 2:
                relay_num, state = command_value
            else:
                self.error_occurred.emit(f"Invalid relay command format: {command_value}")
                return False
                
            if relay_num < 0 or relay_num > 2:
                self.error_occurred.emit(f"Invalid relay number: {relay_num}, must be 0-2")
                return False
            state_byte = 0x01 if state else 0x00
            command_data = [0x55, 0xAA, 0x03, 0x06, relay_num, state_byte]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = f"Set relay {relay_num} to {'ON' if state else 'OFF'}"
            
        else:
            self.error_occurred.emit(f"Unknown command type: {command_type}")
            return False
        
        max_retries = 2
        retry_delay = 0.1  # seconds
        
        for attempt in range(max_retries):
            try:
                command_bytes = bytes(command_data)
                self.client_sockets[client_id].sendall(command_bytes)
                
                # Wait a bit for command to be processed
                time.sleep(0.05)
                
                self.command_sent.emit(f"Sent to {client_id}: {description} - {' '.join(f'0x{b:02X}' for b in command_data)} (attempt {attempt + 1}/{max_retries})")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    self.has_log.emit(f"Command send to {client_id} attempt {attempt + 1} failed: {str(e)}, retrying...", 'WARNING')
                    time.sleep(retry_delay)
                else:
                    self.error_occurred.emit(f"Command send to {client_id} error after {max_retries} attempts: {str(e)}")
                    self.has_log.emit(f"Command send to {client_id} error after {max_retries} attempts: {str(e)}", 'ERROR')
        
        return False
    
    # The following methods are identical to SerialPacketWorker
    # since packet parsing is the same regardless of transport
    
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

    def find_packet_start_in_buffer(self, buffer: bytearray) -> Optional[tuple]:
        """Find a packet start inside a specific client's buffer."""
        if len(buffer) < 2:
            return None

        for i in range(len(buffer) - 1):
            try:
                packet_id = struct.unpack('<H', buffer[i:i+2])[0]
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
            # Only support new packet format
            header_format = '<HHIHhHIHBBH'  # New format: includes product_id, sen_coef, reserved
            header_size = struct.calcsize(header_format)
            
            if len(data) >= header_size:
                try:
                    header = struct.unpack(header_format, data[:header_size])
                    adc_channels = header[10]  # 11th field is adc_channels
                    spectrum_size = adc_channels * 4  # Fixed-size spectrum array: adc_channels * 4 bytes
                    return header_size + spectrum_size
                except struct.error:
                    return 0
            
            return 0  # not enough data yet to determine size

        return 0

    def parse_spectrum_packet(self, data: bytes) -> Optional[SpectrumPacket]:
        # Only support new packet format
        # Format: <HHIHhHIHBBH + fixed-size spectrum array
        # id, seq, timestamp, device_status, temperature, HV, counter, product_id, sen_coef, reserved, adc_channels
        
        header_format = '<HHIHhHIHBBH'  # New format: includes product_id, sen_coef, reserved
        header_size = struct.calcsize(header_format)
        
        if len(data) < header_size:
            return None  # Not enough data for header
        
        try:
            header = struct.unpack(header_format, data[:header_size])
            adc_channels = header[-1]
            adc_start = header_size
            byte_length = adc_channels * 4
            
            if len(data) < header_size + byte_length:
                return None  # Not enough data for spectrum

            # Parse spectrum data
            adc_data = [0] * self.config.adc_channels
            if adc_channels > 0:
                # Spectrum array contains alternating channel index and count value
                spectrum_format = '<' + 'H' * adc_channels * 2
                spectrum_values = struct.unpack(spectrum_format, data[header_size:header_size + byte_length])
                
                # Fill spectrum data into adc_data
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
                temperature=header[4],  # Signed value
                HV=header[5],
                counter=header[6],
                product_id=header[7],   # Product ID
                sen_coef=header[8],     # Alarm sensitivity coefficient
                adc_channels=adc_channels,
                ADC=list(adc_data)
            )
        except struct.error:
            return None  # Parsing failed

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
                        # Emit packet with client_id information
                        # For now, we emit None as client_id (will be updated later)
                        self.spectrum_packet_received.emit(parsed_packet, None)
                    elif isinstance(parsed_packet, DevMessage):
                        self.stats['dev_messages'] += 1
                        self.dev_message_received.emit(parsed_packet)
                else:
                    self.buffer = self.buffer[1:]
                    self.stats['errors'] += 1
        finally:
            self.mutex.unlock()
    
    def parse_packets_with_client_id(self, client_id: str):
        """
        Parse packets from the specified client's buffer and emit them with client_id
        This is used when we know which client the data came from
        """
        self.mutex.lock()
        try:
            if client_id not in self.client_buffers:
                return

            client_buffer = self.client_buffers[client_id]
            while True:
                packet_info = self.find_packet_start_in_buffer(client_buffer)
                
                if packet_info is None:
                    if len(client_buffer) > 1:
                        del client_buffer[:-1]
                    break
                
                start_pos, packet_id = packet_info
                if start_pos > 0:
                    del client_buffer[:start_pos]
                
                expected_size = self.get_expected_packet_size(packet_id, client_buffer)

                if expected_size == 0:
                    del client_buffer[:1]
                    continue
                
                if len(client_buffer) < expected_size:
                    break
                
                packet_data = bytes(client_buffer[:expected_size])
                
                parsed_packet = None
                if packet_id == CMD_FEEDBACK_ID:
                    parsed_packet = self.parse_cmd_feedback(packet_data)
                elif packet_id == SPECTRUM_PACKET_ID:
                    parsed_packet = self.parse_spectrum_packet(packet_data)
                elif packet_id == DEV_MESSAGE_ID:
                    parsed_packet = self.parse_dev_message(packet_data)
                
                if parsed_packet:
                    del client_buffer[:expected_size]
                    if isinstance(parsed_packet, CmdFeedback):
                        self.stats['cmd_packets'] += 1
                        self.cmd_feedback_received.emit(parsed_packet)
                    elif isinstance(parsed_packet, SpectrumPacket):
                        self.stats['spectrum_packets'] += 1
                        # Update client info
                        if client_id in self.client_infos:
                            self.client_infos[client_id].packets_received += 1
                            self.client_infos[client_id].last_active = time.time()
                        # Emit packet with client_id
                        self.spectrum_packet_received.emit(parsed_packet, client_id)
                    elif isinstance(parsed_packet, DevMessage):
                        self.stats['dev_messages'] += 1
                        self.dev_message_received.emit(parsed_packet)
                else:
                    del client_buffer[:1]
                    self.stats['errors'] += 1
        finally:
            self.mutex.unlock()
    
    def calculate_xor_checksum(self, data: list) -> int:
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum
    
    def is_tcp_ready(self):
        """Check if TCP socket is connected and ready"""
        # Return True if there are client connections
        if len(self.client_sockets) > 0:
            self.has_log.emit(f"TCP ready: {len(self.client_sockets)} client(s) connected", 'DEBUG')
            return True
        
        # Also return True if in server mode and listening
        if hasattr(self, 'is_server_mode') and self.is_server_mode and self.server_socket:
            self.has_log.emit(f"TCP ready: Server mode listening on {self.server_socket.getsockname()}", 'DEBUG')
            return True
            
        self.has_log.emit(f"TCP not ready: is_server_mode={hasattr(self, 'is_server_mode')}, server_socket={self.server_socket}, client_sockets={len(self.client_sockets)}", 'DEBUG')
        return False
    
    def try_connection(self):
        """Try to establish connection and return status"""
        if self.is_tcp_ready():
            return True
        else:
            # Try to reconnect based on configuration
            # Note: This method doesn't have access to config, so we'll just return current status
            # The actual reconnection should be handled by ensure_connection_ready in UIBase
            return False
    
    def send_command(self, command_data: list, description: str = ""):
        """
        Send command over TCP socket
        Note: In case of multiple clients, command will be sent to all clients
        Args:
            command_data: List of bytes to send
            description: Description for logging
        Returns:
            bool: True if command was sent successfully to at least one client, False otherwise
        """
        if not self.client_sockets:
            self.error_occurred.emit("No TCP clients connected")
            return False
        
        max_retries = 2
        retry_delay = 0.1  # seconds
        
        success_count = 0
        total_clients = len(self.client_sockets)
        
        for client_id, client_socket in self.client_sockets.items():
            for attempt in range(max_retries):
                try:
                    command_bytes = bytes(command_data)
                    client_socket.sendall(command_bytes)
                    
                    # Wait a bit for command to be processed
                    time.sleep(0.05)
                    
                    self.command_sent.emit(f"Sent to {client_id}: {description} - {' '.join(f'0x{b:02X}' for b in command_data)} (attempt {attempt + 1}/{max_retries})")
                    success_count += 1
                    break  # Successfully sent to this client, break out of retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.has_log.emit(f"Command send to {client_id} attempt {attempt + 1} failed: {str(e)}, retrying...", 'WARNING')
                        time.sleep(retry_delay)
                    else:
                        self.error_occurred.emit(f"Command send to {client_id} error after {max_retries} attempts: {str(e)}")
                        self.has_log.emit(f"Command send to {client_id} error after {max_retries} attempts: {str(e)}", 'ERROR')
        
        # Return True if at least one client received the command
        return success_count > 0
    
    # Command methods (identical to SerialPacketWorker)
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

    def set_sensitivity_coefficient(self, coefficient: int):
        """Set alarm sensitivity coefficient (1-100)"""
        # Command format: 0x55 0xAA 0x03 0x0C [coefficient] 0x00  [checksum]
        if coefficient < 1 or coefficient > 100:
            self.error_occurred.emit(f"Invalid sensitivity coefficient: {coefficient}, must be 1-100")
            return False
        data = [0x55, 0xAA, 0x03, 0x0C, coefficient, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, f"Set sensitivity coefficient to {coefficient}")

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
        #voltage_raw = int(voltage * 100)
        voltage_raw = int(voltage)
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
        mode_byte = 0x00 if mode == 'NOMINAL' else 0x01
        data = [0x55, 0xAA, 0x03, 0x09, mode_byte, 0x00]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        description = f"Set operation mode to {mode}"
        return self.send_command(data, description)

    def reset_spectrum_data(self):
        """Reset spectrum data (clear histogram)"""
        # Command format: 0x55 0xAA 0x03 0x0A [checksum]
        data = [0x55, 0xAA, 0x01, 0x0A]
        checksum = self.calculate_xor_checksum(data)
        data.append(checksum)
        return self.send_command(data, "Reset spectrum data")

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
