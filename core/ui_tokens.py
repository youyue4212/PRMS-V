# -*- coding: utf-8 -*-
"""Shared industrial HMI visual tokens (Qt pages + Web should converge here)."""

# Surfaces
BG = "#1a1a1a"
BG_ELEVATED = "#1f1f1f"
PANEL = "#2a2a2a"
BORDER = "#333333"
BORDER_SOFT = "#444444"

# Semantic
OK = "#4caf50"
WARN = "#ff9800"
ALARM = "#ff4444"
DANGER = "#c62828"
INFO = "#2196F3"
MUTED = "#aaaaaa"
TEXT = "#ffffff"
TEXT_DIM = "#cccccc"

# Geometry
RADIUS_CARD = 10
RADIUS_BTN = 8
TOUCH_H = 44
PAGE_TITLE_PX = 22

# Control-room (PC) typography — tablet px baseline × scale for viewing distance
CONTROL_ROOM_FONT_SCALE = 1.4
# Count-rate digits (CPS) get an extra bump — primary readout at desk viewing distance
CONTROL_ROOM_CPS_EXTRA = 1.32


def cr_px(n: int) -> int:
    """Scale a tablet-baseline px size for control-room desktop UI."""
    return max(1, int(round(n * CONTROL_ROOM_FONT_SCALE)))


def cr_cps_px(n: int) -> int:
    """Scale CPS / count-rate numerals (larger than general UI text)."""
    return max(1, int(round(n * CONTROL_ROOM_FONT_SCALE * CONTROL_ROOM_CPS_EXTRA)))


def cps_digit_scale(text) -> float:
    """Shrink CPS numerals when digit count grows so the unit label stays separated."""
    s = str(text or "").strip().replace(",", "")
    if not s or s == "--":
        return 1.0
    n = len(s)
    if n <= 5:
        return 1.0
    if n == 6:
        return 0.82
    if n == 7:
        return 0.68
    return 0.55

# Common stylesheets
PAGE_TITLE_QSS = f"""
    QLabel {{
        color: {TEXT};
        font-size: {PAGE_TITLE_PX}px !important;
        font-weight: bold !important;
        margin-bottom: 8px;
        background: transparent;
        border: none;
    }}
"""

TOUCH_BTN_QSS = f"""
    QPushButton {{
        min-height: {TOUCH_H}px;
        border: none;
        border-radius: {RADIUS_BTN}px;
        font-size: 14px;
        font-weight: bold;
        padding: 0 16px;
        color: white;
    }}
"""
