# -*- coding: utf-8 -*-
"""相机配置解析与 Passage 字段自检。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vehicle.camera_config import parse_rtsp_host_user
from core.vehicle.passage_fsm import Passage


def main():
    h, u, p = parse_rtsp_host_user("rtsp://admin:pass@192.168.1.64:554/Streaming/Channels/102")
    assert h == "192.168.1.64" and u == "admin" and p == "pass"
    row = Passage(passage_id="t-1", t1_ms=0, length_m=6, v_limit_kmh=8)
    row.image_paths = "/tmp/a.jpg;/tmp/b.jpg"
    d = row.as_row()
    assert d.get("image_paths") == "/tmp/a.jpg;/tmp/b.jpg"
    print("OK camera_selfcheck")


if __name__ == "__main__":
    main()
