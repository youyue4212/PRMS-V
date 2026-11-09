# -*- coding: utf-8 -*-
"""ANPR HTTP 报文解析自检。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vehicle.plate_parse import extract_plate_from_body


def main():
    xml2 = "<licensePlate>京A12345</licensePlate>".encode("utf-8")
    assert extract_plate_from_body(xml2) == "京A12345"
    assert extract_plate_from_body('{"plateNo":"\u6caaB88888"}'.encode("utf-8")) == "\u6caaB88888"
    print("OK plate_selfcheck")


if __name__ == "__main__":
    main()
