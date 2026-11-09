# -*- coding: utf-8 -*-
"""RTSP URL 规范化自检。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vehicle.rtsp_preview import normalize_rtsp_url


def main():
    assert normalize_rtsp_url("") == ""
    assert normalize_rtsp_url("  ") == ""
    assert normalize_rtsp_url("192.168.1.64:554/stream1") == "rtsp://192.168.1.64:554/stream1"
    assert normalize_rtsp_url("rtsp://cam/live") == "rtsp://cam/live"
    print("OK rtsp_selfcheck")


if __name__ == "__main__":
    main()
