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

# io_status bits（主控 GPIO：PG14=入口，PG15=出口；挡光=低。仅对射模式才置这些位）
MASTER_IO_IR_ENTRY = 1 << 0  # PG14
MASTER_IO_IR_EXIT = 1 << 1   # PG15
MASTER_IO_RADAR_GATE = 1 << 2
MASTER_IO_CABINET_DOOR = 1 << 3
MASTER_IO_RELAY0 = 1 << 4  # 总声光实际输出
MASTER_IO_RELAY1 = 1 << 5  # 道闸等
MASTER_IO_RELAY2 = 1 << 6  # 道闸/辅路
MASTER_IO_RELAY_OUTPUT = MASTER_IO_RELAY0  # 兼容旧名 = 继电器 0

# sys_mode bits
MASTER_MODE_IR_DEGRADED = 1 << 0      # 1=无占用门控/未配置（不再表示红外专属降级）
MASTER_MODE_ONLINE_LOW_WARN = 1 << 1
MASTER_MODE_ALARM_LATCH = 1 << 2     # 1=锁存消警（须 0x15）；0=自动（约 3s 条件消失可自灭）
MASTER_MODE_RADAR = 1 << 3           # 1=雷达模式
MASTER_MODE_OCC_GATE_EN = 1 << 4     # 1=占用门控已启用（空闲否决有效）

# 0x19 传感器模式：0=对射 1=雷达 2=未配置
MASTER_SENSOR_MODE_IR = 0
MASTER_SENSOR_MODE_RADAR = 1
MASTER_SENSOR_MODE_UNCONFIGURED = 2

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
    MASTER_DECISION_OVER_THRESHOLD: "\u8d85\u9608\u63d0\u793a\uff08\u672a\u8fbeN\u8def\uff0c\u975e\u786c\u62a5\uff09",
    MASTER_DECISION_WINDOW_MATCHED: "\u6ed1\u52a8\u7a97\u7b26\u5408\uff08\u901a\u9053\u786c\u62a5\uff09",
    MASTER_DECISION_JOINT_ALARM: "\u5bf9\u5c04\u7a97\u7b26\u5408\uff08\u901a\u9053\u786c\u62a5\uff09",
    MASTER_DECISION_PASSING_NO_ALARM: "\u4eba\u5458\u7ecf\u8fc7",
    MASTER_DECISION_MANUAL_RESET: "\u5df2\u4eba\u5de5\u590d\u4f4d",
    MASTER_DECISION_SYSTEM_FAULT: "\u7cfb\u7edf\u6545\u969c",
}

_DECISION_TEXT_EN = {
    MASTER_DECISION_NORMAL: "Normal",
    MASTER_DECISION_OVER_THRESHOLD: "Over threshold (<N probes, not hard alarm)",
    MASTER_DECISION_WINDOW_MATCHED: "Sliding-window match (channel hard alarm)",
    MASTER_DECISION_JOINT_ALARM: "IR-window match (channel hard alarm)",
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
        """sys_mode.bit0：无占用门控 / 未配置。保留旧属性名兼容调用方。"""
        return bool(self.sys_mode & MASTER_MODE_IR_DEGRADED)

    @property
    def online_low_warn(self) -> bool:
        return bool(self.sys_mode & MASTER_MODE_ONLINE_LOW_WARN)

    @property
    def alarm_latch_mode(self) -> bool:
        """True = 锁存消警（须人工 0x15）；False = 自动消警。"""
        return bool(self.sys_mode & MASTER_MODE_ALARM_LATCH)

    @property
    def radar_mode(self) -> bool:
        """sys_mode.bit3：1=雷达模式。"""
        return bool(self.sys_mode & MASTER_MODE_RADAR)

    @property
    def occ_gate_enabled(self) -> bool:
        """sys_mode.bit4：1=占用门控已启用（空闲否决有效）。"""
        return bool(self.sys_mode & MASTER_MODE_OCC_GATE_EN)

    def sensor_mode_code(self) -> int:
        """推断 0x19，顺序与现固件 sys_mode 一致：bit0 → bit3 → bit4。"""
        if self.ir_degraded:
            return MASTER_SENSOR_MODE_UNCONFIGURED
        if self.radar_mode:
            return MASTER_SENSOR_MODE_RADAR
        if self.occ_gate_enabled:
            return MASTER_SENSOR_MODE_IR
        return MASTER_SENSOR_MODE_UNCONFIGURED

    def is_channel_alarm(self) -> bool:
        """
        通道硬报 UI / 闸机态仅绑 decision ∈ {0x02, 0x03}。
        0x02=滑动窗 ≥N 路超阈（未配置降级窗，以及雷达占用期间的滑动符合）；
        0x03=对射窗内符合（只对射模式）；
        0x01 超阈但不够 N 路、0x04 经过、0x05 已复位、0xFF 故障 均不算硬报。
        未配置没有 0x04。继电器 bit4/5/6 仅作辅助显示，不单独拉起硬报 UI。
        """
        return self.decision_result in (
            MASTER_DECISION_WINDOW_MATCHED,
            MASTER_DECISION_JOINT_ALARM,
        )

    def is_hard_alarm(self) -> bool:
        """兼容旧名：等同通道硬报警。"""
        return self.is_channel_alarm()

    def is_channel_busy(self) -> bool:
        """通道占用显示态：只跟主控 decision，不自己用红外/雷达猜。

        0x02/0x03 = 硬报占用；0x04 = 入口挡住且未硬报（人员经过）。
        未配置没有 0x04；雷达占用符合走 0x02，不是 0x03。
        占用门控未生效/降级时主控不会出 0x04，此时即使 io_status 有占用原始位也不算经过。
        出口红外只上报，不参与本判定。
        """
        return (
            self.is_channel_alarm()
            or self.decision_result == MASTER_DECISION_PASSING_NO_ALARM
        )

    def ui_alarm_kind(self) -> str:
        """
        首页报警区状态机（跟主控 L2 decision）:
          channel_alarm | acked | passing | over_threshold | fault | normal
        硬报：0x02（滑动窗：未配置或雷达占用符合）/ 0x03（对射窗，只对射）进入；
        0x05/0x00/0x04 退出。未配置没有 0x04，也不会出 0x03。
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


def find_valid_master_frame_offset(data: bytes, start: int = 0) -> Optional[int]:
    """First offset of a CRC-valid 60B L2 frame, or None.

    Used after 0x19/0x15 ACK leftovers so we do not skip a whole 60B from a
    false 0xA55A and freeze the homepage on a stale decision.
    """
    if not data:
        return None
    try:
        start = max(0, int(start))
    except (TypeError, ValueError):
        start = 0
    n = len(data)
    last = n - MASTER_PACKET_SIZE
    if last < start:
        return None
    for i in range(start, last + 1):
        chunk = data[i:i + MASTER_PACKET_SIZE]
        if not is_master_frame_candidate(chunk):
            continue
        if parse_master_summary(chunk) is not None:
            return i
    return None


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


def format_sensor_mode_brief(pkt: MasterSummaryPacket, lang: str = "zh", mode_override=None) -> str:
    """传感器模式摘要：bit0 未配置，bit3 雷达，bit4 对射门控。"""
    if mode_override in (0, 1, 2):
        code = int(mode_override)
    else:
        code = pkt.sensor_mode_code()
    if lang == "en":
        if code == MASTER_SENSOR_MODE_UNCONFIGURED:
            return "Sensor: configure IR or radar"
        if code == MASTER_SENSOR_MODE_RADAR:
            mode = "Radar"
        else:
            mode = "Beam IR"
        if code == MASTER_SENSOR_MODE_UNCONFIGURED or pkt.ir_degraded or not pkt.occ_gate_enabled:
            if code == MASTER_SENSOR_MODE_UNCONFIGURED:
                return "Sensor: configure IR or radar"
            return "%s · gate inactive" % mode
        return "%s · gate active" % mode
    if code == MASTER_SENSOR_MODE_UNCONFIGURED:
        return "\u8bf7\u914d\u7f6e\u5bf9\u5c04\u6216\u96f7\u8fbe"
    if code == MASTER_SENSOR_MODE_RADAR:
        mode = "\u96f7\u8fbe"
    else:
        mode = "\u5bf9\u5c04"
    if pkt.ir_degraded or not pkt.occ_gate_enabled:
        return "%s \u00b7 \u5360\u4f4d\u672a\u751f\u6548" % mode
    return "%s \u00b7 \u7a7a\u95f2\u5426\u51b3\u6709\u6548" % mode


def format_ir_beam_states(pkt: MasterSummaryPacket, lang: str = "zh", only_blocked: bool = False) -> list:
    """对射通/挡。现固件仅对射模式把 PG14/PG15 打进 L2。
    only_blocked=True：操作员画面只报挡光，通光不写。
    """
    items = []
    if lang == "en":
        if pkt.ir_entry:
            items.append("IR-IN blocked")
        elif not only_blocked:
            items.append("IR-IN clear")
        if pkt.ir_exit:
            items.append("IR-OUT blocked")
        elif not only_blocked:
            items.append("IR-OUT clear")
        return items
    if pkt.ir_entry:
        items.append("\u5165\u53e3\u5bf9\u5c04\uff1a\u6321")
    elif not only_blocked:
        items.append("\u5165\u53e3\u5bf9\u5c04\uff1a\u901a")
    if pkt.ir_exit:
        items.append("\u51fa\u53e3\u5bf9\u5c04\uff1a\u6321")
    elif not only_blocked:
        items.append("\u51fa\u53e3\u5bf9\u5c04\uff1a\u901a")
    return items


def format_io_brief(
    pkt: MasterSummaryPacket,
    lang: str = "zh",
    ir_installed: bool = True,
    mode_override=None,
    beam_detail: str = "exception",
) -> str:
    """IO 摘要。
    beam_detail=exception：操作员/总览，只报挡光；always：开通/设置，通和挡都列。
    未配置现固件不上报 PG14/PG15，不画通/挡。
    """
    if mode_override in (0, 1, 2):
        code = int(mode_override)
    else:
        code = pkt.sensor_mode_code()
    always = str(beam_detail or "exception") == "always"
    show_ir = bool(ir_installed) and code == MASTER_SENSOR_MODE_IR
    show_radar = code == MASTER_SENSOR_MODE_RADAR
    mode = format_sensor_mode_brief(pkt, lang=lang, mode_override=code)
    if lang == "en":
        parts = [mode]
        if show_ir:
            parts.extend(format_ir_beam_states(pkt, lang="en", only_blocked=not always))
        if show_radar and pkt.radar_gate:
            parts.append("RADAR occupied")
        elif show_radar and always:
            parts.append("RADAR clear")
        if pkt.relay0 or pkt.relay1 or pkt.relay2:
            parts.append("R%d%d%d" % (int(pkt.relay0), int(pkt.relay1), int(pkt.relay2)))
        return ", ".join(parts) if parts else "Idle"
    parts = [mode]
    if show_ir:
        parts.extend(format_ir_beam_states(pkt, lang="zh", only_blocked=not always))
    if show_radar and pkt.radar_gate:
        parts.append("\u96f7\u8fbe\u5360\u7528")
    elif show_radar and always:
        parts.append("\u96f7\u8fbe\u7a7a\u95f2")
    if pkt.relay0 or pkt.relay1 or pkt.relay2:
        parts.append(
            "\u7ee7\u7535\u5668 %d/%d/%d" % (int(pkt.relay0), int(pkt.relay1), int(pkt.relay2))
        )
    return "\u3001".join(parts) if parts else "\u901a\u9053\u7a7a\u95f2"
