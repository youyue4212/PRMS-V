#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master L2 Summary (60B) parser - aligned with master_summary_packet.h
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional

MASTER_PACKET_HEADER = 0xA55A  # wire: 5A A5
MASTER_DEVICE_TYPE = 0x02
MASTER_PACKET_SIZE = 60
MASTER_PACKET_CRC_LEN = 58
MASTER_MAX_PROBES = 16

# io_status bits
MASTER_IO_IR_ENTRY = 1 << 0
MASTER_IO_IR_EXIT = 1 << 1
MASTER_IO_RADAR_GATE = 1 << 2
MASTER_IO_CABINET_DOOR = 1 << 3
MASTER_IO_RELAY0 = 1 << 4  # 总声光实际输出
MASTER_IO_RELAY1 = 1 << 5  # 道闸等
MASTER_IO_RELAY2 = 1 << 6  # 道闸/辅路
MASTER_IO_RELAY_OUTPUT = MASTER_IO_RELAY0  # 兼容旧名 = 继电器 0

# sys_mode bits
MASTER_MODE_IR_DEGRADED = 1 << 0
MASTER_MODE_ONLINE_LOW_WARN = 1 << 1
MASTER_MODE_ALARM_LATCH = 1 << 2  # 1=锁存消警（须 0x15）；0=自动（约 3s 条件消失可自灭）

MASTER_DECISION_NORMAL = 0x00
MASTER_DECISION_OVER_THRESHOLD = 0x01
MASTER_DECISION_WINDOW_MATCHED = 0x02
MASTER_DECISION_JOINT_ALARM = 0x03
MASTER_DECISION_PASSING_NO_ALARM = 0x04
MASTER_DECISION_MANUAL_RESET = 0x05  # 已人工复位 / 待重新武装
MASTER_DECISION_SYSTEM_FAULT = 0xFF

# Master considered offline if no valid summary within this window (1 Hz TX)
MASTER_OFFLINE_TIMEOUT_SEC = 3.0

_DECISION_TEXT_ZH = {
    MASTER_DECISION_NORMAL: "\u6b63\u5e38",
    MASTER_DECISION_OVER_THRESHOLD: "\u8d85\u9608\u63d0\u793a",
    MASTER_DECISION_WINDOW_MATCHED: "\u7a97\u7b26\u5408\uff08\u964d\u7ea7\uff09",
    MASTER_DECISION_JOINT_ALARM: "\u8054\u62a5/\u7b26\u5408\u62a5\u8b66",
    MASTER_DECISION_PASSING_NO_ALARM: "\u4eba\u5458\u7ecf\u8fc7",
    MASTER_DECISION_MANUAL_RESET: "\u5df2\u4eba\u5de5\u590d\u4f4d",
    MASTER_DECISION_SYSTEM_FAULT: "\u7cfb\u7edf\u6545\u969c",
}

_DECISION_TEXT_EN = {
    MASTER_DECISION_NORMAL: "Normal",
    MASTER_DECISION_OVER_THRESHOLD: "Over threshold (not channel alarm)",
    MASTER_DECISION_WINDOW_MATCHED: "Window matched (degraded)",
    MASTER_DECISION_JOINT_ALARM: "Joint / matched alarm",
    MASTER_DECISION_PASSING_NO_ALARM: "Person passing",
    MASTER_DECISION_MANUAL_RESET: "Manually acknowledged",
    MASTER_DECISION_SYSTEM_FAULT: "System fault",
}


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            crc &= 0xFFFF
    return crc


@dataclass
class MasterSummaryPacket:
    header: int
    device_type: int
    master_id: int
    io_status: int
    decision_result: int
    hit_probe_mask: int
    online_mask: int
    window_x_sec: int
    window_y_sec: int
    sys_mode: int
    match_threshold_n: int
    probe_count_cfg: int
    total_cps: int
    probe_cps: List[int] = field(default_factory=list)
    timestamp_ms: int = 0
    reserved_word: int = 0
    reserved2: int = 0
    checksum: int = 0
    received_at: float = 0.0  # PC receive time

    @property
    def ir_entry(self) -> bool:
        return bool(self.io_status & MASTER_IO_IR_ENTRY)

    @property
    def ir_exit(self) -> bool:
        return bool(self.io_status & MASTER_IO_IR_EXIT)

    @property
    def radar_gate(self) -> bool:
        return bool(self.io_status & MASTER_IO_RADAR_GATE)

    @property
    def cabinet_door(self) -> bool:
        return bool(self.io_status & MASTER_IO_CABINET_DOOR)

    @property
    def relay0(self) -> bool:
        return bool(self.io_status & MASTER_IO_RELAY0)

    @property
    def relay1(self) -> bool:
        return bool(self.io_status & MASTER_IO_RELAY1)

    @property
    def relay2(self) -> bool:
        return bool(self.io_status & MASTER_IO_RELAY2)

    @property
    def relay_output(self) -> bool:
        """兼容旧名：等同继电器 0（总声光）。"""
        return self.relay0

    @property
    def relay_mask(self) -> int:
        """bit0/1/2 ← io_status bit4/5/6，与 0x11/0x12 掩码一致。"""
        m = 0
        if self.relay0:
            m |= 0x01
        if self.relay1:
            m |= 0x02
        if self.relay2:
            m |= 0x04
        return m

    @property
    def ir_degraded(self) -> bool:
        return bool(self.sys_mode & MASTER_MODE_IR_DEGRADED)

    @property
    def online_low_warn(self) -> bool:
        return bool(self.sys_mode & MASTER_MODE_ONLINE_LOW_WARN)

    @property
    def alarm_latch_mode(self) -> bool:
        """True = 锁存消警（须人工 0x15）；False = 自动消警。"""
        return bool(self.sys_mode & MASTER_MODE_ALARM_LATCH)

    def is_channel_alarm(self) -> bool:
        """
        通道符合硬报（上位机硬报 UI / 闸机态）仅绑 decision ∈ {0x02, 0x03}。
        0x01 超阈提示、0x05 已人工复位、0xFF 故障 均不算硬报。
        继电器 bit4/5/6 仅作辅助显示 / 闸机态，不单独拉起硬报 UI。
        """
        return self.decision_result in (
            MASTER_DECISION_WINDOW_MATCHED,
            MASTER_DECISION_JOINT_ALARM,
        )

    def is_hard_alarm(self) -> bool:
        """兼容旧名：等同通道硬报警。"""
        return self.is_channel_alarm()

    def is_channel_busy(self) -> bool:
        return (
            self.ir_entry
            or self.radar_gate
            or self.decision_result == MASTER_DECISION_PASSING_NO_ALARM
            or self.is_channel_alarm()
        )

    def ui_alarm_kind(self) -> str:
        """
        首页报警区状态机（跟主控 L2 decision）:
          channel_alarm | acked | passing | over_threshold | fault | normal
        硬报：0x02/0x03 进入；0x05/0x00/0x04 退出（不靠定时猜清除）。
        """
        d = self.decision_result
        if d in (MASTER_DECISION_WINDOW_MATCHED, MASTER_DECISION_JOINT_ALARM):
            return "channel_alarm"
        if d == MASTER_DECISION_MANUAL_RESET:
            return "acked"
        if d == MASTER_DECISION_PASSING_NO_ALARM:
            return "passing"
        if d == MASTER_DECISION_OVER_THRESHOLD:
            return "over_threshold"
        if d == MASTER_DECISION_SYSTEM_FAULT:
            return "fault"
        return "normal"

    def decision_text(self, lang: str = "zh") -> str:
        table = _DECISION_TEXT_ZH if lang != "en" else _DECISION_TEXT_EN
        return table.get(self.decision_result, f"0x{self.decision_result:02X}")

    def active_probe_count(self) -> int:
        n = int(self.probe_count_cfg or 0)
        if n <= 0:
            n = MASTER_MAX_PROBES
        return min(n, MASTER_MAX_PROBES)

    def looks_sane(self) -> bool:
        """Reject clearly mis-decoded L2 (bitfield cast / wrong layout)."""
        if self.probe_count_cfg > MASTER_MAX_PROBES:
            return False
        if self.match_threshold_n > MASTER_MAX_PROBES:
            return False
        # Channel monitors: multi-megacps is not plausible
        if int(self.total_cps) > 2_000_000:
            return False
        return True


def explain_master_summary_reject(data: bytes) -> str:
    """Human-readable reason when 60B frame looks like L2 but fails parse."""
    if len(data) < MASTER_PACKET_SIZE:
        return "short(%d)" % len(data)
    try:
        header, device_type = struct.unpack_from('<HB', data, 0)
        checksum = struct.unpack_from('<H', data, 58)[0]
    except struct.error:
        return "struct"
    if header != MASTER_PACKET_HEADER:
        return "header=0x%04X" % header
    if device_type != MASTER_DEVICE_TYPE:
        return "device_type=0x%02X" % device_type
    expect = crc16_modbus(data[:MASTER_PACKET_CRC_LEN])
    if expect != checksum:
        return "crc expect=0x%04X got=0x%04X" % (expect, checksum)
    return "unknown"


def is_master_frame_candidate(data: bytes) -> bool:
    """True if bytes look like Master L2 header (even before CRC)."""
    if len(data) < 3:
        return False
    try:
        header, device_type = struct.unpack_from('<HB', data, 0)
    except struct.error:
        return False
    return header == MASTER_PACKET_HEADER and device_type == MASTER_DEVICE_TYPE


def parse_master_summary(data: bytes, received_at: Optional[float] = None) -> Optional[MasterSummaryPacket]:
    if len(data) < MASTER_PACKET_SIZE:
        return None
    try:
        header, device_type, master_id, io_status, decision, hit_mask, online_mask, \
            window_cfg, sys_mode, match_n, probe_count = struct.unpack_from('<HBBBBHHBBBB', data, 0)
        total_cps = struct.unpack_from('<I', data, 14)[0]
        probe_cps = list(struct.unpack_from('<' + 'H' * MASTER_MAX_PROBES, data, 18))
        timestamp_ms, reserved_word, reserved2, checksum = struct.unpack_from('<IHHH', data, 50)
    except struct.error:
        return None

    if header != MASTER_PACKET_HEADER or device_type != MASTER_DEVICE_TYPE:
        return None

    expect = crc16_modbus(data[:MASTER_PACKET_CRC_LEN])
    if expect != checksum:
        # CRC 不过丢弃（通道判决只认合法 L2）
        return None

    return MasterSummaryPacket(
        header=header,
        device_type=device_type,
        master_id=master_id,
        io_status=io_status,
        decision_result=decision,
        hit_probe_mask=hit_mask,
        online_mask=online_mask,
        window_x_sec=window_cfg & 0x0F,
        window_y_sec=(window_cfg >> 4) & 0x0F,
        sys_mode=sys_mode,
        match_threshold_n=match_n,
        probe_count_cfg=probe_count,
        total_cps=total_cps,
        probe_cps=probe_cps,
        timestamp_ms=timestamp_ms,
        reserved_word=reserved_word,
        reserved2=reserved2,
        checksum=checksum,
        received_at=received_at if received_at is not None else time.time(),
    )


def is_master_online(last_packet: Optional[MasterSummaryPacket], now: Optional[float] = None) -> bool:
    if last_packet is None:
        return False
    t = now if now is not None else time.time()
    return (t - float(last_packet.received_at or 0)) <= MASTER_OFFLINE_TIMEOUT_SEC


def hit_slots(mask: int, count: int) -> List[int]:
    return [i for i in range(min(count, MASTER_MAX_PROBES)) if mask & (1 << i)]


def format_io_brief(pkt: MasterSummaryPacket, lang: str = "zh") -> str:
    if lang == "en":
        parts = []
        if pkt.ir_entry:
            parts.append("IR-IN")
        if pkt.ir_exit:
            parts.append("IR-OUT")
        if pkt.radar_gate:
            parts.append("RADAR")
        if pkt.relay0 or pkt.relay1 or pkt.relay2:
            parts.append("R%d%d%d" % (int(pkt.relay0), int(pkt.relay1), int(pkt.relay2)))
        if pkt.ir_degraded:
            parts.append("IR-DEG")
        return ", ".join(parts) if parts else "Idle"
    parts = []
    if pkt.ir_entry:
        parts.append("\u5165\u53e3\u7ea2\u5916")
    if pkt.ir_exit:
        parts.append("\u51fa\u53e3\u7ea2\u5916")
    if pkt.radar_gate:
        parts.append("\u96f7\u8fbe")
    if pkt.relay0 or pkt.relay1 or pkt.relay2:
        parts.append(
            "\u7ee7\u7535\u5668 %d/%d/%d" % (int(pkt.relay0), int(pkt.relay1), int(pkt.relay2))
        )
    if pkt.ir_degraded:
        parts.append("\u7ea2\u5916\u964d\u7ea7")
    return "\u3001".join(parts) if parts else "\u901a\u9053\u7a7a\u95f2"
