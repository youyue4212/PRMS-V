# -*- coding: utf-8 -*-
"""车辆通道主界面的样式表。取色自图1–图4效果图；键名对应 CSS 变量（--bg → "bg"），改样式只改这里。"""

COLOR = {
    "bg": "#02050a",
    "card": "#060b12",
    "card-dim": "#040910",
    "line": "#151b24",
    "text": "#e8eaec",
    "text-soft": "#d0d4d8",
    "muted": "#8a9099",
    "white": "#ffffff",
    "ok": "#5fbf52",
    "alarm": "#e5302f",
    "amber": "#eca845",
    "fault": "#ff8a3d",
    "scroll-handle": "#2a3340",
    "pill-bg": "#0b121b",
    "capture-bg": "#05080d",
    "trouble-text": "#ffd7c2",
    "login-bg": "#2e7d32",
    "login-pressed": "#1b5e20",
    "reset-bg": "#9c0f12",
    "reset-pressed": "#6e0a0c",
    "reset-off-bg": "#2a2f36",
    "recheck-pressed": "#2a2410",
    "icon-alarm": "#f2c14e",
    "icon-fault": "#ffe2cc",
    "unit": "#e6e6e6",
    "grid": "#1c202b",
}

# 顶栏色带：(左端色, 标题字色)；色带从左斜边向右渐隐到底色。
BAND = {
    "ok": ("#0e4d16", "#ffffff"),
    "alarm": ("#8a0204", "#ffffff"),
    "amber": ("#0a3a12", "#f0b44c"),
    "fault": ("#7a3410", "#ffe2cc"),
}

# 探头卡：(底色, 描边, 数字/状态色)；alarm 与消警 reset-bg / COLOR.alarm 同一套红
CARD = {
    "ok": ("#04140b", "#16261b", "#5fbf52"),
    "alarm": ("#3a0a0c", "#9c0f12", "#e5302f"),
    "amber": ("#0b1508", "#2a2a12", "#eca845"),
    "fault": ("#1c1510", "#5a3418", "#ff8a3d"),
    "offline": ("#040910", "#12161e", "#9aa0a6"),
}

HISTORY_ROW = {
    "invalid": "#0a0e14",
    "hard": "#3a0a0c",
    "fast": "#2e2410",
    "pass": "#132a18",
    "hard-text": "#ff6b6b",
    "pass-time": "#8fb98a",
    "fast-time": "#e0b080",
}

FONT = '"Microsoft YaHei", "Segoe UI"'
FONT_DIGIT_FAMILY = "Bahnschrift SemiBold"
FONT_DIGIT = '"Bahnschrift SemiBold", "Segoe UI", Arial'

SIZE = {
    "banner-h": 54,
    "banner-title": 32,
    "brand": 21,
    "card-title": 18,
    "card-location": 16,
    "card-status": 19,
    "card-status-compact": 15,
    "card-empty": 20,
    "card-dot": 14,
    "cps-base": 52,
    "cps-max": 78,
    "fault-word": 32,
    "fault-word-compact": 20,
    "field-key": 16,
    "field-value": 16,
    "field-alert": 22,
    "reset": 28,
    "section-title": 16,
    "history": 16,
    "history-row-h": 36,
    "radius-card": 6,
}
