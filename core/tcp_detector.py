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
from core.master_summary import (
    MASTER_PACKET_HEADER,
    MASTER_PACKET_SIZE,
    MasterSummaryPacket,
    explain_master_summary_reject,
    find_valid_master_frame_offset,
    is_master_frame_candidate,
    parse_master_summary,
)

# Reuse packet definitions and constants from detector module
CMD_FEEDBACK_SIZE = 10
DEV_MESSAGE_SIZE = 9  # 2+4+1+2 bytes from struct definition
CMD_FEEDBACK_ID = 0x4346
SPECTRUM_PACKET_ID = 0x5350
DEV_MESSAGE_ID = 0x7783  # New packet ID
# Master L2 summary header 0xA55A (wire 5A A5)


def _enable_tcp_keepalive(sock: socket.socket,
                          idle: int = 3, interval: int = 1, count: int = 3) -> None:
    """Detect dead peers faster after cable unplug (Linux/Windows best-effort)."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    # Linux
    for opt, val in (
        (getattr(socket, "TCP_KEEPIDLE", None), idle),
        (getattr(socket, "TCP_KEEPINTVL", None), interval),
        (getattr(socket, "TCP_KEEPCNT", None), count),
    ):
        if opt is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, opt, val)
        except OSError:
            pass
    # Windows
    if hasattr(sock, "ioctl") and hasattr(socket, "SIO_KEEPALIVE_VALS"):
        try:
            # (on/off, keepalivetime ms, keepaliveinterval ms)
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))
        except OSError:
            pass

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
    master_summary_received = pyqtSignal(object, str)  # MasterSummaryPacket, client_id
    # Emitted when a client is identified as master (L2 header seen), even before CRC OK
    master_link_seen = pyqtSignal(str)  # client_id
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
        self.master_client_id = None  # last client that sent valid L2 summary
        self._last_l2_online_mask = None
        self._last_l2_timestamp_ms = None
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
        
        # Timeout control（与诊断 E102 一致，加快掉线提醒）
        self.last_packet_time = time.time()
        self.timeout_threshold = 5.0  # seconds without data
        self.timeout_debounce_sec = 1.2
        self.last_timeout_meta = {}
        self._last_link_event = {}
        
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

    @staticmethod
    def _socket_error_detail(err: Exception) -> str:
        parts = []
        winerror = getattr(err, "winerror", None)
        errno = getattr(err, "errno", None)
        if winerror is not None:
            parts.append(f"winerror={winerror}")
        if errno is not None:
            parts.append(f"errno={errno}")
        parts.append(str(err))
        return " ".join(p for p in parts if p).strip()

    @staticmethod
    def _is_would_block_error(err: Exception) -> bool:
        winerror = getattr(err, "winerror", None)
        errno = getattr(err, "errno", None)
        return (
            errno in (getattr(socket, "EWOULDBLOCK", None), getattr(socket, "EAGAIN", None), 11, 35, 10035)
            or winerror in (10035,)
        )

    def _record_link_event(self, kind: str, client_id: str = "", detail: str = ""):
        self._last_link_event = {
            "kind": str(kind or ""),
            "client_id": str(client_id or ""),
            "detail": str(detail or ""),
            "at": time.time(),
        }

    def _remove_duplicate_ip_sessions(self, ip_address: str, keep_client_id: str):
        ip = str(ip_address or "").strip()
        if not ip:
            return
        duplicates = []
        for cid, info in list(self.client_infos.items()):
            if cid == keep_client_id:
                continue
            if str(getattr(info, "ip_address", "") or "").strip() == ip:
                duplicates.append(cid)
        for cid in duplicates:
            self.has_log.emit(
                f"Replacing stale session {cid} with new connection {keep_client_id} from {ip}",
                "WARNING",
            )
            self._remove_client(
                cid,
                reason=f"replaced by newer session from {ip}",
                emit_signal=False,
            )

    def _classify_timeout(self, current_time: float) -> dict:
        age = max(0.0, float(current_time) - float(self.last_packet_time or current_time))
        recent = dict(self._last_link_event or {})
        recent_age = current_time - float(recent.get("at", 0.0) or 0.0)
        if recent and recent_age <= 2.5 and recent.get("kind") in ("socket_error", "peer_closed", "client_removed"):
            kind = "link_drop"
        else:
            kind = "rx_stall"
        meta = {
            "kind": kind,
            "age_sec": age,
            "clients": len(self.client_sockets),
            "recent_kind": recent.get("kind", ""),
            "recent_client_id": recent.get("client_id", ""),
            "recent_detail": recent.get("detail", ""),
            "at": float(current_time),
        }
        self.last_timeout_meta = meta
        return meta

    @staticmethod
    def _timeout_kind_label(meta: dict) -> str:
        kind = str((meta or {}).get("kind") or "")
        if kind == "link_drop":
            return "链路断开型"
        if kind == "rx_stall":
            return "接收停顿型"
        return "通信超时"

    def _format_timeout_error_message(self, meta: dict) -> str:
        label = self._timeout_kind_label(meta)
        parts = [f"TCP通信超时 - 未收到数据（判定：{label}"]
        try:
            age = float((meta or {}).get("age_sec", 0.0) or 0.0)
            if age > 0:
                parts.append(f"；空窗={age:.1f}s")
        except (TypeError, ValueError):
            pass
        try:
            clients = int((meta or {}).get("clients", 0) or 0)
            if clients > 0:
                parts.append(f"；在线连接={clients}")
        except (TypeError, ValueError):
            pass
        recent_kind = str((meta or {}).get("recent_kind") or "")
        recent_client = str((meta or {}).get("recent_client_id") or "")
        if recent_kind:
            recent_label = {
                "socket_error": "最近Socket异常",
                "peer_closed": "最近对端关闭",
                "client_removed": "最近连接移除",
            }.get(recent_kind, recent_kind)
            if recent_client:
                parts.append(f"；{recent_label}={recent_client}")
            else:
                parts.append(f"；{recent_label}")
        parts.append("）")
        kind = str((meta or {}).get("kind") or "")
        if kind:
            parts.append(f" [timeout_class={kind}]")
        return "".join(parts)
    
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
                    _enable_tcp_keepalive(client_socket)
                    
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
                    bind_host = host or "0.0.0.0"
                    self.has_log.emit(f"Binding to {bind_host}:{port}", 'DEBUG')
                    try:
                        self.server_socket.bind((bind_host, port))
                    except OSError as bind_err:
                        # WinError 10049 等：配置的 IP 不在本机（例如平板 IP 在电脑上）
                        # 回退到 0.0.0.0，避免自检每秒刷屏且永远连不上
                        err_s = str(bind_err)
                        if bind_host not in ("0.0.0.0", "", "::") and (
                            getattr(bind_err, "winerror", None) == 10049
                            or getattr(bind_err, "errno", None) in (99, 49, 22)
                            or "10049" in err_s
                            or "not available" in err_s.lower()
                            or "地址无效" in err_s
                        ):
                            self.has_log.emit(
                                f"Bind {bind_host}:{port} failed ({bind_err}); falling back to 0.0.0.0:{port}",
                                'WARNING',
                            )
                            try:
                                self.server_socket.close()
                            except Exception:
                                pass
                            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                            self.server_socket.settimeout(5.0)
                            self.server_socket.bind(("0.0.0.0", port))
                            bind_host = "0.0.0.0"
                        else:
                            raise
                    self.server_socket.listen(5)  # Listen for up to 5 connections
                    
                    # Set socket to non-blocking for accepting connections
                    self.server_socket.setblocking(False)
                    
                    self.connection_status_changed.emit(True, f"Listening on {bind_host}:{port} (attempt {attempt + 1}/{max_retries})")
                    self.has_log.emit(f"Listening on {bind_host}:{port} (attempt {attempt + 1}/{max_retries})", 'INFO')
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
            # Check timeout only while clients exist. Empty listen is standby, not a fault.
            current_time = time.time()
            if self.client_sockets and (
                current_time - self.last_packet_time > (self.timeout_threshold + self.timeout_debounce_sec)
            ):
                self.stats['timeouts'] += 1
                meta = self._classify_timeout(current_time)
                self.error_occurred.emit(self._format_timeout_error_message(meta))
                self.last_packet_time = current_time  # Reset timeout timer
            
            # For server mode: accept incoming connections
            if hasattr(self, 'is_server_mode') and self.is_server_mode and self.server_socket:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    client_id = f"client_{self.client_counter}_{client_address[0]}:{client_address[1]}"
                    self.client_counter += 1
                    
                    # Set socket to non-blocking
                    client_socket.setblocking(False)
                    _enable_tcp_keepalive(client_socket)
                    
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
                    # New socket has no payload yet; do not inherit idle-listen age.
                    self.last_packet_time = time.time()
                    self._remove_duplicate_ip_sessions(client_address[0], client_id)
                    
                    self.stats['clients_connected'] += 1
                    
                    self.has_log.emit(f"Accepted connection from {client_address} as {client_id}", 'INFO')
                    self.client_connected.emit(client_id)
                    self.connection_status_changed.emit(True, f"{len(self.client_sockets)} client(s) connected")
                    
                except socket.error as e:
                    # No incoming connections (non-blocking socket)
                    if not self._is_would_block_error(e):
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
                        self._record_link_event("peer_closed", client_id, "recv returned 0 bytes")
                        disconnected_clients.append(client_id)
                        
                except socket.error as e:
                    # No data available (non-blocking socket)
                    if not self._is_would_block_error(e):
                        detail = self._socket_error_detail(e)
                        self._record_link_event("socket_error", client_id, detail)
                        self.has_log.emit(f"Socket error from {client_id}: {detail}", 'ERROR')
                        disconnected_clients.append(client_id)

            # Application-level idle drop: keepalive may not fire on some stacks / half-open K2.
            stale_sec = 15.0
            now = current_time
            for cid, info in list(self.client_infos.items()):
                if cid in disconnected_clients:
                    continue
                last_active = float(getattr(info, "last_active", 0) or 0)
                if last_active > 0 and (now - last_active) >= stale_sec:
                    self._record_link_event("idle_drop", cid, "no RX for %.0fs" % (now - last_active))
                    self.has_log.emit(
                        "Dropping stale TCP session %s (no data for %.0fs)" % (cid, now - last_active),
                        "WARNING",
                    )
                    disconnected_clients.append(cid)
            
            # Remove disconnected clients
            for client_id in disconnected_clients:
                self._remove_client(client_id)
                
        except Exception as e:
            self.error_occurred.emit(f"TCP read error: {str(e)}")
    
    def _remove_client(self, client_id, reason: str = "", emit_signal: bool = True):
        """Remove disconnected client"""
        if client_id == self.master_client_id:
            self.master_client_id = None
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
        reason_txt = f" ({reason})" if reason else ""
        self._record_link_event("client_removed", client_id, reason or "removed")
        self.has_log.emit(f"Client {client_id} disconnected{reason_txt}", 'INFO')
        if emit_signal:
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
                          'set_product_id', 'read_product_id', 'set_sensitivity_coefficient', 'control_single_relay',
                          'control_multiple_relays', 'read_relay_status',
                          'channel_alarm_reset', 'channel_alarm_clear_mode',
                          'channel_sensor_mode', 'reset_factory_defaults')
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
        is_master = bool(self.master_client_id and client_id == self.master_client_id)
        
        if command_type == 'channel_alarm_reset':
            # 通道报警人工复位 → 主控: 55 AA 03 15 A5 5A 16
            if not is_master:
                self.error_occurred.emit("channel_alarm_reset must target master TCP client")
                return False
            command_data = [0x55, 0xAA, 0x03, 0x15, 0xA5, 0x5A]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = description or "Channel alarm manual reset (0x15)"

        elif command_type == 'channel_alarm_clear_mode':
            # 消警模式 0x16：00=自动，01=锁存，FF=读；确认字节 A5
            # 设自动 55 AA 03 16 00 A5 4F；设锁存 … 01 A5 4E；读 … FF A5 B0
            if not is_master:
                self.error_occurred.emit("channel_alarm_clear_mode must target master TCP client")
                return False
            try:
                mode = int(command_value)
            except (TypeError, ValueError):
                mode = 0xFF
            if mode not in (0, 1, 0xFF):
                mode = 0xFF
            command_data = [0x55, 0xAA, 0x03, 0x16, mode & 0xFF, 0xA5]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            if mode == 0:
                description = description or "Set alarm clear mode AUTO (0x16)"
            elif mode == 1:
                description = description or "Set alarm clear mode LATCH (0x16)"
            else:
                description = description or "Read alarm clear mode (0x16)"

        elif command_type == 'channel_sensor_mode':
            # 传感器模式 0x19：00=对射，01=雷达，02=未配置，FF=读；确认字节 A5
            # 对射 55 AA 03 19 00 A5 40；雷达 … 01 A5 41；未配置 … 02 A5 42；读 … FF A5 BF
            if not is_master:
                self.error_occurred.emit("channel_sensor_mode must target master TCP client")
                return False
            try:
                mode = int(command_value)
            except (TypeError, ValueError):
                mode = 0xFF
            if mode not in (0, 1, 2, 0xFF):
                mode = 0xFF
            command_data = [0x55, 0xAA, 0x03, 0x19, mode & 0xFF, 0xA5]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            names = {0: "IR beam", 1: "radar", 2: "unconfigured", 0xFF: "read"}
            if mode == 0xFF:
                description = description or "Read sensor mode (0x19)"
            else:
                description = description or (
                    "Set sensor mode %s (0x19)" % names.get(mode, str(mode))
                )

        elif command_type == 'reset_factory_defaults':
            # 55 AA 03 14 A5 5A 17 — restore HV/trigger/sen_coef defaults
            command_data = [0x55, 0xAA, 0x03, 0x14, 0xA5, 0x5A]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = description or "Reset factory defaults (0x14)"

        elif command_type == 'set_hv':
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

        elif command_type == 'read_product_id':
            # Read product ID command
            flag_byte = 0x01 if bool(command_value) else 0x00
            command_data = [0x55, 0xAA, 0x03, 0x0D, flag_byte, 0x00]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            description = description or "Read product ID (0x0D)"
            
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
            # 0x06: 55 AA 03 06 [relay_num] [0/1] [xor]  — probe/master same, relay 0-2
            if isinstance(command_value, tuple) and len(command_value) == 2:
                relay_num, state = command_value
            else:
                self.error_occurred.emit(f"Invalid relay command format: {command_value}")
                return False
            relay_num = int(relay_num)
            if relay_num < 0 or relay_num > 2:
                self.error_occurred.emit(f"Invalid relay number: {relay_num}, must be 0-2")
                return False
            state_byte = 0x01 if state else 0x00
            command_data = [0x55, 0xAA, 0x03, 0x06, relay_num, state_byte]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            who = "master" if is_master else "probe"
            description = f"Set {who} relay {relay_num} to {'ON' if state else 'OFF'}"

        elif command_type == 'control_multiple_relays':
            # 0x11: 55 AA 03 11 [mask] xx [xor]
            # bit0=R0, bit1=R1, bit2=R2; ack value = actual 3-ch status mask
            relay_mask = int(command_value) & 0x07
            command_data = [0x55, 0xAA, 0x03, 0x11, relay_mask, 0x00]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            who = "master" if is_master else "probe"
            description = (
                "Set %s relay mask 0x%02X (R0=%d R1=%d R2=%d)"
                % (
                    who,
                    relay_mask,
                    1 if (relay_mask & 0x01) else 0,
                    1 if (relay_mask & 0x02) else 0,
                    1 if (relay_mask & 0x04) else 0,
                )
            )

        elif command_type == 'read_relay_status':
            # 0x12: 55 AA 03 12 [flag] 00 [xor]
            flag_byte = 0x01 if bool(command_value) else 0x00
            command_data = [0x55, 0xAA, 0x03, 0x12, flag_byte, 0x00]
            checksum = self.calculate_xor_checksum(command_data)
            command_data.append(checksum)
            who = "master" if is_master else "probe"
            description = f"Read {who} relay status (0x12)"
            
        else:
            self.error_occurred.emit(f"Unknown command type: {command_type}")
            return False
        
        max_retries = 2
        retry_delay = 0.1  # seconds
        
        for attempt in range(max_retries):
            try:
                command_bytes = bytes(command_data)
                self.client_sockets[client_id].sendall(command_bytes)
                
                # Flash-write commands need longer settle time
                control_code = command_data[3] if len(command_data) >= 4 else 0
                if control_code in (0x07, 0x08, 0x0C, 0x0E, 0x14):
                    time.sleep(0.15)
                else:
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

    def reset_factory_defaults(self, client_id: Optional[str] = None) -> bool:
        """Send 0x14 restore-defaults to one probe client (not master)."""
        target = client_id
        if target is None:
            # Prefer a non-master connected client
            for cid in self.client_sockets:
                if cid != self.master_client_id:
                    target = cid
                    break
        if target is None:
            self.error_occurred.emit("No probe client available for factory reset")
            return False
        return self.send_command_to_client(target, 'reset_factory_defaults', None)
    
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
                if packet_id in [CMD_FEEDBACK_ID, SPECTRUM_PACKET_ID, DEV_MESSAGE_ID, MASTER_PACKET_HEADER]:
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
                if packet_id in [CMD_FEEDBACK_ID, SPECTRUM_PACKET_ID, DEV_MESSAGE_ID, MASTER_PACKET_HEADER]:
                    return (i, packet_id)
            except struct.error:
                continue
        return None

    def get_expected_packet_size(self, packet_id: int, data: bytes = b'') -> int:
        if packet_id == CMD_FEEDBACK_ID:
            return CMD_FEEDBACK_SIZE
        elif packet_id == DEV_MESSAGE_ID:
            return DEV_MESSAGE_SIZE
        elif packet_id == MASTER_PACKET_HEADER:
            return MASTER_PACKET_SIZE
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

    def parse_master_summary_packet(self, data: bytes) -> Optional[MasterSummaryPacket]:
        return parse_master_summary(data)

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
                elif packet_id == MASTER_PACKET_HEADER:
                    parsed_packet = self.parse_master_summary_packet(packet_data)
                
                if parsed_packet:
                    self.buffer = self.buffer[expected_size:]
                    if isinstance(parsed_packet, CmdFeedback):
                        self.stats['cmd_packets'] += 1
                        try:
                            parsed_packet.source_client_id = None
                        except Exception:
                            pass
                        self.cmd_feedback_received.emit(parsed_packet)
                    elif isinstance(parsed_packet, SpectrumPacket):
                        self.stats['spectrum_packets'] += 1
                        # Emit packet with client_id information
                        # For now, we emit None as client_id (will be updated later)
                        self.spectrum_packet_received.emit(parsed_packet, None)
                    elif isinstance(parsed_packet, MasterSummaryPacket):
                        self.stats.setdefault('master_packets', 0)
                        self.stats['master_packets'] += 1
                        self.master_summary_received.emit(parsed_packet, None)
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
                elif packet_id == MASTER_PACKET_HEADER:
                    # Mark master link as soon as header+device_type match
                    if is_master_frame_candidate(packet_data):
                        if self.master_client_id != client_id:
                            self.master_client_id = client_id
                            self.has_log.emit(
                                "Master L2 header seen from %s (awaiting CRC)" % client_id, 'INFO'
                            )
                            self.master_link_seen.emit(client_id)
                    parsed_packet = self.parse_master_summary_packet(packet_data)
                    if parsed_packet is None and is_master_frame_candidate(packet_data):
                        reason = explain_master_summary_reject(packet_data)
                        hex_head = ' '.join('%02X' % b for b in packet_data[:8])
                        self.has_log.emit(
                            "Master L2 reject from %s: %s | head=%s" % (client_id, reason, hex_head),
                            'WARNING'
                        )
                        # 0x19 应答后若多 1～2 字节，假 0xA55A 再整帧丢 60B 会把真 L2
                        # 裁掉，首页一直停在旧判决，看起来像灵敏度掉了。
                        nxt = find_valid_master_frame_offset(bytes(client_buffer), 1)
                        if nxt is not None and nxt > 0:
                            del client_buffer[:nxt]
                            self.has_log.emit(
                                "Master L2 resync from %s: skipped %d leftover bytes"
                                % (client_id, nxt),
                                'WARNING',
                            )
                        else:
                            del client_buffer[:1]
                        self.stats['errors'] += 1
                        continue
                    if (parsed_packet is not None
                            and isinstance(parsed_packet, MasterSummaryPacket)
                            and int(getattr(parsed_packet, "checksum", 0) or 0) == 0):
                        # Accepted with zero CRC workaround — remind once in a while
                        n = int(self.stats.get('master_packets', 0) or 0)
                        if n == 0 or (n % 30) == 0:
                            self.has_log.emit(
                                "Master L2 accepted with checksum=0 from %s (reflash master CRC fix)"
                                % client_id,
                                'WARNING',
                            )
                
                if parsed_packet:
                    del client_buffer[:expected_size]
                    if isinstance(parsed_packet, CmdFeedback):
                        self.stats['cmd_packets'] += 1
                        try:
                            parsed_packet.source_client_id = client_id
                        except Exception:
                            pass
                        self.cmd_feedback_received.emit(parsed_packet)
                        # ACK 与 L2 可能粘在同一段 TCP 里；应答长度若与 10B 不完全一致，
                        # 先对齐到下一帧合法 L2，避免通道判决停在写传感器之前的旧包。
                        ctrl = int(getattr(parsed_packet, "control_code", 0) or 0)
                        if (
                            ctrl in (0x06, 0x11, 0x12, 0x15, 0x16, 0x19)
                            or client_id == self.master_client_id
                        ):
                            nxt = find_valid_master_frame_offset(bytes(client_buffer), 0)
                            if nxt is not None and nxt > 0:
                                del client_buffer[:nxt]
                                self.has_log.emit(
                                    "Master buffer aligned after 0x%02X ack from %s: skip %d bytes"
                                    % (ctrl, client_id, nxt),
                                    'WARNING',
                                )
                    elif isinstance(parsed_packet, SpectrumPacket):
                        self.stats['spectrum_packets'] += 1
                        # Update client info
                        if client_id in self.client_infos:
                            self.client_infos[client_id].packets_received += 1
                            self.client_infos[client_id].last_active = time.time()
                        # Emit packet with client_id
                        self.spectrum_packet_received.emit(parsed_packet, client_id)
                    elif isinstance(parsed_packet, MasterSummaryPacket):
                        self.stats.setdefault('master_packets', 0)
                        self.stats['master_packets'] += 1
                        self.master_client_id = client_id
                        if client_id in self.client_infos:
                            self.client_infos[client_id].packets_received += 1
                            self.client_infos[client_id].last_active = time.time()
                        n_pkt = int(self.stats['master_packets'])
                        mask = int(getattr(parsed_packet, "online_mask", 0) or 0)
                        tick = int(getattr(parsed_packet, "timestamp_ms", 0) or 0)
                        prev_mask = self._last_l2_online_mask
                        prev_tick = self._last_l2_timestamp_ms
                        mask_changed = prev_mask is not None and mask != prev_mask
                        # 主控复位：毫秒 tick 明显回跳（排除 uint32 回绕）
                        tick_reset = (
                            prev_tick is not None
                            and tick + 5000 < prev_tick
                            and prev_tick < 0xF0000000
                        )
                        periodic = n_pkt == 1 or (n_pkt % 30) == 0
                        if periodic or mask_changed or tick_reset:
                            n_slots = int(parsed_packet.probe_count_cfg or 0) or 2
                            slot_cps = list(parsed_packet.probe_cps or [])[:n_slots]
                            slot_txt = ",".join(
                                "%d:%d" % (i + 1, int(v or 0))
                                for i, v in enumerate(slot_cps)
                            ) or "-"
                            extra = ""
                            if mask_changed:
                                extra += " mask_changed"
                            if tick_reset:
                                extra += " timestamp_reset"
                            self.has_log.emit(
                                "Master L2 OK from %s: total_cps=%d slot_cps=[%s] probes=%d "
                                "decision=0x%02X online_mask=0x%04X timestamp_ms=%d (#%d)%s"
                                % (
                                    client_id,
                                    int(parsed_packet.total_cps),
                                    slot_txt,
                                    int(parsed_packet.probe_count_cfg),
                                    int(parsed_packet.decision_result),
                                    mask,
                                    tick,
                                    n_pkt,
                                    extra,
                                ),
                                'INFO',
                            )
                            if n_pkt == 1:
                                hx = ' '.join('%02X' % b for b in packet_data)
                                self.has_log.emit("Master L2 raw60: %s" % hx, 'INFO')
                        self._last_l2_online_mask = mask
                        self._last_l2_timestamp_ms = tick
                        self.master_summary_received.emit(parsed_packet, client_id)
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

    def reset_factory_defaults_broadcast_probes(self) -> int:
        """Send 0x14 to all non-master clients. Returns number of successful sends."""
        ok = 0
        for cid in list(self.client_sockets.keys()):
            if cid == self.master_client_id:
                continue
            if self.send_command_to_client(cid, 'reset_factory_defaults', None):
                ok += 1
        return ok

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
