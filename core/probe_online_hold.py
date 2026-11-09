# -*- coding: utf-8 -*-
"""探头在线防抖：与行人首页 PROBE_OFFLINE_HOLD 一致，按 L2 槽位键控。"""

from __future__ import annotations

PROBE_OFFLINE_HOLD_SEC = 2.0


def debounce_probe_online(
    tile_hold: dict,
    slot: int,
    want_online: bool,
    cps: int,
    now: float,
    hold_sec: float = PROBE_OFFLINE_HOLD_SEC,
) -> bool:
    """L2 online_mask 偶发掉 bit 时，在 hold_sec 内仍视为在线（与 home_page 相同）。"""
    st = tile_hold.setdefault(
        int(slot),
        {"offline_since": None, "last": None},
    )
    if want_online or int(cps or 0) > 0:
        st["offline_since"] = None
        return True
    if st["offline_since"] is None:
        st["offline_since"] = now
        if st.get("last") and st["last"][1]:
            return True
        return False
    if (now - float(st["offline_since"])) < float(hold_sec):
        return True
    return False
