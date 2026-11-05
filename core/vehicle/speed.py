# -*- coding: utf-8 -*-
"""PRMS-V-11 车速：v = L / (t2 - t1)，只在上位机计算。"""

from __future__ import annotations


def delta_ms(t1_ms: int, t2_ms: int) -> int:
    """主控 timestamp_ms 为 uint32，允许回绕。"""
    return (int(t2_ms) - int(t1_ms)) & 0xFFFFFFFF


def speed_kmh(length_m: float, t1_ms: int, t2_ms: int) -> float | None:
    dt_ms = delta_ms(t1_ms, t2_ms)
    if dt_ms <= 0 or length_m <= 0:
        return None
    return float(length_m) / (dt_ms / 1000.0) * 3.6
