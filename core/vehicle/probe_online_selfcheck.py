# -*- coding: utf-8 -*-
"""探头 online 防抖单元自检（无 GUI）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.probe_online_hold import PROBE_OFFLINE_HOLD_SEC, debounce_probe_online


def main():
    hold = {}
    t0 = 2_000.0
    assert debounce_probe_online(hold, 0, True, 10, t0)
    hold[0]["last"] = (10, True, False)
    assert debounce_probe_online(hold, 0, False, 0, t0 + 0.2)
    assert not debounce_probe_online(hold, 0, False, 0, t0 + PROBE_OFFLINE_HOLD_SEC + 0.3)
    print("ok probe online hold")


if __name__ == "__main__":
    main()
