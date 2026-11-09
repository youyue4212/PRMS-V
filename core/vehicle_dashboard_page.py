# -*- coding: utf-8 -*-
"""车辆通道主界面。版式按效果图：顶栏色带、左探头、中抓拍、右本次通行、底历史。"""

from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
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

from core.translation import _t
from core.ui_tokens import cps_digit_scale
from core.vehicle import theme
from core.vehicle.dashboard_model import FIELD_ORDER
from core.vehicle.rtsp_preview import RtspPreviewWidget
from core.vehicle.theme import COLOR as _C, SIZE as _S

_BG = _C["bg"]
_CARD = _C["card"]
_CARD_DIM = _C["card-dim"]
_LINE = _C["line"]
_TEXT = _C["text"]
_MUTED = _C["muted"]
_GREEN = _C["ok"]
_RED = _C["alarm"]
_AMBER = _C["amber"]
_FONT = theme.FONT
_CPS_BASE_PX = _S["cps-base"]

_BAND = theme.BAND

_FAULT = _C["fault"]
_FAULT_WORD_PX = _S["fault-word"]
_FAULT_HINT = {"通信异常": "查链路", "高压偏离": "等高压恢复"}

_SCROLL_QSS = (
    "QScrollArea { background: transparent; border: none; }"
    "QScrollArea > QWidget > QWidget { background: transparent; }"
    "QScrollBar:vertical { background: %s; width: 8px; border: none; }"
    "QScrollBar::handle:vertical { background: %s; border-radius: 4px; min-height: 30px; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
    % (_BG, _C["scroll-handle"])
)

_HISTORY_COL_KEYS = (
    "vhist_col_time", "vhist_col_lane", "vhist_col_plate", "vhist_col_total",
    "vhist_col_peak", "vhist_col_rad", "vhist_col_speed", "vhist_col_overspeed",
    "vhist_col_result",
)


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
        self.setFixedHeight(_S["banner-h"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignVCenter)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(_trefoil(28, _C["white"], ring=True))
        self.brand = QLabel(_t("vbrand_title"))
        self.brand.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; background: transparent; border: none; font-family: %s;"
            % (_C["white"], _S["brand"], _FONT)
        )
        brand.setContentsMargins(0, 0, 0, 0)
        brand.addWidget(self.brand_icon)
        brand.addWidget(self.brand)
        brand.addStretch(1)
        brand_wrap = QWidget()
        brand_wrap.setStyleSheet("background: transparent;")
        brand_wrap.setLayout(brand)
        lay.addWidget(brand_wrap, 0)
        self._brand_wrap = brand_wrap

        center = QHBoxLayout()
        center.setContentsMargins(36, 0, 0, 0)
        center.setSpacing(10)
        self.status_icon = QLabel()
        self.status_icon.hide()
        self.banner_label = QLabel("通道空闲")
        self.chip_host = QHBoxLayout()
        self.chip_host.setSpacing(6)
        center.addWidget(self.status_icon)
        center.addWidget(self.banner_label)
        center.addLayout(self.chip_host)
        center.addStretch(1)
        center_wrap = QWidget()
        center_wrap.setStyleSheet("background: transparent;")
        center_wrap.setLayout(center)
        lay.addWidget(center_wrap, 1)

        # 左侧已有产品全称；右侧不再重复「监测软件」，只保留账户操作
        self.mode_label = QLabel(_t("vbrand_mode"))
        self.mode_label.hide()
        self.session_label = QLabel("")
        self.session_label.setAlignment(Qt.AlignCenter)
        self.session_label.setFixedHeight(28)
        self.session_label.hide()
        self.login_btn = QPushButton(_t("btn_login"))
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setFixedHeight(28)
        self.login_btn.setMinimumWidth(72)
        self._apply_banner_session_styles(logged_in=False)
        right = QHBoxLayout()
        right.setSpacing(12)
        right.setAlignment(Qt.AlignVCenter)
        right.addStretch(1)
        right.addWidget(self.session_label, 0, Qt.AlignVCenter)
        right.addWidget(self.login_btn, 0, Qt.AlignVCenter)
        right_wrap = QWidget()
        right_wrap.setStyleSheet("background: transparent;")
        right_wrap.setLayout(right)
        lay.addWidget(right_wrap, 0)

    def set_tone(self, tone: str):
        self._tone = tone or "ok"
        self.update()

    def _apply_banner_session_styles(self, logged_in: bool):
        px = _S["card-location"]
        self.session_label.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; padding: 0 10px;"
            " background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.22);"
            " border-radius: 6px; font-family: %s;"
            % (_C["white"], px, _FONT)
        )
        if logged_in:
            self.login_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #e0e0e0;"
                " border: 1px solid rgba(255,255,255,0.35); border-radius: 6px;"
                " padding: 0 14px; font-size: %dpx; font-weight: 600; font-family: %s; }"
                "QPushButton:pressed { background: rgba(255,255,255,0.08); }"
                % (px, _FONT)
            )
        else:
            self.login_btn.setStyleSheet(
                "QPushButton { background: %s; color: white; border: none; border-radius: 6px;"
                " padding: 0 14px; font-size: %dpx; font-weight: 700; font-family: %s; }"
                "QPushButton:pressed { background: %s; }"
                % (_C["login-bg"], px, _FONT, _C["login-pressed"])
            )

    def resizeEvent(self, event):
        self._brand_wrap.setFixedWidth(max(self.brand.sizeHint().width() + 48, int(self.width() * 0.33)))
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(_BG))
        w = self.width()
        h = self.height()
        start = QColor(_BAND.get(self._tone, _BAND["ok"])[0])
        slant = 22
        left = self._brand_wrap.geometry().right() + 4
        path = QPainterPath()
        path.moveTo(left + slant, 0)
        path.lineTo(w, 0)
        path.lineTo(w, h)
        path.lineTo(left, h)
        path.closeSubpath()
        grad = QLinearGradient(left, 0, w, 0)
        grad.setColorAt(0.0, start)
        grad.setColorAt(0.45, start.darker(260))
        grad.setColorAt(0.85, QColor(_BG))
        p.fillPath(path, QBrush(grad))
        p.end()


class _ProbeCard(QFrame):
    clicked = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("probeCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._nav_slot = 0
        self._nav_client_id = ""
        self._nav_enabled = False
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
        self._word = False
        self._empty = False
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
            self.setMinimumHeight(58)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(10, 6, 10, 6)
            lay.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(self.dot, 0, Qt.AlignVCenter)
            title_col = QVBoxLayout()
            title_col.setSpacing(0)
            title_col.setContentsMargins(0, 0, 0, 0)
            self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.location.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title_col.addWidget(self.title)
            title_col.addWidget(self.location)
            head.addLayout(title_col, 1)
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
            self.setMinimumHeight(102)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(14, 10, 14, 12)
            lay.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(self.dot, 0, Qt.AlignVCenter)
            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            title_col.setContentsMargins(0, 0, 0, 0)
            self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.location.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title_col.addWidget(self.title)
            title_col.addWidget(self.location)
            head.addLayout(title_col, 1)
            head.addStretch(1)
            lay.addLayout(head)
            lay.addStretch(1)
            num = QHBoxLayout()
            num.setSpacing(8)
            num.addStretch(1)
            num.addWidget(self.cps, 0, Qt.AlignBottom)
            num.addWidget(self.unit, 0, Qt.AlignBottom)
            num.addStretch(1)
            lay.addLayout(num)
            lay.addSpacing(2)
            lay.addWidget(self.status)
            lay.addStretch(1)
        self._fit_cps()

    def _fit_cps(self):
        text = self.cps.text()
        if self._word:
            px = _S["fault-word-compact"] if self._compact else _FAULT_WORD_PX
            weight = "bold"
            if self._empty:
                px = _S["card-status-compact"] if self._compact else _S["card-empty"]
                weight = "normal"
            self.cps.setStyleSheet(
                "color: %s; font-size: %dpx; font-weight: %s; background: transparent; border: none;"
                " font-family: %s;" % (self._cps_color, px, weight, _FONT)
            )
            return
        unit_w = self.unit.sizeHint().width() if not self.unit.isHidden() else 0
        if self._compact:
            base = max(16, min(36, int((self.height() - 30) * 0.95)))
            room = self.width() - 20 - 6 - unit_w
        else:
            base = max(_CPS_BASE_PX, min(_S["cps-max"], int(self.height() * 0.26)))
            base = min(base, max(18, int((self.height() - 84) * 0.9)))
            room = self.width() - 28 - 8 - unit_w
        px = max(12, int(round(base * cps_digit_scale(text))))
        if text and room > 40:
            font = QFont(theme.FONT_DIGIT_FAMILY)
            font.setPixelSize(px)
            need = QFontMetrics(font).horizontalAdvance(text)
            if need > room:
                px = max(12, int(px * room / need))
        self.cps.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent; border: none;"
            " font-family: %s;" % (self._cps_color, px, theme.FONT_DIGIT)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_cps()

    def apply_card(self, card: dict):
        tone = card.get("tone") or "offline"
        status = card.get("status") or ""
        empty = status == "未接入"
        bg, border, color = theme.CARD.get("offline" if empty else tone, theme.CARD["offline"])
        self.title.setText("" if empty else (card.get("title") or ""))
        self.location.setText("" if empty else (card.get("location") or ""))
        self.dot.setVisible(not empty)
        self.dot.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent; border: none;" % (color, _S["card-dot"])
        )
        self.title.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; background: transparent; border: none; font-family: %s;"
            % (_TEXT, _S["card-title"], _FONT)
        )
        self.location.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent; border: none; font-family: %s;"
            % (_C["text-soft"], _S["card-location"], _FONT)
        )
        self.unit.hide()
        self.status.show()
        if empty:
            self.cps.setText("未接入")
            self.cps.show()
            self.status.setText("")
            self.status.hide()
        elif tone == "fault":
            self.cps.setText(status)
            self.cps.show()
            self.status.setText(_FAULT_HINT.get(status, "设备故障"))
        elif card.get("show_cps"):
            self.cps.setText(str(card.get("cps_text") or ""))
            self.cps.show()
            self.unit.show()
            self.status.setText(status)
        else:
            self.cps.hide()
            self.cps.setText("")
            self.status.setText(status)
        if self._compact:
            self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        else:
            self.status.setAlignment(Qt.AlignCenter)
        self._empty = empty
        self._word = empty or tone == "fault"
        self._cps_color = color
        small = _S["card-status-compact"] if self._compact else _S["card-status"]
        self.unit.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent; border: none; font-family: %s;"
            " padding-bottom: 6px;" % (_C["unit"], small, theme.FONT_DIGIT)
        )
        self.status.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent; border: none; font-family: %s;"
            % (color, small, _FONT)
        )
        self._fit_cps()
        border_w = 2 if tone == "alarm" else 1
        self.setStyleSheet(
            "QFrame#probeCard { background: %s; border: %dpx solid %s; border-radius: %dpx; }"
            % (bg, border_w, border, _S["radius-card"])
        )
        try:
            slot = int(card.get("slot", 0))
        except (TypeError, ValueError):
            slot = 0
        cid = str(card.get("client_id") or "").strip()
        self._nav_slot = slot
        self._nav_client_id = cid
        self._nav_enabled = (not empty) and bool(cid)
        self.setCursor(Qt.PointingHandCursor if self._nav_enabled else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if (
            self._nav_enabled
            and event.button() == Qt.LeftButton
            and self.rect().contains(event.pos())
        ):
            self.clicked.emit(self._nav_slot, self._nav_client_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class VehicleDashboardPage(QWidget):
    """图1至图4。消警只在辐射硬报时出现。"""

    reset_requested = pyqtSignal()
    plate_edited = pyqtSignal(str)
    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    probe_requested = pyqtSignal(int, str)

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
        self._chip_sig = None
        self._probe_sig = None
        self._history_sig = None
        self._field_order_sig = None
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
        cap_col.setContentsMargins(8, 6, 8, 8)
        cap_col.setSpacing(6)
        cap_head = QHBoxLayout()
        cap_title = QLabel(_t("vcap_title"))
        self._cap_title = cap_title
        cap_title.setStyleSheet(
            "color: %s; font-size: %dpx; font-family: %s;" % (_TEXT, _S["section-title"], _FONT)
        )
        self.lane_label = QLabel(_t("vlane_fmt", lane="03"))
        self.lane_label.setAlignment(Qt.AlignCenter)
        self.lane_label.setStyleSheet(
            "color: %s; font-size: %dpx; font-family: %s;" % (_TEXT, _S["section-title"], _FONT)
        )
        cap_head.addWidget(cap_title)
        cap_head.addStretch(1)
        cap_head.addWidget(self.lane_label)
        cap_col.addLayout(cap_head)
        self.capture = RtspPreviewWidget()
        self.capture.set_center_text(_t("vcapture_wait"))
        cap_col.addWidget(self.capture, 1)
        cap_frame = QFrame()
        cap_frame.setObjectName("dashCapPanel")
        cap_frame.setStyleSheet(
            "QFrame#dashCapPanel { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (_CARD, _LINE, _S["radius-card"])
        )
        cap_frame.setLayout(cap_col)
        body.addWidget(cap_frame, 6)

        side = QVBoxLayout()
        side.setContentsMargins(14, 12, 14, 12)
        side.setSpacing(0)
        side_head = QHBoxLayout()
        side_dot = QLabel("●")
        side_dot.setStyleSheet("color: %s; font-size: 11px;" % _GREEN)
        side_title = QLabel(_t("vside_title"))
        self._side_title = side_title
        side_title.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; font-family: %s;"
            % (_TEXT, _S["section-title"] + 1, _FONT)
        )
        side_head.addWidget(side_dot)
        side_head.addWidget(side_title)
        side_head.addStretch(1)
        side.addLayout(side_head)
        side.addSpacing(6)
        self.plate_edit = QLineEdit()
        self.plate_edit.setPlaceholderText(_t("vval_plate_manual"))
        self.plate_edit.setAlignment(Qt.AlignRight)
        self.plate_edit.setFixedHeight(28)
        self.plate_edit.setStyleSheet(
            "QLineEdit { background: transparent; color: %s; border: none; font-size: %dpx; font-family: %s; }"
            % (_TEXT, _S["field-value"], _FONT)
        )
        self.plate_edit.editingFinished.connect(self._emit_plate)
        self.plate_edit.returnPressed.connect(self._emit_plate)
        fields = QVBoxLayout()
        fields.setContentsMargins(0, 0, 6, 0)
        fields.setSpacing(0)
        self._fields_lay = fields
        for fid in FIELD_ORDER:
            row = QHBoxLayout()
            row.setContentsMargins(10, 7, 10, 7)
            key = QLabel(_t("vfield_" + fid))
            key.setStyleSheet(
                "color: %s; font-size: %dpx; font-family: %s;" % (_C["text-soft"], _S["field-key"], _FONT)
            )
            val = QLabel("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setWordWrap(False)
            val.setStyleSheet(
                "color: %s; font-size: %dpx; font-family: %s;" % (_TEXT, _S["field-value"], _FONT)
            )
            row.addWidget(key)
            row.addStretch(1)
            if fid == "plate":
                row.addWidget(self.plate_edit, 1)
            else:
                row.addWidget(val)
            wrap = QWidget()
            wrap.setLayout(row)
            wrap.setStyleSheet("border-bottom: 1px solid %s; background: transparent;" % _LINE)
            self._field_values[fid] = val
            self._field_keys[fid] = key
            self._field_rows[fid] = wrap
            fields.addWidget(wrap)
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
        side.addWidget(self.side_scroll, 0)
        side.addStretch(1)
        self.reset_btn = QPushButton(_t("vbtn_reset"))
        self.reset_btn.setMinimumHeight(48)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.reset_btn.hide()
        self.reset_hint = QLabel(_t("vreset_need_priv"))
        self.reset_hint.setAlignment(Qt.AlignCenter)
        self.reset_hint.setStyleSheet(
            "color: %s; font-size: %dpx; font-family: %s;" % (_MUTED, _S["card-location"], _FONT)
        )
        self.reset_hint.hide()
        self.recheck_btn = QPushButton(_t("vbtn_recheck"))
        self.recheck_btn.setMinimumHeight(40)
        self.recheck_btn.setCursor(Qt.PointingHandCursor)
        self.recheck_btn.setStyleSheet(
            "QPushButton { background: transparent; color: %s; font-size: %dpx; font-weight: 700;"
            " border: 1px solid %s; border-radius: 6px; font-family: %s; margin-top: 8px; }"
            "QPushButton:pressed { background: %s; }"
            % (_AMBER, _S["field-value"] + 2, _AMBER, _FONT, _C["recheck-pressed"])
        )
        self.recheck_btn.clicked.connect(self._show_recheck)
        self.recheck_btn.hide()
        self.recheck_text = QLabel("")
        self.recheck_text.setWordWrap(True)
        self.recheck_text.setStyleSheet(
            "color: %s; font-size: %dpx; padding-top: 6px; font-family: %s;"
            % (_AMBER, _S["card-location"], _FONT)
        )
        self.recheck_text.hide()
        self.trouble = QLabel("")
        self.trouble.setWordWrap(True)
        self.trouble.setStyleSheet(
            "color: %s; font-size: %dpx; padding-top: 8px; font-family: %s;"
            % (_C["trouble-text"], _S["card-location"], _FONT)
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
        side_frame.setMinimumWidth(300)
        body.addWidget(side_frame, 4)
        root.addLayout(body, 1)

        hist_title = QLabel(_t("vhist_title"))
        self._hist_title = hist_title
        hist_title.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 600; font-family: %s;"
            % (_TEXT, _S["section-title"], _FONT)
        )
        root.addWidget(hist_title)
        self.history = QTableWidget(0, len(_HISTORY_COL_KEYS))
        self._apply_history_headers()
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history.setSelectionMode(QTableWidget.NoSelection)
        self.history.setShowGrid(True)
        self.history.setFocusPolicy(Qt.NoFocus)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hist_h = _S.get("history-row-h", 36)
        header.setFixedHeight(hist_h + 2)
        self.history.verticalHeader().setDefaultSectionSize(hist_h)
        self.history.setStyleSheet(
            "QTableWidget { background: %s; color: %s; border: 1px solid %s; border-radius: %dpx;"
            " gridline-color: %s; font-size: %dpx; font-family: %s; }"
            "QHeaderView::section { background: %s; color: %s; border: none; border-right: 1px solid %s;"
            " border-bottom: 1px solid %s; padding: 4px; font-size: %dpx; font-weight: 600; font-family: %s; }"
            % (_CARD, _TEXT, _LINE, _S["radius-card"], _C["grid"], _S["history"], _FONT,
               _CARD, _TEXT, _C["grid"], _C["grid"], _S["history"], _FONT)
            + _SCROLL_QSS
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

    def _apply_history_headers(self):
        self.history.setHorizontalHeaderLabels([_t(k) for k in _HISTORY_COL_KEYS])

    def retranslate_ui(self):
        self.banner.brand.setText(_t("vbrand_title"))
        if hasattr(self, "_cap_title"):
            self._cap_title.setText(_t("vcap_title"))
        if hasattr(self, "_side_title"):
            self._side_title.setText(_t("vside_title"))
        if hasattr(self, "_hist_title"):
            self._hist_title.setText(_t("vhist_title"))
        self.plate_edit.setPlaceholderText(_t("vval_plate_manual"))
        for fid, key in self._field_keys.items():
            key.setText(_t("vfield_" + fid))
        self.reset_btn.setText(_t("vbtn_reset"))
        self.reset_hint.setText(_t("vreset_need_priv"))
        self.recheck_btn.setText(_t("vbtn_recheck"))
        self._apply_history_headers()
        logged = bool(getattr(self, "_logged_in", False))
        self.banner.login_btn.setText(_t("btn_logout") if logged else _t("btn_login"))
        self.banner._apply_banner_session_styles(logged)
        self._history_sig = None

    def set_session(self, logged_in: bool, name: str = ""):
        self._logged_in = bool(logged_in)
        shown = str(name or "").strip()
        self.banner.session_label.setText(shown)
        self.banner.session_label.setVisible(bool(self._logged_in and shown))
        self.banner.login_btn.setText(_t("btn_logout") if self._logged_in else _t("btn_login"))
        self.banner._apply_banner_session_styles(self._logged_in)

    def _on_session_click(self):
        if self._logged_in:
            self.logout_requested.emit()
        else:
            self.login_requested.emit()

    def _on_probe_card(self, slot: int, client_id: str):
        """Same contract as行人 Web HMI: index + clientId → overview."""
        self.probe_requested.emit(int(slot), client_id or "")

    def apply_rtsp_config(self, url: str):
        self.capture.set_stream_url(url)

    def _layout_cards(self, count: int):
        while len(self._cards) < count:
            card = _ProbeCard()
            card.clicked.connect(self._on_probe_card)
            self._cards.append(card)
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
        self.recheck_text.setText(_t("vrecheck_body"))
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
                "QPushButton { background: %s; color: white; font-size: %dpx; font-weight: 700;"
                " border: none; border-radius: 6px; font-family: %s; margin-top: 10px; }"
                "QPushButton:pressed { background: %s; }"
                % (_C["reset-bg"], _S["reset"], _FONT, _C["reset-pressed"])
            )
            self.reset_hint.hide()
        else:
            self.reset_btn.setEnabled(False)
            self.reset_btn.setStyleSheet(
                "QPushButton { background: %s; color: %s; font-size: %dpx; font-weight: 700;"
                " border: none; border-radius: 6px; font-family: %s; margin-top: 10px; }"
                % (_C["reset-off-bg"], _MUTED, _S["reset"], _FONT)
            )
            self.reset_hint.show()

    def apply_model(self, model: dict):
        tone = model.get("banner_tone") or "ok"
        _bg, fg = _BAND.get(tone, _BAND["ok"])
        self.banner.set_tone(tone)
        self.banner_label.setText(model.get("banner") or "")
        self.banner_label.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: bold; background: transparent; border: none; font-family: %s;"
            % (fg, _S["banner-title"], _FONT)
        )
        if tone == "alarm":
            self.status_icon.setPixmap(_trefoil(24, _C["icon-alarm"]))
            self.status_icon.show()
        elif tone == "fault":
            self.status_icon.setPixmap(_wrench(24, _C["icon-fault"]))
            self.status_icon.show()
        else:
            self.status_icon.hide()
        chips = tuple(str(x) for x in list(model.get("chips") or []))
        if chips != self._chip_sig:
            self._chip_sig = chips
            while self.chip_host.count():
                item = self.chip_host.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            for text in chips:
                chip = QLabel(text)
                chip.setAlignment(Qt.AlignCenter)
                chip.setFixedHeight(28)
                chip.setStyleSheet(
                    "color: %s; background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.32);"
                    " border-radius: 6px; padding: 3px 10px; font-size: %dpx; font-family: %s;"
                    % (_C["white"], _S["card-location"], _FONT)
                )
                self.chip_host.addWidget(chip, 0, Qt.AlignVCenter)

        self.lane_label.setText(_t("vlane_fmt", lane=(model.get("lane") or "03")))
        capture = model.get("capture")
        plate = model.get("plate") or ""
        alarm_img = str(model.get("alarm_image") or "").strip()
        self.capture.set_alarm_image(alarm_img if tone == "alarm" and alarm_img else "")
        if self.capture.stream_enabled():
            if capture == "wait":
                self.capture.set_center_text(_t("vcapture_wait"))
            elif plate:
                self.capture.set_center_text(plate)
            else:
                self.capture.set_center_text(_t("vcapture_manual"))
            self.capture.set_badge_text(plate if plate else "")
        else:
            if capture == "wait":
                self.capture.set_center_text(_t("vcapture_wait"))
            elif plate:
                self.capture.set_center_text(plate)
            else:
                self.capture.set_center_text(_t("vcapture_manual"))
            self.capture.set_badge_text("")

        self._building_plate = True
        if not self.plate_edit.hasFocus():
            self.plate_edit.setText(plate)
        self._building_plate = False

        probes = list(model.get("probes") or [])
        probe_sig = tuple(
            (
                p.get("title"),
                p.get("status"),
                p.get("cps_text"),
                p.get("tone"),
                p.get("show_cps"),
                p.get("location"),
            )
            for p in probes
        )
        if probe_sig != self._probe_sig:
            self._probe_sig = probe_sig
            self._layout_cards(len(probes))
            for i, card in enumerate(self._cards):
                if i < len(probes):
                    card.apply_card(probes[i])
        elif len(self._cards) != len(probes):
            self._layout_cards(len(probes))
            for i, card in enumerate(self._cards):
                if i < len(probes):
                    card.apply_card(probes[i])

        field_list = list(model.get("fields") or [])
        shown = {f.get("id") for f in field_list if f.get("id")}
        for f in field_list:
            fid = f.get("id")
            lab = self._field_values.get(fid)
            if lab is None or fid == "plate":
                continue
            text = str(f.get("text") or "")
            if fid == "speed":
                try:
                    float(text)
                    text = text + " km/h"
                except ValueError:
                    pass
            lab.setText(text)
            color = _TEXT
            size = _S["field-value"]
            weight = "normal"
            hint = str(f.get("hint") or "")
            if fid == "rad_hard" and hint == "yes":
                color, size, weight = _RED, _S["field-alert"], "bold"
            elif fid == "channel_status" and hint == "idle":
                color = _GREEN
            elif fid == "channel_status" and hint == "passing":
                color = _AMBER
            elif fid == "overspeed" and hint == "yes":
                color = _AMBER
            lab.setStyleSheet(
                "color: %s; font-size: %dpx; font-weight: %s; background: transparent; border: none; font-family: %s;"
                % (color, size, weight, _FONT)
            )
        order = [f.get("id") for f in field_list if f.get("id")]
        order += [fid for fid in self._field_rows if fid not in order]
        order_sig = tuple(order)
        if order_sig != self._field_order_sig:
            self._field_order_sig = order_sig
            for name in order:
                self._fields_lay.removeWidget(self._field_rows[name])
            for i, name in enumerate(order):
                self._fields_lay.insertWidget(i, self._field_rows[name])
        for fid, wrap in self._field_rows.items():
            wrap.setVisible(fid in shown)
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
            keys = [str(card.get("status_key") or "") for card in probes]
            if "comm" in keys:
                notes.append(_t("vtrouble_comm"))
            if "hv" in keys:
                notes.append(_t("vtrouble_hv"))
            if not notes:
                notes.append(_t("vtrouble_default"))
        self.trouble.setText(_t("vtrouble_head") + "\n" + "\n".join(notes) if notes else "")
        self.trouble.setVisible(bool(notes))

        rows = list(model.get("history") or [])
        history_sig = tuple(tuple(str(row.get(k) or "") for k in (
            "time", "lane", "plate", "total", "peak", "radiation", "speed", "overspeed", "result"
        )) for row in rows)
        if history_sig == self._history_sig:
            return
        self._history_sig = history_sig
        self.history.clearSpans()
        if not rows:
            self.history.setRowCount(1)
            item = QTableWidgetItem(_t("vhist_empty"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QBrush(QColor(_MUTED)))
            self.history.setItem(0, 0, item)
            self.history.setSpan(0, 0, 1, len(_HISTORY_COL_KEYS))
            return
        self.history.setRowCount(len(rows))
        keys = ("time", "lane", "plate", "total", "peak", "radiation", "speed", "overspeed", "result")
        ink = QBrush(QColor(_TEXT))
        row_bg = theme.HISTORY_ROW
        hot = QBrush(QColor(row_bg["hard-text"]))
        warn = QBrush(QColor(_AMBER))
        good = QBrush(QColor(_GREEN))
        dim = QBrush(QColor(_MUTED))
        for r, row in enumerate(rows):
            invalid = row.get("result_kind") == "invalid"
            hard_row = row.get("rad_kind") == "hard" or row.get("result_kind") == "deny"
            fast_row = bool(row.get("overspeed_yes")) and not hard_row
            if invalid:
                bg = QBrush(QColor(row_bg["invalid"]))
            elif hard_row:
                bg = QBrush(QColor(row_bg["hard"]))
            elif fast_row:
                bg = QBrush(QColor(row_bg["fast"]))
            else:
                bg = QBrush(QColor(row_bg["pass"]))
            for c, key in enumerate(keys):
                item = QTableWidgetItem(str(row.get(key) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(bg)
                if invalid:
                    item.setForeground(dim)
                else:
                    item.setForeground(ink)
                    if key == "radiation" and row.get("rad_kind") == "ok":
                        item.setForeground(good)
                    if key == "result" and row.get("result_kind") == "pass":
                        item.setForeground(good)
                    if key == "radiation" and row.get("rad_kind") == "hard":
                        item.setForeground(hot)
                    if key == "result" and row.get("result_kind") == "deny":
                        item.setForeground(hot)
                    if key == "time" and not hard_row:
                        item.setForeground(QBrush(QColor(row_bg["fast-time" if fast_row else "pass-time"])))
                    if key == "overspeed" and row.get("overspeed_yes"):
                        item.setForeground(warn)
                self.history.setItem(r, c, item)
