"""报警灵敏度 M（1.0~10.0）与探头 TCP 0x0C 载荷编解码。"""

M_MIN = 1.0
M_MAX = 10.0


def clamp_m(m) -> float:
    try:
        v = float(m)
    except (TypeError, ValueError):
        v = 3.0
    if v < M_MIN:
        return M_MIN
    if v > M_MAX:
        return M_MAX
    return v


def encode_0x0c_bytes(m) -> tuple:
    """返回 (b4, b5) 供 0x55 0xAA 0x03 0x0C [b4] [b5] 使用。"""
    m = clamp_m(m)
    rounded = int(round(m))
    if abs(m - float(rounded)) < 0.05 and M_MIN <= rounded <= 10:
        return int(rounded), 0
    raw = int(round(m * 10.0))
    if raw < 10:
        raw = 10
    if raw > 100:
        raw = 100
    return raw & 0xFF, (raw >> 8) & 0xFF


def decode_0x0c_bytes(b4: int, b5: int) -> float:
    b4 = int(b4) & 0xFF
    b5 = int(b5) & 0xFF
    if b5 == 0 and b4 <= 10:
        return clamp_m(float(b4 if b4 >= 1 else 1))
    raw = b4 | (b5 << 8)
    return clamp_m(raw / 10.0)


def format_m_display(m) -> str:
    m = clamp_m(m)
    if abs(m - round(m)) < 0.05:
        return str(int(round(m)))
    return f"{m:.1f}"


def decode_feedback_x10(value: int) -> float:
    """探头 CmdFeedback 0x0C/0x0F 的 value 为 round(M×10)。"""
    try:
        raw = int(value) & 0xFFFF
    except (TypeError, ValueError):
        return 3.0
    if raw <= 0:
        return 3.0
    return clamp_m(raw / 10.0)
