# -*- coding: utf-8 -*-
"""PRMS-V-11 通行状态机。t1/t2 取 L2 io_status bit0/bit1 的 0→1。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.vehicle.speed import delta_ms, speed_kmh

HARD_ALARM = (0x02, 0x03)
# 通道内超过此时长仍无出口沿，本趟作废。L2 约 1 秒一包，用主控毫秒差。
OPEN_TIMEOUT_MS = 180_000


@dataclass
class Passage:
    passage_id: str
    t1_ms: int
    length_m: float
    v_limit_kmh: float
    t2_ms: int | None = None
    speed_kmh: float | None = None
    overspeed: bool = False
    decision: int = 0
    hard_alarm: bool = False
    hit_probe_mask: int = 0
    cps: list = field(default_factory=list)
    peak_cps: list = field(default_factory=list)
    trigger_cps: list = field(default_factory=list)
    invalid_reason: str = ""
    plate: str = ""
    r2_on: bool = False
    opened_at: float = 0.0
    closed_at: float = 0.0
    decision_text: str = ""
    context: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        return {
            "passage_id": self.passage_id,
            "t1_ms": self.t1_ms,
            "t2_ms": self.t2_ms,
            "length_m": self.length_m,
            "speed_kmh": self.speed_kmh,
            "v_limit_kmh": self.v_limit_kmh,
            "overspeed": self.overspeed,
            "decision": self.decision,
            "decision_text": self.decision_text,
            "hard_alarm": self.hard_alarm,
            "hit_probe_mask": self.hit_probe_mask,
            "cps": self.cps,
            "peak_cps": self.peak_cps,
            "trigger_cps": self.trigger_cps,
            "invalid_reason": self.invalid_reason,
            "plate": self.plate,
            "r2_on": self.r2_on,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "context": dict(self.context),
        }


class PassageFsm:
    def __init__(self, length_m: float, v_limit_kmh: float, store=None):
        self.length_m = float(length_m)
        self.v_limit_kmh = float(v_limit_kmh)
        self.store = store
        self._prev_entry = False
        self._prev_exit = False
        self.open: Passage | None = None
        self.last_closed: Passage | None = None
        self._seq = 0

    def update_params(self, length_m: float, v_limit_kmh: float) -> None:
        self.length_m = float(length_m)
        self.v_limit_kmh = float(v_limit_kmh)

    def on_packet(self, packet) -> Passage | None:
        entry = bool(getattr(packet, "ir_entry", False))
        exit_on = bool(getattr(packet, "ir_exit", False))
        ts = int(getattr(packet, "timestamp_ms", 0) or 0)
        closed = None

        if self.open is not None and delta_ms(self.open.t1_ms, ts) > OPEN_TIMEOUT_MS:
            self.open.invalid_reason = "timeout"
            closed = self._close(self.open)

        if (not self._prev_entry) and entry:
            if self.open is not None:
                self.open.invalid_reason = self.open.invalid_reason or "new_entry"
                closed = self._close(self.open)
            self._seq += 1
            self.open = Passage(
                passage_id=f"{int(time.time())}-{self._seq}",
                t1_ms=ts,
                length_m=self.length_m,
                v_limit_kmh=self.v_limit_kmh,
                opened_at=time.time(),
            )

        if self.open is not None:
            self._latch_packet(packet)
            if (not self._prev_exit) and exit_on and self.open.t1_ms != ts:
                closed = self._finish(packet, ts)

        self._prev_entry = entry
        self._prev_exit = exit_on
        return closed

    def _finish(self, packet, ts: int) -> Passage:
        row = self.open
        assert row is not None
        row.t2_ms = ts
        online = int(getattr(packet, "online_mask", 0) or 0)
        if online == 0:
            row.invalid_reason = "offline"
        else:
            v = speed_kmh(row.length_m, row.t1_ms, ts)
            if v is None:
                row.invalid_reason = "bad_dt"
            else:
                row.speed_kmh = v
                row.overspeed = v > row.v_limit_kmh
        # 超速可以亮 R2；硬报未消警时不要把 R2 交给道闸
        row.r2_on = bool(row.overspeed) and not row.hard_alarm and not row.invalid_reason
        return self._close(row)

    def _latch_packet(self, packet) -> None:
        row = self.open
        if row is None:
            return
        decision = int(getattr(packet, "decision_result", 0) or 0)
        if decision in HARD_ALARM or decision == 0xFF:
            if not row.hard_alarm:
                row.decision_text = self._decision_text(packet, decision)
            row.decision = decision
        elif row.decision == 0 and decision:
            row.decision = decision
            row.decision_text = self._decision_text(packet, decision)
        if decision in HARD_ALARM and not row.hard_alarm:
            row.trigger_cps = list(getattr(packet, "probe_cps", []) or [])
            row.hard_alarm = True
        elif decision in HARD_ALARM:
            row.hard_alarm = True
        mask = int(getattr(packet, "hit_probe_mask", 0) or 0)
        if row.hard_alarm:
            row.hit_probe_mask |= mask
        else:
            row.hit_probe_mask = mask
        cps = [int(v or 0) for v in list(getattr(packet, "probe_cps", []) or [])]
        row.cps = cps
        if len(row.peak_cps) < len(cps):
            row.peak_cps.extend([0] * (len(cps) - len(row.peak_cps)))
        for i, value in enumerate(cps):
            row.peak_cps[i] = max(int(row.peak_cps[i] or 0), value)
        if not row.context:
            row.context = self._context_from_packet(packet)

    @staticmethod
    def _decision_text(packet, decision: int) -> str:
        try:
            return str(packet.decision_text("zh") or "")
        except Exception:
            return "0x%02X" % int(decision or 0)

    @staticmethod
    def _context_from_packet(packet) -> dict:
        def _int(name):
            try:
                return int(getattr(packet, name, 0) or 0)
            except (TypeError, ValueError):
                return 0

        sensor = None
        try:
            sensor = int(packet.sensor_mode_code())
        except Exception:
            sensor = None
        return {
            "master_id": _int("master_id"),
            "online_mask": _int("online_mask"),
            "total_cps": _int("total_cps"),
            "radar_gate": bool(getattr(packet, "radar_gate", False)),
            "sensor_mode": sensor,
            "ungated": bool(getattr(packet, "ir_degraded", False)),
            "latch_mode": bool(getattr(packet, "alarm_latch_mode", False)),
            "match_threshold_n": _int("match_threshold_n"),
            "window_x_sec": _int("window_x_sec"),
            "window_y_sec": _int("window_y_sec"),
        }

    def _close(self, row: Passage) -> Passage:
        row.closed_at = time.time()
        self.last_closed = row
        self.open = None
        if self.store is not None:
            self.store.insert(row.as_row())
        return row
