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
    invalid_reason: str = ""
    r2_on: bool = False

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
            "hit_probe_mask": self.hit_probe_mask,
            "cps": self.cps,
            "invalid_reason": self.invalid_reason,
            "r2_on": self.r2_on,
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
            )

        if self.open is not None:
            decision = int(getattr(packet, "decision_result", 0) or 0)
            if decision in HARD_ALARM or decision == 0xFF:
                self.open.decision = decision
            elif self.open.decision == 0:
                self.open.decision = decision
            if decision in HARD_ALARM:
                self.open.hard_alarm = True
            self.open.hit_probe_mask = int(getattr(packet, "hit_probe_mask", 0) or 0)
            cps = list(getattr(packet, "probe_cps", []) or [])
            self.open.cps = cps[:2]
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

    def _close(self, row: Passage) -> Passage:
        self.last_closed = row
        self.open = None
        if self.store is not None:
            self.store.insert(row.as_row())
        return row
