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
