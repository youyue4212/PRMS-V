# -*- coding: utf-8 -*-
"""车辆通道主界面。版式按效果图：顶栏色带、左探头、中抓拍、右本次通行、底历史。"""

from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.ui_tokens import cps_digit_scale

_BG = "#0c100e"
_CARD = "#141c18"
_CARD_DIM = "#101714"
_LINE = "#24302a"
_TEXT = "#e8ece9"
_MUTED = "#8b978f"
_GREEN = "#3dd68c"
_RED = "#ff4d4d"
_AMBER = "#f0c14a"
_FONT = '"Microsoft YaHei", "Segoe UI"'
_CPS_BASE_PX = 48

_BAND = {
    "ok": ("#1f9d46", "#ffffff"),
    "alarm": ("#d32f2f", "#ffffff"),
    "amber": ("#6e5b16", "#f5d76e"),
    "fault": ("#8a3a12", "#ffe2cc"),
}

_FAULT = "#ff8a3d"

_TONE = {
    "ok": _GREEN,
    "alarm": _RED,
    "amber": _AMBER,
    "fault": _FAULT,
    "offline": _MUTED,
}

_SCROLL_QSS = (
    "QScrollArea { background: transparent; border: none; }"
    "QScrollArea > QWidget > QWidget { background: transparent; }"
    "QScrollBar:vertical { background: %s; width: 8px; border: none; }"
    "QScrollBar::handle:vertical { background: #34443b; border-radius: 4px; min-height: 30px; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }" % _BG
)

_HISTORY_COLS = ("通行时间", "通道", "车牌", "γ总计", "峰值", "辐射结果", "速度", "超速", "通行结果")


def _trefoil(size: int, color: str, ring: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    if ring:
        p.setPen(QPen(c, max(1.4, size * 0.06)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    inset = size * (0.16 if ring else 0.08)
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    for center in (90, 210, 330):
        p.drawPie(rect, int((center - 26) * 16), int(52 * 16))
    p.setBrush(QColor(_BG))
    hole = size * 0.10
    p.drawEllipse(QRectF(size / 2 - hole, size / 2 - hole, hole * 2, hole * 2))
    p.end()
    return pm


def _wrench(size: int, color: str) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(QPen(c, max(2.5, size * 0.16), Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(size * 0.22, size * 0.80), QPointF(size * 0.58, size * 0.44))
    p.setPen(QPen(c, max(2.0, size * 0.12), Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(size * 0.48, size * 0.12, size * 0.40, size * 0.40), 200 * 16, 250 * 16)
    p.end()
    return pm


class _StatusBanner(QWidget):
    """左黑底产品名，中间斜切色带放状态，右侧监测软件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tone = "ok"
        self.setFixedHeight(58)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(_trefoil(22, "#ffffff", ring=True))
        self.brand = QLabel("车辆通道放射性检测 PRMS-V")
        self.brand.setStyleSheet(
            "color: #ffffff; font-size: 15px; font-weight: 600; background: transparent; border: none; font-family: %s;"
            % _FONT
        )
        brand.setContentsMargins(0, 0, 0, 0)
        brand.addWidget(self.brand_icon)
        brand.addWidget(self.brand)
        brand.addStretch(1)
        brand_wrap = QWidget()
        brand_wrap.setStyleSheet("background: transparent;")
        brand_wrap.setLayout(brand)
        lay.addWidget(brand_wrap, 1)

        center = QHBoxLayout()
        center.setSpacing(8)
        self.status_icon = QLabel()
        self.status_icon.hide()
        self.banner_label = QLabel("通道空闲")
        self.chip_host = QHBoxLayout()
        self.chip_host.setSpacing(6)
        center.addWidget(self.status_icon)
        center.addWidget(self.banner_label)
        center.addLayout(self.chip_host)
        center_wrap = QWidget()
        center_wrap.setStyleSheet("background: transparent;")
        center_wrap.setLayout(center)
        lay.addWidget(center_wrap, 0, Qt.AlignCenter)
        self._center_wrap = center_wrap

        self.mode_label = QLabel("监测软件")
        self.mode_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mode_label.setStyleSheet(
            "color: rgba(255,255,255,0.82); font-size: 13px; background: transparent; border: none; font-family: %s;"
            % _FONT
        )
        self.session_label = QLabel("")
        self.session_label.setStyleSheet(
            "color: #ffffff; font-size: 13px; background: transparent; border: none; font-family: %s;" % _FONT
        )
        self.session_label.hide()
        self.login_btn = QPushButton("登录")
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setFixedHeight(28)
        self.login_btn.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; border: none; border-radius: 6px;"
            " padding: 0 12px; font-size: 13px; font-weight: 700; font-family: %s; }"
            "QPushButton:pressed { background: #1b5e20; }" % _FONT
        )
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        right.addWidget(self.session_label)
        right.addWidget(self.login_btn)
        right.addWidget(self.mode_label)
        right_wrap = QWidget()
        right_wrap.setStyleSheet("background: transparent;")
        right_wrap.setLayout(right)
        lay.addWidget(right_wrap, 1)

    def set_tone(self, tone: str):
        self._tone = tone or "ok"
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(_BG))
        w = self.width()
        h = self.height()
        color = QColor(_BAND.get(self._tone, _BAND["ok"])[0])
        slant = 16
        geo = self._center_wrap.geometry()
        left = min(w * 0.38, geo.left() - slant - 10)
        right = max(w * 0.78, geo.right() + slant + 14)
        path = QPainterPath()
        path.moveTo(left + slant, 0)
        path.lineTo(right, 0)
        path.lineTo(right - slant, h)
        path.lineTo(left, h)
        path.closeSubpath()
        p.fillPath(path, color)
        p.end()


class _ProbeCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("probeCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dot = QLabel("●")
        self.title = QLabel()
        self.location = QLabel()
        self.cps = QLabel("")
        self.cps.setAlignment(Qt.AlignCenter)
        self.unit = QLabel("cps")
        self.unit.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.unit.hide()
        self.status = QLabel("未接入")
        self._cps_color = _MUTED
        self._compact = None
        self.set_compact(False)

    def set_compact(self, compact: bool):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        old = self.layout()
        if old is not None:
            sip.delete(old)
        if compact:
            self.setMinimumHeight(52)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(10, 4, 10, 4)
            lay.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(6)
            head.addWidget(self.dot, 0, Qt.AlignVCenter)
            head.addWidget(self.title, 0, Qt.AlignVCenter)
            head.addWidget(self.location, 0, Qt.AlignVCenter)
            head.addStretch(1)
            head.addWidget(self.status, 0, Qt.AlignVCenter)
            lay.addLayout(head)
            lay.addStretch(1)
            num = QHBoxLayout()
            num.setSpacing(6)
            num.addStretch(1)
            num.addWidget(self.cps, 0, Qt.AlignVCenter)
            num.addWidget(self.unit, 0, Qt.AlignVCenter)
            num.addStretch(1)
            lay.addLayout(num)
            lay.addStretch(1)
        else:
            self.setMinimumHeight(96)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(14, 10, 14, 12)
            lay.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(6)
            head.addWidget(self.dot, 0, Qt.AlignVCenter)
            head.addWidget(self.title, 0, Qt.AlignVCenter)
            head.addStretch(1)
            lay.addLayout(head)
            lay.addWidget(self.location)
            lay.addStretch(1)
            num = QHBoxLayout()
            num.setSpacing(8)
            num.addStretch(1)
            num.addWidget(self.cps, 0, Qt.AlignVCenter)
            num.addWidget(self.unit, 0, Qt.AlignVCenter)
            num.addStretch(1)
            lay.addLayout(num)
            lay.addStretch(1)
            lay.addWidget(self.status)
        self._fit_cps()

    def _fit_cps(self):
        text = self.cps.text()
        unit_w = self.unit.sizeHint().width() if not self.unit.isHidden() else 0
        if self._compact:
            base = max(16, min(36, int((self.height() - 30) * 0.95)))
            room = self.width() - 20 - 6 - unit_w
        else:
            base = max(_CPS_BASE_PX, min(72, int(self.height() * 0.26)))
            base = min(base, max(18, int((self.height() - 84) * 0.9)))
            room = self.width() - 28 - 8 - unit_w
        px = max(12, int(round(base * cps_digit_scale(text))))
        if text and room > 40:
            font = QFont("Consolas")
            font.setBold(True)
            font.setPixelSize(px)
            need = QFontMetrics(font).horizontalAdvance(text)
            if need > room:
                px = max(12, int(px * room / need))
        self.cps.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 700; background: transparent; border: none;"
            " font-family: Consolas, monospace;" % (self._cps_color, px)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_cps()

    def apply_card(self, card: dict):
        tone = card.get("tone") or "offline"
        status = card.get("status") or ""
        color = _TONE.get(tone, _MUTED)
        empty = status == "未接入"
        self.title.setText("" if empty else (card.get("title") or ""))
        self.location.setText("" if empty else (card.get("location") or ""))
        self.dot.setVisible(not empty)
        self.dot.setStyleSheet(
            "color: %s; font-size: 11px; background: transparent; border: none;" % color
        )
        self.title.setStyleSheet(
            "color: %s; font-size: 14px; font-weight: 600; background: transparent; border: none; font-family: %s;"
            % (_TEXT, _FONT)
        )
        self.location.setStyleSheet(
            "color: %s; font-size: 12px; background: transparent; border: none; font-family: %s;" % (_MUTED, _FONT)
        )
        self.unit.hide()
        if empty:
            self.cps.hide()
            self.cps.setText("")
            self.status.setText("未接入")
            self.status.setAlignment(Qt.AlignCenter)
        elif status == "高压偏离" and str(card.get("cps_text") or "0") in ("", "0"):
            self.cps.setText("—")
            self.cps.show()
            self.status.setText(status)
            self.status.setAlignment(Qt.AlignLeft)
        elif card.get("show_cps"):
            self.cps.setText(str(card.get("cps_text") or ""))
            self.cps.show()
            self.unit.show()
            self.status.setText(status)
            self.status.setAlignment(Qt.AlignLeft)
        else:
            self.cps.hide()
            self.cps.setText("")
            self.status.setText(status)
            self.status.setAlignment(Qt.AlignLeft)
        if self._compact and not empty:
            self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._cps_color = color
        small = 13 if self._compact else 16
        self.unit.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; background: transparent; border: none; font-family: %s;"
            % (color, small, _FONT)
        )
        if empty:
            self.status.setStyleSheet(
                "color: %s; font-size: %dpx; background: transparent; border: none; font-family: %s;"
                % (_MUTED, small, _FONT)
            )
        else:
            self.status.setStyleSheet(
                "color: %s; font-size: %dpx; font-weight: 700; background: transparent; border: none; font-family: %s;"
                % (color, small, _FONT)
            )
        self._fit_cps()
        border = "#2a1616" if tone in ("alarm", "fault") else ("#3a3214" if tone == "amber" else _LINE)
        bg = "#1a1212" if tone in ("alarm", "fault") else (_CARD_DIM if empty else _CARD)
        self.setStyleSheet(
            "QFrame#probeCard { background: %s; border: 1px solid %s; border-radius: 10px; }" % (bg, border)
        )


class VehicleDashboardPage(QWidget):
    """图1至图4。消警只在辐射硬报时出现。"""

    reset_requested = pyqtSignal()
    plate_edited = pyqtSignal(str)
    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("vehicleDash")
        self._cards = []
        self._field_values = {}
        self._field_keys = {}
        self._field_rows = {}
        self._building_plate = False
        self._reset_allowed = False
        self._reset_wanted = False
        self._logged_in = False
        self._build()
        self.banner.login_btn.clicked.connect(self._on_session_click)

    def _build(self):
        self.setStyleSheet(
            "QWidget#vehicleDash { background: %s; font-family: %s; }"
            "QWidget#vehicleDash QLabel { background: transparent; border: none; }"
            % (_BG, _FONT)
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        self.banner = _StatusBanner()
        self.banner_label = self.banner.banner_label
        self.chip_host = self.banner.chip_host
        self.status_icon = self.banner.status_icon
        root.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(12)

        probe_col = QVBoxLayout()
        probe_col.setSpacing(8)
        self.probe_grid = QGridLayout()
        self.probe_grid.setSpacing(8)
        probe_col.setContentsMargins(0, 0, 0, 0)
        probe_col.addLayout(self.probe_grid, 1)
        probe_host = QWidget()
        probe_host.setObjectName("probeHost")
        probe_host.setStyleSheet("QWidget#probeHost { background: transparent; }")
        probe_host.setLayout(probe_col)
        self.probe_scroll = QScrollArea()
        self.probe_scroll.setWidgetResizable(True)
        self.probe_scroll.setFrameShape(QFrame.NoFrame)
        self.probe_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.probe_scroll.setStyleSheet(_SCROLL_QSS)
        self.probe_scroll.setWidget(probe_host)
        self.probe_scroll.setMinimumWidth(380)
        body.addWidget(self.probe_scroll, 4)

        cap_col = QVBoxLayout()
        cap_col.setSpacing(6)
        cap_head = QHBoxLayout()
        cap_title = QLabel("抓拍图像")
        cap_title.setStyleSheet("color: %s; font-size: 13px; font-family: %s;" % (_MUTED, _FONT))
        self.lane_label = QLabel("通道 03")
        self.lane_label.setAlignment(Qt.AlignCenter)
        self.lane_label.setStyleSheet(
            "color: %s; background: #1c2620; border: 1px solid %s; border-radius: 9px;"
            " padding: 2px 10px; font-size: 12px; font-family: %s;" % (_TEXT, _LINE, _FONT)
        )
        cap_head.addWidget(cap_title)
        cap_head.addStretch(1)
        cap_head.addWidget(self.lane_label)
        cap_col.addLayout(cap_head)
        self.capture = QLabel("等待过车")
        self.capture.setObjectName("dashCapture")
        self.capture.setAlignment(Qt.AlignCenter)
        self.capture.setMinimumHeight(240)
        self.capture.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.capture.setStyleSheet(
            "QLabel#dashCapture { background: #070b09; color: #ffffff; border: 1px solid %s;"
            " border-radius: 10px; font-size: 28px; font-weight: 700; font-family: %s; }"
            % (_LINE, _FONT)
        )
        cap_col.addWidget(self.capture, 1)
        body.addLayout(cap_col, 6)

        side = QVBoxLayout()
        side.setContentsMargins(14, 12, 14, 12)
        side.setSpacing(0)
        side_head = QHBoxLayout()
        side_dot = QLabel("●")
        side_dot.setStyleSheet("color: %s; font-size: 11px;" % _GREEN)
        side_title = QLabel("本次通行")
        side_title.setStyleSheet(
            "color: %s; font-size: 15px; font-weight: 700; font-family: %s;" % (_TEXT, _FONT)
        )
        side_head.addWidget(side_dot)
        side_head.addWidget(side_title)
        side_head.addStretch(1)
        side.addLayout(side_head)
        side.addSpacing(6)
        self.plate_edit = QLineEdit()
        self.plate_edit.setPlaceholderText("— 可手补")
        self.plate_edit.setAlignment(Qt.AlignRight)
        self.plate_edit.setFixedHeight(26)
        self.plate_edit.setStyleSheet(
            "QLineEdit { background: transparent; color: %s; border: none; font-size: 14px; font-family: %s; }"
            % (_TEXT, _FONT)
        )
        self.plate_edit.editingFinished.connect(self._emit_plate)
        fields = QVBoxLayout()
        fields.setContentsMargins(0, 0, 6, 0)
        fields.setSpacing(0)
        for name in (
            "通道状态", "车牌", "车速", "限速", "超速",
            "辐射硬报", "峰值CPS", "γ总计", "命中掩码", "阈值说明",
        ):
            row = QHBoxLayout()
            row.setContentsMargins(0, 7, 0, 7)
            key = QLabel(name)
            key.setStyleSheet("color: %s; font-size: 13px; font-family: %s;" % (_MUTED, _FONT))
            val = QLabel("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setWordWrap(False)
            val.setStyleSheet(
                "color: %s; font-size: 14px; font-weight: 600; font-family: %s;" % (_TEXT, _FONT)
            )
            row.addWidget(key)
            row.addStretch(1)
            if name == "车牌":
                row.addWidget(self.plate_edit, 1)
            else:
                row.addWidget(val)
            wrap = QWidget()
            wrap.setLayout(row)
            wrap.setStyleSheet("border-bottom: 1px solid %s; background: transparent;" % _LINE)
            self._field_values[name] = val
            self._field_keys[name] = key
            self._field_rows[name] = wrap
            fields.addWidget(wrap)
        fields.addStretch(1)
        fields_host = QWidget()
        fields_host.setObjectName("sideFields")
        fields_host.setStyleSheet("QWidget#sideFields { background: transparent; }")
        fields_host.setLayout(fields)
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_scroll.setStyleSheet(_SCROLL_QSS)
        self.side_scroll.setWidget(fields_host)
        side.addWidget(self.side_scroll, 1)
        self.reset_btn = QPushButton("消警")
        self.reset_btn.setMinimumHeight(48)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.reset_btn.hide()
        self.reset_hint = QLabel("需管理员或维护员权限")
        self.reset_hint.setAlignment(Qt.AlignCenter)
        self.reset_hint.setStyleSheet("color: %s; font-size: 12px; font-family: %s;" % (_MUTED, _FONT))
        self.reset_hint.hide()
        self.recheck_btn = QPushButton("引导复检")
        self.recheck_btn.setMinimumHeight(40)
        self.recheck_btn.setCursor(Qt.PointingHandCursor)
        self.recheck_btn.setStyleSheet(
            "QPushButton { background: transparent; color: %s; font-size: 16px; font-weight: 700;"
            " border: 1px solid %s; border-radius: 6px; font-family: %s; margin-top: 8px; }"
            "QPushButton:pressed { background: #3a3214; }" % (_AMBER, _AMBER, _FONT)
        )
        self.recheck_btn.clicked.connect(self._show_recheck)
        self.recheck_btn.hide()
        self.recheck_text = QLabel("")
        self.recheck_text.setWordWrap(True)
        self.recheck_text.setStyleSheet(
            "color: %s; font-size: 13px; padding-top: 6px; font-family: %s;" % (_AMBER, _FONT)
        )
        self.recheck_text.hide()
        self.trouble = QLabel("")
        self.trouble.setWordWrap(True)
        self.trouble.setStyleSheet(
            "color: #ffd7c2; font-size: 13px; padding-top: 8px; font-family: %s;" % _FONT
        )
        self.trouble.hide()
        side.addWidget(self.reset_btn)
        side.addWidget(self.reset_hint)
        side.addWidget(self.recheck_btn)
        side.addWidget(self.recheck_text)
        side.addWidget(self.trouble)
        side_frame = QFrame()
        side_frame.setObjectName("dashSide")
        side_frame.setLayout(side)
        side_frame.setStyleSheet(
            "QFrame#dashSide { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (_CARD, _LINE)
        )
        side_frame.setMinimumWidth(280)
        body.addWidget(side_frame, 3)
        root.addLayout(body, 1)

        hist_title = QLabel("通行历史记录")
        hist_title.setStyleSheet(
            "color: %s; font-size: 14px; font-weight: 600; font-family: %s;" % (_TEXT, _FONT)
        )
        root.addWidget(hist_title)
        self.history = QTableWidget(0, len(_HISTORY_COLS))
        self.history.setHorizontalHeaderLabels(list(_HISTORY_COLS))
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history.setSelectionMode(QTableWidget.NoSelection)
        self.history.setShowGrid(False)
        self.history.setFocusPolicy(Qt.NoFocus)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setFixedHeight(32)
        header.setFont(QFont("Microsoft YaHei", 9))
        self.history.verticalHeader().setDefaultSectionSize(32)
        self.history.setStyleSheet(
            "QTableWidget { background: #101714; color: %s; border: 1px solid %s; border-radius: 8px;"
            " font-size: 13px; font-family: %s; }"
            "QHeaderView::section { background: #101714; color: %s; border: none; border-bottom: 1px solid %s;"
            " padding: 4px; font-size: 12px; font-family: %s; }"
            % (_TEXT, _LINE, _FONT, _MUTED, _LINE, _FONT)
        )
        self.history.setMinimumHeight(112)
        root.addWidget(self.history, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.history.setMaximumHeight(max(112, min(260, int(self.height() * 0.26))))

    def _emit_plate(self):
        if self._building_plate:
            return
        self.plate_edited.emit(self.plate_edit.text().strip())

    def set_session(self, logged_in: bool, name: str = ""):
        self._logged_in = bool(logged_in)
        shown = str(name or "").strip()
        self.banner.session_label.setText(shown)
        self.banner.session_label.setVisible(bool(self._logged_in and shown))
        self.banner.login_btn.setText("退出" if self._logged_in else "登录")

    def _on_session_click(self):
        if self._logged_in:
            self.logout_requested.emit()
        else:
            self.login_requested.emit()

    def _layout_cards(self, count: int):
        while len(self._cards) < count:
            self._cards.append(_ProbeCard())
        while self.probe_grid.count():
            self.probe_grid.takeAt(0)
        cols = 2 if count > 2 else 1
        rows = max(1, (count + cols - 1) // cols)
        compact = count > 6
        self.probe_grid.setSpacing(6 if compact else 8)
        for r in range(8):
            self.probe_grid.setRowStretch(r, 1 if r < rows else 0)
        for i, card in enumerate(self._cards):
            card.set_compact(compact)
            if i < count:
                self.probe_grid.addWidget(card, i // cols, i % cols)
                card.show()
            else:
                card.hide()

    def _show_recheck(self):
        self.recheck_text.setText("请停车。复查各探头计数。确认不是硬报后再放行。")
        self.recheck_text.show()

    def set_reset_allowed(self, allowed: bool):
        self._reset_allowed = bool(allowed)
        self._paint_reset()

    def _paint_reset(self):
        show = bool(self._reset_wanted)
        self.reset_btn.setVisible(show)
        if not show:
            self.reset_hint.hide()
            return
        if self._reset_allowed:
            self.reset_btn.setEnabled(True)
            self.reset_btn.setStyleSheet(
                "QPushButton { background: #c62828; color: white; font-size: 20px; font-weight: 700;"
                " border: none; border-radius: 6px; font-family: %s; margin-top: 10px; }"
                "QPushButton:pressed { background: #8e1c1c; }" % _FONT
            )
            self.reset_hint.hide()
        else:
            self.reset_btn.setEnabled(False)
            self.reset_btn.setStyleSheet(
                "QPushButton { background: #3a3f3c; color: #8b978f; font-size: 20px; font-weight: 700;"
                " border: none; border-radius: 6px; font-family: %s; margin-top: 10px; }" % _FONT
            )
            self.reset_hint.show()

    def apply_model(self, model: dict):
        tone = model.get("banner_tone") or "ok"
        _bg, fg = _BAND.get(tone, _BAND["ok"])
        self.banner.set_tone(tone)
        self.banner_label.setText(model.get("banner") or "")
        self.banner_label.setStyleSheet(
            "color: %s; font-size: 28px; font-weight: 800; background: transparent; border: none; font-family: %s;"
            % (fg, _FONT)
        )
        if tone == "alarm":
            self.status_icon.setPixmap(_trefoil(24, "#ffe082"))
            self.status_icon.show()
        elif tone == "fault":
            self.status_icon.setPixmap(_wrench(24, "#ffe2cc"))
            self.status_icon.show()
        else:
            self.status_icon.hide()
        while self.chip_host.count():
            item = self.chip_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for text in list(model.get("chips") or []):
            chip = QLabel(text)
            chip.setAlignment(Qt.AlignCenter)
            chip.setStyleSheet(
                "color: %s; background: rgba(0,0,0,0.18); border: 1px solid rgba(255,255,255,0.55);"
                " border-radius: 10px; padding: 1px 8px; font-size: 12px; font-family: %s;"
                % (fg, _FONT)
            )
            self.chip_host.addWidget(chip)

        self.lane_label.setText("通道 %s" % (model.get("lane") or "03"))
        capture = model.get("capture")
        plate = model.get("plate") or ""
        if capture == "wait":
            self.capture.setText("等待过车")
        elif plate:
            self.capture.setText(plate)
        else:
            self.capture.setText("可手补车牌")

        self._building_plate = True
        if not self.plate_edit.hasFocus():
            self.plate_edit.setText(plate)
        self._building_plate = False

        probes = list(model.get("probes") or [])
        self._layout_cards(len(probes))
        for i, card in enumerate(self._cards):
            if i < len(probes):
                card.apply_card(probes[i])

        shown = {name for name, _val in list(model.get("fields") or [])}
        for name, val in list(model.get("fields") or []):
            lab = self._field_values.get(name)
            if lab is None or name == "车牌":
                continue
            text = str(val)
            if name == "车速":
                try:
                    float(text)
                    text = text + " km/h"
                except ValueError:
                    pass
            lab.setText(text)
            color = _TEXT
            if name == "辐射硬报" and val == "是":
                color = _RED
            elif name == "辐射硬报" and val == "无":
                color = _GREEN
            elif name == "通道状态" and val == "空闲":
                color = _GREEN
            elif name == "通道状态" and val == "车辆经过":
                color = _AMBER
            elif name == "超速" and val == "是":
                color = _AMBER
            lab.setStyleSheet(
                "color: %s; font-size: 14px; font-weight: 650; background: transparent; border: none; font-family: %s;"
                % (color, _FONT)
            )
        for name, wrap in self._field_rows.items():
            wrap.setVisible(name in shown or name == "车牌")
        self._reset_wanted = bool(model.get("show_reset"))
        self._paint_reset()
        if tone == "amber":
            self.recheck_btn.show()
            self.recheck_text.setVisible(self.recheck_text.text() != "")
        else:
            self.recheck_btn.hide()
            self.recheck_text.hide()
            self.recheck_text.setText("")
        notes = []
        if tone == "fault":
            statuses = [str(card.get("status") or "") for card in probes]
            if "通信异常" in statuses:
                notes.append("查链路：网线、探头供电，确认主控仍在线。")
            if "高压偏离" in statuses:
                notes.append("等高压恢复。这不是辐射报警，消警清不了高压。")
            if not notes:
                notes.append("按探头卡上的故障处理。这不是辐射报警。")
        self.trouble.setText("排查\n" + "\n".join(notes) if notes else "")
        self.trouble.setVisible(bool(notes))

        rows = list(model.get("history") or [])
        self.history.clearSpans()
        if not rows:
            self.history.setRowCount(1)
            item = QTableWidgetItem("暂无通行记录")
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QBrush(QColor(_MUTED)))
            self.history.setItem(0, 0, item)
            self.history.setSpan(0, 0, 1, len(_HISTORY_COLS))
            return
        self.history.setRowCount(len(rows))
        keys = ("time", "lane", "plate", "total", "peak", "radiation", "speed", "overspeed", "result")
        ink = QBrush(QColor(_TEXT))
        hot = QBrush(QColor("#ff6b6b"))
        warn = QBrush(QColor(_AMBER))
        good = QBrush(QColor(_GREEN))
        dim = QBrush(QColor(_MUTED))
        for r, row in enumerate(rows):
            invalid = row.get("result") == "无效"
            hard_row = row.get("radiation") == "硬报" or row.get("result") == "禁行"
            fast_row = row.get("overspeed") == "是" and not hard_row
            if invalid:
                bg = QBrush(QColor("#161a18"))
            elif hard_row:
                bg = QBrush(QColor("#4a1518"))
            elif fast_row:
                bg = QBrush(QColor("#3a2a10"))
            else:
                bg = QBrush(QColor("#14301c"))
            for c, key in enumerate(keys):
                item = QTableWidgetItem(str(row.get(key) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(bg)
                if invalid:
                    item.setForeground(dim)
                else:
                    item.setForeground(ink)
                    if key in ("radiation", "result") and row.get(key) in ("正常", "放行"):
                        item.setForeground(good)
                    if key == "radiation" and row.get(key) == "硬报":
                        item.setForeground(hot)
                    if key == "result" and row.get(key) == "禁行":
                        item.setForeground(hot)
                    if key == "overspeed" and row.get(key) == "是":
                        item.setForeground(warn)
                self.history.setItem(r, c, item)
