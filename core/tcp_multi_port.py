#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PC 多端口分流：主控口 (L2/下行命令) + 探头口 (0x5350)。
对外接口与 TcpPacketWorker 一致，供 ui_base / main_window 复用。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from core.config import ConfigManager
from core.tcp_detector import TcpPacketWorker, ClientInfo, CmdFeedback, SpectrumPacket


def is_tcp_worker(worker) -> bool:
    return isinstance(worker, (TcpPacketWorker, MultiPortTcpPacketWorker))


class MultiPortTcpPacketWorker(QObject):
    """双 listen：master_worker + probe_worker，信号与命令路由合并。"""

    cmd_feedback_received = pyqtSignal(CmdFeedback)
    spectrum_packet_received = pyqtSignal(SpectrumPacket, str)
    master_summary_received = pyqtSignal(object, str)
    master_link_seen = pyqtSignal(str)
    dev_message_received = pyqtSignal(object)
    connection_status_changed = pyqtSignal(bool, str)
    error_occurred = pyqtSignal(str)
    has_log = pyqtSignal(str, str)
    command_sent = pyqtSignal(str)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self._master = TcpPacketWorker(self)
        self._probe = TcpPacketWorker(self)
        self._master.listen_role = "master_only"
        self._probe.listen_role = "probe_only"
        self.is_server_mode = True
        self.raw_logger = None
        self.is_running = False
        self._retiring = False
        self._wire_child(self._master)
        self._wire_child(self._probe)

    def _wire_child(self, child: TcpPacketWorker):
        child.cmd_feedback_received.connect(self.cmd_feedback_received.emit)
        child.spectrum_packet_received.connect(self.spectrum_packet_received.emit)
        child.master_summary_received.connect(self.master_summary_received.emit)
        child.master_link_seen.connect(self.master_link_seen.emit)
        child.dev_message_received.connect(self.dev_message_received.emit)
        child.error_occurred.connect(self.error_occurred.emit)
        child.has_log.connect(self.has_log.emit)
        child.command_sent.connect(self.command_sent.emit)
        child.client_connected.connect(self.client_connected.emit)
        child.client_disconnected.connect(self._on_child_disconnected)
        child.connection_status_changed.connect(self._on_child_connection_status)

    def _on_child_connection_status(self, _ok, _msg):
        if self._retiring:
            return
        self._emit_combined_status()

    def _unwire_children(self):
        """Break child→parent signal forwards before socket teardown (avoid deleted-parent RuntimeError)."""
        self._retiring = True
        for child in (self._master, self._probe):
            pairs = [
                (child.cmd_feedback_received, self.cmd_feedback_received.emit),
                (child.spectrum_packet_received, self.spectrum_packet_received.emit),
                (child.master_summary_received, self.master_summary_received.emit),
                (child.master_link_seen, self.master_link_seen.emit),
                (child.dev_message_received, self.dev_message_received.emit),
                (child.error_occurred, self.error_occurred.emit),
                (child.has_log, self.has_log.emit),
                (child.command_sent, self.command_sent.emit),
                (child.client_connected, self.client_connected.emit),
                (child.client_disconnected, self._on_child_disconnected),
                (child.connection_status_changed, self._on_child_connection_status),
            ]
            for sig, slot in pairs:
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass

    def _on_child_disconnected(self, client_id: str):
        if self._retiring:
            return
        self.client_disconnected.emit(client_id)
        self._emit_combined_status()

    def _emit_combined_status(self):
        if self._retiring:
            return
        n_m = len(self._master.client_sockets)
        n_p = len(self._probe.client_sockets)
        listening = bool(self._master.server_socket) and bool(self._probe.server_socket)
        connected = (n_m + n_p) > 0 or listening
        msg = (
            f"Multi-port: master={self.config.tcp_port_master} ({n_m} client(s)), "
            f"probe={self.config.tcp_port_probe} ({n_p} client(s))"
        )
        self.connection_status_changed.emit(connected, msg)

    @property
    def master_client_id(self):
        return self._master.master_client_id

    @master_client_id.setter
    def master_client_id(self, value):
        self._master.master_client_id = value

    @property
    def client_sockets(self):
        out = dict(self._master.client_sockets)
        out.update(self._probe.client_sockets)
        return out

    @property
    def client_infos(self):
        """合并主控/探头子 worker，供 get_online_probe_client_ids 等使用。"""
        out = dict(getattr(self._master, "client_infos", None) or {})
        out.update(getattr(self._probe, "client_infos", None) or {})
        return out

    def _child_for_client(self, client_id: str) -> Optional[TcpPacketWorker]:
        if client_id in self._master.client_sockets:
            return self._master
        if client_id in self._probe.client_sockets:
            return self._probe
        return None

    def set_logger(self, logger, log_fn=None):
        self.raw_logger = logger
        self._master.set_logger(logger)
        self._probe.set_logger(logger)

    def connect_tcp(self, host: str, port: int, mode: str = "server"):
        if mode != "server":
            self.has_log.emit("Multi-port worker only supports server mode", "ERROR")
            return False
        self.config.load_settings()
        bind_host = host or self.config.tcp_host or "0.0.0.0"
        p_m = int(self.config.tcp_port_master)
        p_p = int(self.config.tcp_port_probe)
        if p_m == p_p:
            self.error_occurred.emit(
                f"TCP multi-port: master port and probe port must differ (both {p_m})"
            )
            return False
        ok_m = self._master.connect_tcp(bind_host, p_m, "server")
        ok_p = self._probe.connect_tcp(bind_host, p_p, "server")
        self.is_server_mode = ok_m and ok_p
        self._emit_combined_status()
        if ok_m and ok_p:
            self.has_log.emit(
                f"Multi-port listening: master {bind_host}:{p_m}, probe {bind_host}:{p_p}",
                "INFO",
            )
        return ok_m and ok_p

    def disconnect_tcp(self):
        self._master.disconnect_tcp()
        self._probe.disconnect_tcp()
        self.is_server_mode = False
        self.connection_status_changed.emit(False, "Multi-port disconnected")

    def start_reading(self):
        self.is_running = True
        self._master.start_reading()
        self._probe.start_reading()

    def stop_reading(self):
        self.is_running = False
        self._master.stop_reading()
        self._probe.stop_reading()

    @pyqtSlot()
    def shutdown_tcp_io(self):
        self._unwire_children()
        self.is_running = False
        self._master.is_running = False
        self._probe.is_running = False
        self._master._cleanup_all_sockets()
        self._probe._cleanup_all_sockets()
        self.is_server_mode = False

    def read_tcp_loop(self):
        if not self.is_running:
            return
        self._master.read_tcp_loop()
        self._probe.read_tcp_loop()

    def is_tcp_ready(self):
        return self._master.is_tcp_ready() and self._probe.is_tcp_ready()

    def try_connection(self):
        return self.is_tcp_ready()

    def get_client_list(self):
        return list(self.client_sockets.keys())

    def get_client_info(self, client_id: str) -> Optional[ClientInfo]:
        w = self._child_for_client(client_id)
        return w.get_client_info(client_id) if w else None

    def get_all_client_infos(self):
        return self._master.get_all_client_infos() + self._probe.get_all_client_infos()

    def get_stats(self):
        sm = self._master.get_stats()
        sp = self._probe.get_stats()
        out = dict(sm)
        for k, v in sp.items():
            if isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + v
            else:
                out[f"probe_{k}"] = v
        return out

    def send_command_to_client(self, client_id: str, command_type: str, command_value, description: str = "") -> bool:
        w = self._child_for_client(client_id)
        if w is None:
            self.error_occurred.emit(f"Client {client_id} not found on master/probe ports")
            return False
        return w.send_command_to_client(client_id, command_type, command_value, description)

    def send_command(self, command_data: list, description: str = ""):
        return self._probe.send_command(command_data, description)

    def reset_factory_defaults(self, client_id: Optional[str] = None) -> bool:
        if client_id:
            w = self._child_for_client(client_id)
            if w is self._master:
                self.error_occurred.emit("Factory reset (0x14) must target probe clients")
                return False
            return w.reset_factory_defaults(client_id) if w else False
        return bool(self._probe.reset_factory_defaults())

    def reset_factory_defaults_broadcast_probes(self) -> int:
        return self._probe.reset_factory_defaults_broadcast_probes()

    def set_high_voltage(self, voltage: float):
        return self._probe.set_high_voltage(voltage)

    def set_threshold(self, threshold: int):
        return self._probe.set_threshold(threshold)

    def set_operation_mode(self, mode: str):
        return self._probe.set_operation_mode(mode)

    def set_product_id(self, product_id: int):
        return self._probe.set_product_id(product_id)

    def read_product_id(self, flag: bool):
        return self._probe.read_product_id(flag)

    def set_sensitivity_coefficient(self, coefficient):
        return self._probe.set_sensitivity_coefficient(coefficient)

    def read_sensitivity_coefficient(self, flag: bool):
        return self._probe.read_sensitivity_coefficient(flag)

    def read_relay_status(self, flag: bool):
        return self._master.read_relay_status(flag)

    def read_alarm_status(self, flag: bool):
        return self._probe.read_alarm_status(flag)

    def set_input_signal_source(self, from_internal=True):
        return self._probe.set_input_signal_source(from_internal)

    def set_gain_stabilizer_flag(self, flag: bool):
        return self._probe.set_gain_stabilizer_flag(flag)

    def control_single_relay(self, relay_num: int, state: bool):
        return self._master.control_single_relay(relay_num, state)

    def control_multiple_relays(self, relay_mask: int):
        return self._master.control_multiple_relays(relay_mask)

    def reset_spectrum_data(self):
        return self._probe.reset_spectrum_data()

    def control_multiple_leds(self, led_mask: int):
        return self._probe.control_multiple_leds(led_mask)
