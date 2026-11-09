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
CONTROL_ROOM_FONT_SCALE = 1.1
# Count-rate digits (CPS) get an extra bump — primary readout at desk viewing distance
CONTROL_ROOM_CPS_EXTRA = 1.32


def cr_px(n: int) -> int:
    """Scale a tablet-baseline px size for control-room desktop UI."""
    return max(1, int(round(n * CONTROL_ROOM_FONT_SCALE)))


def cr_cps_px(n: int) -> int:
    """Scale CPS / count-rate numerals (larger than general UI text)."""
    return max(1, int(round(n * CONTROL_ROOM_FONT_SCALE * CONTROL_ROOM_CPS_EXTRA)))


# Duty-wall chrome: status bar + header pills/buttons share one size family
CR_CHROME_H = cr_px(30)
CR_CHROME_FONT_PX = cr_px(12)
CR_STATUS_BAR_H = cr_px(36)
# 底部导航文字（平板 / 主控室）
NAV_BAR_FONT_PX = 14
NAV_BAR_FONT_PX_CR = cr_px(14)


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

# Settings page: one dark surface — groups outlined, not filled (avoids black/gray stripes)
CR_SETTINGS_PAGE_QSS = f"""
    QWidget {{
        background-color: {BG};
        color: {TEXT};
    }}
    QGroupBox {{
        color: {TEXT};
        font-size: {CR_CHROME_FONT_PX}px;
        font-weight: bold;
        border: 1px solid {BORDER};
        border-radius: 8px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        background-color: {BG};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {TEXT_DIM};
        background-color: {BG};
    }}
    QGroupBox QLabel {{
        color: {TEXT};
        font-size: {CR_CHROME_FONT_PX}px;
        font-weight: normal;
        background: transparent;
    }}
    QCheckBox {{
        color: {TEXT};
        font-size: {CR_CHROME_FONT_PX}px;
        spacing: 8px;
        background: transparent;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        min-height: {CR_CHROME_H}px;
        max-height: {CR_CHROME_H + 4}px;
        font-size: {CR_CHROME_FONT_PX}px;
        padding: 2px 8px;
        background: {BG_ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER_SOFT};
        border-radius: 4px;
    }}
    QPushButton {{
        min-height: {CR_CHROME_H}px;
        font-size: {CR_CHROME_FONT_PX}px;
        font-weight: bold;
        padding: 0 12px;
        border: none;
        border-radius: {RADIUS_BTN}px;
        color: white;
        background-color: #455a64;
    }}
    QPushButton:pressed {{
        background-color: #37474f;
    }}
    QPushButton:disabled {{
        background-color: #555555;
        color: #999999;
    }}
"""
