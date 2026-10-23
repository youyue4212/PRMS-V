#!/usr/bin/env python3
"""方案 A 上位机编解码自检（与探头 0x0C 一致）。"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.sensitivity_m import (
    clamp_m,
    encode_0x0c_bytes,
    decode_0x0c_bytes,
    decode_feedback_x10,
    format_m_display,
)


def main():
    cases = [1.0, 3.0, 3.5, 10.0, 10.5]
    ok = True
    for m in cases:
        b4, b5 = encode_0x0c_bytes(m)
        back = decode_0x0c_bytes(b4, b5)
        if abs(back - clamp_m(m)) > 0.11:
            print(f"FAIL m={m} bytes=({b4},{b5}) back={back}")
            ok = False
        else:
            print(f"OK  m={format_m_display(m):>4}  0x0C [{b4:02X} {b5:02X}] -> {back}")
    # 旧整数路径
    b4, b5 = encode_0x0c_bytes(4)
    assert b4 == 4 and b5 == 0
    print("Legacy int path 4.0 OK")
    assert abs(decode_feedback_x10(35) - 3.5) < 0.01
    assert decode_feedback_x10(30) == 3.0
    print("0x0F feedback x10 decode OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
