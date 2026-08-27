# -*- coding: utf-8 -*-
"""Control-room (PC) overview wall: multi-probe grid + alarm duty sidebar."""

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QListWidget, QListWidgetItem, QApplication,
)

from core.ui_tokens import (
    BG, PANEL, BORDER, OK, WARN, ALARM, INFO, TEXT, TEXT_DIM, MUTED,
    RADIUS_CARD, RADIUS_BTN, cr_px, cr_cps_px, cps_digit_scale,
    CR_CHROME_H, CR_CHROME_FONT_PX,
)


def _card_frame():
    f = QFrame()
    f.setObjectName("crCard")
    f.setStyleSheet(f"""
        QFrame#crCard {{
            background-color: {PANEL};
            border: 1px solid {BORDER};
            border-radius: {RADIUS_CARD}px;
        }}
        QFrame#crCard QLabel {{
            background: transparent;
            border: none;
        }}
    """)
    return f


class ProbeTile(QFrame):
    """One probe cell on the control-room wall (click + drag-reorder)."""
    clicked = pyqtSignal(object)  # client_id or None
    drag_started = pyqtSignal(int)
    drag_hover = pyqtSignal(int)
    drag_finished = pyqtSignal(int, object)  # from_index, global pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client_id = None
        self._index = -1
        self._press_pos = None
        self._dragging = False
        self._nav_enabled = False
        self.setObjectName("probeTile")
        self.setCursor(Qt.ArrowCursor)
        self.setMinimumSize(220, 168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(False)
        self.setMouseTracking(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self.name_label = QLabel("--")
        self.name_label.setStyleSheet(
            f"color: {TEXT}; font-size: {cr_px(15)}px; font-weight: bold;"
        )
        self.loc_label = QLabel("")
        self.loc_label.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(12)}px;")
        self.loc_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.name_label, 1)
        head.addWidget(self.loc_label)
        lay.addLayout(head)

        self._cps_base_px = cr_cps_px(36)
        self._cps_color = OK
        self.cps_label = QLabel("--")
        self.cps_label.setAlignment(Qt.AlignCenter)
        self.cps_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self._apply_cps_typography("--")
        self.unit_label = QLabel("CPS")
        self.unit_label.setAlignment(Qt.AlignCenter)
        self.unit_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.unit_label.setStyleSheet(
            f"color: {MUTED}; font-size: {cr_px(16)}px; font-weight: 600;"
        )
        body_wrap = QWidget()
        body_wrap.setStyleSheet("background: transparent;")
        body_lay = QVBoxLayout(body_wrap)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.addStretch(1)
        cps_row = QHBoxLayout()
        cps_row.setSpacing(8)
        cps_row.addStretch(1)
        cps_row.addWidget(self.cps_label, 0, Qt.AlignVCenter)
        cps_row.addWidget(self.unit_label, 0, Qt.AlignVCenter)
        cps_row.addStretch(1)
        body_lay.addLayout(cps_row, 0)
        body_lay.addStretch(1)
        lay.addWidget(body_wrap, 1)

        foot_wrap = QFrame()
        foot_wrap.setObjectName("probeFoot")
        foot_wrap.setStyleSheet(f"""
            QFrame#probeFoot {{
                border-top: 1px solid {BORDER};
                padding-top: 6px;
                margin-top: 2px;
            }}
            QFrame#probeFoot QLabel {{
                background: transparent; border: none;
            }}
        """)
        foot = QHBoxLayout(foot_wrap)
        foot.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setStyleSheet(
            f"color: {MUTED}; font-size: {cr_px(13)}px; font-weight: bold;"
        )
        foot.addWidget(self.status_label, 0, Qt.AlignLeft)
        foot.addStretch(1)
        lay.addWidget(foot_wrap)

        self._apply_chrome("offline")

    def _apply_cps_typography(self, text: str):
        scale = cps_digit_scale(text)
        px = max(12, int(round(self._cps_base_px * scale)))
        self.cps_label.setStyleSheet(
            f"color: {self._cps_color}; font-size: {px}px; font-weight: bold; "
            f"font-family: Consolas, monospace;"
        )

    def set_index(self, index: int):
        self._index = int(index)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.pos() - self._press_pos
        if not self._dragging and (delta.manhattanLength() >= 8):
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.drag_started.emit(self._index)
        if self._dragging:
            w = QApplication.widgetAt(event.globalPos())
            while w is not None and not isinstance(w, ProbeTile):
                w = w.parentWidget()
            if isinstance(w, ProbeTile):
                self.drag_hover.emit(w._index)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._dragging:
                self.drag_finished.emit(self._index, event.globalPos())
            elif self._press_pos is not None:
                self.clicked.emit(self._client_id)
            self._press_pos = None
            self._dragging = False
            self._apply_cursor()
        super().mouseReleaseEvent(event)

    def set_reorder_enabled(self, enabled: bool):
        self.setProperty("canReorder", bool(enabled))
        self._apply_cursor()

    def set_nav_enabled(self, enabled: bool):
        self._nav_enabled = bool(enabled)
        self._apply_cursor()

    def _apply_cursor(self):
        if self._dragging:
            self.setCursor(Qt.ClosedHandCursor)
        elif self.property("canReorder"):
            self.setCursor(Qt.OpenHandCursor)
        elif getattr(self, "_nav_enabled", False):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def set_drop_highlight(self, on: bool):
        if on:
            self.setStyleSheet(self.styleSheet() + f"""
                QFrame#probeTile {{ border: 2px solid {INFO}; }}
            """)
        # full chrome refreshed on next update_data / _apply_chrome

    def _apply_chrome(self, kind: str):
        if kind == "alarm":
            border, cps = ALARM, ALARM
        elif kind == "online":
            border, cps = "#3d5a40", OK
        elif kind == "drag":
            border, cps = INFO, OK
        else:
            border, cps = BORDER, MUTED
        self.setStyleSheet(f"""
            QFrame#probeTile {{
                background-color: {PANEL};
                border: 2px solid {border};
                border-radius: {RADIUS_CARD}px;
            }}
            QFrame#probeTile QLabel {{ background: transparent; border: none; }}
        """)
        self._cps_color = cps
        self._apply_cps_typography(self.cps_label.text())
        unit_color = WARN if kind == "alarm" else MUTED
        self.unit_label.setStyleSheet(
            f"color: {unit_color}; font-size: {cr_px(16)}px; font-weight: 600;"
        )
        self._chrome_kind = kind

    def update_data(self, entry: dict, labels: dict):
        self._client_id = entry.get("client_id")
        self.name_label.setText(str(entry.get("name") or "--"))
        self.loc_label.setText(str(entry.get("location") or ""))
        online = bool(entry.get("online", False))
        hit = bool(entry.get("hit", False))
        cps = int(entry.get("cps", 0) or 0)
        if online or cps:
            cps_text = str(cps)
            self.cps_label.setText(cps_text)
        else:
            cps_text = "--"
            self.cps_label.setText(cps_text)
        self._apply_cps_typography(cps_text)
        status_qss = f"font-size: {cr_px(13)}px; font-weight: bold;"
        if hit:
            self.status_label.setText(labels.get("alarm", "ALARM"))
            self.status_label.setStyleSheet(f"color: {ALARM}; {status_qss}")
            self._apply_chrome("alarm")
        elif online:
            self.status_label.setText(labels.get("ok", "OK"))
            self.status_label.setStyleSheet(f"color: {OK}; {status_qss}")
            self._apply_chrome("online")
        else:
            self.status_label.setText(labels.get("offline", "OFF"))
            self.status_label.setStyleSheet(f"color: {MUTED}; {status_qss}")
            self._apply_chrome("offline")


class ClickCard(QFrame):
    """Sidebar card that opens a page on click."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav_enabled = False
        self.setObjectName("crCard")
        self.setCursor(Qt.ArrowCursor)
        self.setStyleSheet(f"""
            QFrame#crCard {{
                background-color: {PANEL};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_CARD}px;
            }}
            QFrame#crCard QLabel {{
                background: transparent;
                border: none;
            }}
        """)

    def set_nav_enabled(self, enabled: bool):
        self._nav_enabled = bool(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and getattr(self, "_nav_enabled", False):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_warn(self, on: bool):
        border = WARN if on else BORDER
        width = 2 if on else 1
        self.setStyleSheet(f"""
            QFrame#crCard {{
                background-color: {PANEL};
                border: {width}px solid {border};
                border-radius: {RADIUS_CARD}px;
            }}
            QFrame#crCard QLabel {{
                background: transparent;
                border: none;
            }}
        """)


class ControlRoomPage(QWidget):
    """PC control-room home: probe wall + duty sidebar."""

    probe_selected = pyqtSignal(object)
    open_alarm_log = pyqtSignal()
    open_diagnostics = pyqtSignal()
    reset_requested = pyqtSignal()
    login_requested = pyqtSignal()
    reorder_requested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self._tiles = []
        self._probe_entries = []
        self._labels = {}
        self._layout_sig = None
        self._can_reorder = False
        self._nav_enabled = False
        self._reset_wanted = False
        self._drag_from = -1
        self._drag_hover = -1
        self._build_ui()
        self.retranslate_ui()

        self._alarm_timer = QTimer(self)
        self._alarm_timer.setInterval(2000)
        self._alarm_timer.timeout.connect(self.refresh_alarm_sidebar)

    def set_alarm_polling(self, enabled: bool):
        if enabled:
            if not self._alarm_timer.isActive():
                self._alarm_timer.start()
            self.refresh_alarm_sidebar()
        else:
            self._alarm_timer.stop()

    def set_reorder_enabled(self, enabled: bool):
        self._can_reorder = bool(enabled)
        for t in self._tiles:
            t.set_reorder_enabled(self._can_reorder)

    def set_nav_enabled(self, enabled: bool):
        """未登录只看总览/日志；登录后探头卡、系统状态卡才可跳转。"""
        self._nav_enabled = bool(enabled)
        cursor = Qt.PointingHandCursor if self._nav_enabled else Qt.ArrowCursor
        for card in (getattr(self, "_system_card", None),):
            if card is None:
                continue
            card.set_nav_enabled(self._nav_enabled)
            card.setCursor(cursor)
        for t in self._tiles:
            t.set_nav_enabled(self._nav_enabled)
        self._refresh_nav_tooltips()
        if hasattr(self, "reset_btn"):
            self.reset_btn.setEnabled(
                bool(self._nav_enabled and getattr(self, "_reset_wanted", False))
            )

    def _refresh_nav_tooltips(self):
        from core.translation import _t
        if hasattr(self, "_system_card"):
            self._system_card.setToolTip(
                _t("tip_system_card_nav") if self._nav_enabled else ""
            )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        # ---- Header (desktop-readable) ----
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            f"color: {TEXT}; font-size: {cr_px(18)}px; font-weight: bold; background: transparent; border: none;"
        )
        header.addWidget(self.title_label, 0, Qt.AlignVCenter)

        self.master_link_label = QLabel("--")
        self.master_link_label.setAlignment(Qt.AlignCenter)
        self.master_link_label.setWordWrap(False)
        self.master_link_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.master_link_label.setFixedHeight(CR_CHROME_H)
        self.master_link_label.setStyleSheet(self._pill_qss(MUTED))
        header.addWidget(self.master_link_label, 0, Qt.AlignVCenter)

        header.addStretch(1)

        self.alarm_banner = QLabel()
        self.alarm_banner.setAlignment(Qt.AlignCenter)
        self.alarm_banner.setWordWrap(False)
        self.alarm_banner.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.alarm_banner.setFixedHeight(CR_CHROME_H)
        self.alarm_banner.setStyleSheet(self._pill_qss(OK))
        header.addWidget(self.alarm_banner, 0, Qt.AlignVCenter)

        self.reset_btn = QPushButton()
        self.reset_btn.setFixedHeight(CR_CHROME_H)
        self.reset_btn.setEnabled(False)
        self.reset_btn.setStyleSheet(
            self._header_btn_qss("#455a64", press="#c62828", enabled_bg=ALARM)
        )
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        header.addWidget(self.reset_btn, 0, Qt.AlignVCenter)

        self.login_btn = QPushButton()
        self.login_btn.setFixedHeight(CR_CHROME_H)
        self.login_btn.setStyleSheet(self._header_btn_qss(OK, press="#45a049"))
        self.login_btn.clicked.connect(self.login_requested.emit)
        header.addWidget(self.login_btn, 0, Qt.AlignVCenter)

        root.addLayout(header)

        # ---- Body ----
        body = QHBoxLayout()
        body.setSpacing(12)

        wall_wrap = QFrame()
        wall_wrap.setObjectName("crWall")
        wall_wrap.setStyleSheet(f"""
            QFrame#crWall {{
                background-color: {BG};
                border: 1px solid {BORDER};
                border-radius: {RADIUS_CARD}px;
            }}
        """)
        wall_lay = QVBoxLayout(wall_wrap)
        wall_lay.setContentsMargins(12, 10, 12, 12)
        wall_lay.setSpacing(8)

        wall_head = QHBoxLayout()
        self.probe_section_title = QLabel()
        self.probe_section_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;"
        )
        wall_head.addWidget(self.probe_section_title, 1)
        self.online_summary = QLabel()
        self.online_summary.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(12)}px;")
        wall_head.addWidget(self.online_summary)
        wall_lay.addLayout(wall_head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{
                background: #555; border-radius: 4px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; width: 0; background: none; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self.probe_host = QWidget()
        self.probe_host.setStyleSheet("background: transparent;")
        self.probe_grid = QGridLayout(self.probe_host)
        self.probe_grid.setContentsMargins(0, 0, 0, 0)
        self.probe_grid.setSpacing(10)
        scroll.setWidget(self.probe_host)
        wall_lay.addWidget(scroll, 1)
        body.addWidget(wall_wrap, 7)

        side = QVBoxLayout()
        side.setSpacing(10)

        # 仅保留「活动辐射」一眼指标；在线数在探头墙标题，今日数在日志页
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.kpi_active = self._make_kpi()
        kpi_row.addWidget(self.kpi_active)
        side.addLayout(kpi_row)

        occ_card = _card_frame()
        self._occ_card = occ_card
        occ_lay = QVBoxLayout(occ_card)
        occ_lay.setContentsMargins(12, 10, 12, 10)
        self.occ_title = QLabel()
        self.occ_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;"
        )
        self.occ_status = QLabel("--")
        self.occ_status.setStyleSheet(
            f"color: {TEXT}; font-size: {cr_px(16)}px; font-weight: bold;"
        )
        self.occ_desc = QLabel("")
        self.occ_desc.setWordWrap(True)
        self.occ_desc.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(12)}px;")
        occ_lay.addWidget(self.occ_title)
        occ_lay.addWidget(self.occ_status)
        occ_lay.addWidget(self.occ_desc)
        side.addWidget(occ_card)

        # 健康+故障合并：异常时加粗，点进诊断
        system_card = ClickCard()
        system_card.clicked.connect(self.open_diagnostics.emit)
        sys_lay = QVBoxLayout(system_card)
        sys_lay.setContentsMargins(12, 10, 12, 10)
        sys_lay.setSpacing(4)
        sys_head = QHBoxLayout()
        self.system_title = QLabel()
        self.system_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.system_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;"
        )
        self.system_status = QLabel("--")
        self.system_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.system_status.setWordWrap(False)
        self.system_status.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.system_status.setStyleSheet(
            f"color: {OK}; font-size: {cr_px(13)}px; font-weight: bold;"
        )
        sys_head.addWidget(self.system_title, 1, Qt.AlignVCenter)
        sys_head.addWidget(self.system_status, 0, Qt.AlignVCenter)
        sys_lay.addLayout(sys_head)
        self.system_detail = QLabel("")
        self.system_detail.setWordWrap(True)
        self.system_detail.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(12)}px;")
        sys_lay.addWidget(self.system_detail)
        self._system_card = system_card
        self._sys_health_status = ""
        self._sys_health_rows = {}
        self._sys_health_warn = False
        self._sys_fault_status = ""
        self._sys_fault_text = ""
        self._sys_fault_warn = False
        # 兼容旧属性名（避免外部引用崩溃）
        self._health_card = system_card
        self._fault_card = system_card
        self.health_status = self.system_status
        self.fault_status = self.system_status
        self.fault_text = self.system_detail
        side.addWidget(system_card)

        alarm_card = _card_frame()
        alarm_lay = QVBoxLayout(alarm_card)
        alarm_lay.setContentsMargins(12, 10, 12, 10)
        alarm_head = QHBoxLayout()
        self.alarm_list_title = QLabel()
        self.alarm_list_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;"
        )
        alarm_head.addWidget(self.alarm_list_title, 1, Qt.AlignVCenter)
        self.open_log_btn = QPushButton()
        self.open_log_btn.setFixedHeight(CR_CHROME_H)
        self.open_log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #333; color: {INFO}; border: 1px solid {INFO};
                border-radius: 6px; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;
                padding: 0 12px; min-height: {CR_CHROME_H}px; max-height: {CR_CHROME_H}px;
            }}
            QPushButton:pressed {{ background-color: {INFO}; color: white; }}
        """)
        self.open_log_btn.clicked.connect(self.open_alarm_log.emit)
        alarm_head.addWidget(self.open_log_btn, 0, Qt.AlignVCenter)
        alarm_lay.addLayout(alarm_head)

        list_qss = f"""
            QListWidget {{
                background: #1f1f1f; border: 1px solid {BORDER}; border-radius: 6px;
                color: {TEXT_DIM}; font-size: {cr_px(12)}px;
            }}
            QListWidget::item {{ padding: {cr_px(8)}px; border-bottom: 1px solid #2a2a2a; }}
            QListWidget::item:selected {{ background: #333; color: {TEXT}; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{
                background: #555; border-radius: 4px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; width: 0; background: none; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """
        self.alarm_list = QListWidget()
        self.alarm_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.alarm_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.alarm_list.setStyleSheet(list_qss)
        alarm_lay.addWidget(self.alarm_list, 2)

        self.system_list_title = QLabel()
        self.system_list_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;"
        )
        alarm_lay.addWidget(self.system_list_title)
        self.system_list = QListWidget()
        self.system_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.system_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.system_list.setMaximumHeight(cr_px(180))
        self.system_list.setStyleSheet(list_qss)
        alarm_lay.addWidget(self.system_list, 1)
        side.addWidget(alarm_card, 1)

        body.addLayout(side, 3)
        root.addLayout(body, 1)

    def _make_kpi(self):
        card = _card_frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        title = QLabel("--")
        title.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(11)}px;")
        value = QLabel("0")
        value.setStyleSheet(
            f"color: {TEXT}; font-size: {cr_px(22)}px; font-weight: bold;"
        )
        lay.addWidget(title)
        lay.addWidget(value)
        card._title = title
        card._value = value
        return card

    @staticmethod
    def _hex_rgba(color: str, alpha: float) -> str:
        h = (color or "#888888").lstrip("#")
        if len(h) < 6:
            h = "888888"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "rgba(%d, %d, %d, %.2f)" % (r, g, b, alpha)

    @staticmethod
    def _pill_qss(color: str, emphasis: bool = False) -> str:
        if emphasis:
            px = cr_px(16)
            return f"""
                QLabel {{
                    color: {color}; font-size: {px}px; font-weight: bold;
                    padding: 6px 18px; border: 2px solid {color};
                    border-radius: 8px;
                    background: {ControlRoomPage._hex_rgba(color, 0.22)};
                }}
            """
        return f"""
            QLabel {{
                color: {color}; font-size: {CR_CHROME_FONT_PX}px; font-weight: bold;
                padding: 0 12px; border: 1px solid {color};
                border-radius: 6px; background: rgba(0,0,0,0.25);
            }}
        """

    def _apply_pill(self, label, color: str, emphasis: bool = False):
        h = cr_px(42) if emphasis else CR_CHROME_H
        label.setFixedHeight(h)
        label.setMinimumWidth(cr_px(108) if emphasis else 0)
        label.setStyleSheet(self._pill_qss(color, emphasis=emphasis))

    @staticmethod
    def _header_btn_qss(bg: str, press: str = None, enabled_bg: str = None) -> str:
        press = press or bg
        extra = ""
        if enabled_bg:
            extra = f"""
            QPushButton:enabled {{ background-color: {enabled_bg}; }}
            QPushButton:pressed:enabled {{ background-color: {press}; }}
            """
        else:
            extra = f"""
            QPushButton:pressed {{ background-color: {press}; }}
            """
        return f"""
            QPushButton {{
                background-color: {bg}; color: white; border: none;
                border-radius: {RADIUS_BTN}px; font-size: {CR_CHROME_FONT_PX}px;
                font-weight: bold; padding: 0 12px;
                min-height: {CR_CHROME_H}px; max-height: {CR_CHROME_H}px;
            }}
            {extra}
            QPushButton:disabled {{ background-color: #333; color: #777; }}
        """

    def retranslate_ui(self):
        from core.translation import _t
        self._labels = {
            "ok": _t("probe_tile_ok"),
            "alarm": _t("probe_tile_alarm"),
            "offline": _t("probe_tile_offline"),
        }
        self.title_label.setText(_t("control_room_title"))
        self.probe_section_title.setText(_t("control_room_probe_wall"))
        self.occ_title.setText(_t("control_room_occupancy"))
        if hasattr(self, "system_title"):
            self.system_title.setText(_t("control_room_system_status"))
        self._refresh_nav_tooltips()
        self.alarm_list_title.setText(_t("control_room_recent_alarms"))
        if hasattr(self, "system_list_title"):
            self.system_list_title.setText(_t("control_room_system_events"))
        self.open_log_btn.setText(_t("control_room_open_log"))
        self.reset_btn.setText(_t("btn_channel_alarm_reset_active"))
        self.kpi_active._title.setText(_t("control_room_kpi_active"))
        self._refresh_system_card()
        self.refresh_alarm_sidebar()
        parent = getattr(self, "parent", None)
        home = getattr(parent, "home_page", None) if parent is not None else None
        for i, e in enumerate(self._probe_entries):
            cid = e.get("client_id")
            if cid and parent is not None and hasattr(parent, "get_probe_label"):
                try:
                    label = parent.get_probe_label(cid)
                    if label:
                        e["name"] = label
                except Exception:
                    pass
            elif not e.get("name"):
                e["name"] = _t("probe_slot_name", n=i + 1)
            if home is not None and hasattr(home, "_slot_location"):
                try:
                    e["location"] = home._slot_location(i)
                except Exception:
                    pass
        self._relabel_tiles()

    def set_login_visible(self, visible: bool):
        """visible=True 显示登录；False 表示已登录，改成退出。"""
        from core.translation import _t
        self.login_btn.setVisible(True)
        if visible:
            self.login_btn.setText(_t("btn_login"))
            self.login_btn.setStyleSheet(self._header_btn_qss(OK, press="#45a049"))
        else:
            self.login_btn.setText(_t("btn_logout"))
            self.login_btn.setStyleSheet(self._header_btn_qss(ALARM, press="#c62828"))
        self.set_nav_enabled(not visible)

    def set_master_link(self, text: str, level: str = "ok"):
        self.master_link_label.setText(text or "--")
        emphasis = str(level) == "offline"
        color = {"ok": OK, "warn": WARN, "offline": WARN}.get(level, MUTED)
        self._apply_pill(self.master_link_label, color, emphasis=emphasis)

    def set_channel_alarm(self, active: bool, latch_text: str = "", kind: str = "normal"):
        from core.translation import _t
        if active:
            self._reset_wanted = True
            self.alarm_banner.setText(latch_text or _t("side_tag_alarm"))
            self._apply_pill(self.alarm_banner, ALARM, emphasis=True)
            self.reset_btn.setEnabled(getattr(self, "_nav_enabled", False))
        elif kind == "offline":
            # 主控离线由顶栏链路胶囊表达，banner 只标「硬报暂停」避免与链路重复抢视线
            self._reset_wanted = False
            self.alarm_banner.setText(_t("control_room_rad_paused"))
            self._apply_pill(self.alarm_banner, MUTED, emphasis=False)
            self.reset_btn.setEnabled(False)
        elif kind == "warn":
            self._reset_wanted = False
            self.alarm_banner.setText(latch_text or _t("side_tag_warn"))
            self._apply_pill(self.alarm_banner, WARN, emphasis=True)
            self.reset_btn.setEnabled(False)
        else:
            self._reset_wanted = False
            self.alarm_banner.setText(_t("side_tag_ok"))
            self._apply_pill(self.alarm_banner, OK, emphasis=False)
            self.reset_btn.setEnabled(False)

    def set_occupancy(self, kind, status: str, desc: str = ""):
        if isinstance(kind, bool):
            kind = "passing" if kind else "vacant"
        kind = str(kind or "vacant")
        self.occ_status.setText(status or "--")
        self.occ_desc.setText(desc or "")
        color = {
            "alarm": ALARM,
            "passing": INFO,
            "offline": WARN,
            "ungated": WARN,
            "noconn": MUTED,
            "vacant": OK,
        }.get(kind, TEXT)
        emph = kind in ("offline", "alarm", "ungated")
        self.occ_status.setStyleSheet(
            f"color: {color}; font-size: {cr_px(16)}px; font-weight: bold;"
        )
        if hasattr(self, "_occ_card"):
            border = color if emph else BORDER
            width = 2 if emph else 1
            self._occ_card.setStyleSheet(f"""
                QFrame#crCard {{
                    background-color: {PANEL};
                    border: {width}px solid {border};
                    border-radius: {RADIUS_CARD}px;
                }}
                QFrame#crCard QLabel {{
                    background: transparent;
                    border: none;
                }}
            """)

    def set_health_summary(self, status: str, rows: dict, warn: bool = False):
        self._sys_health_status = status or ""
        self._sys_health_rows = rows or {}
        self._sys_health_warn = bool(warn)
        self._refresh_system_card()

    def set_fault_summary(self, status: str, text: str, warn: bool = False):
        self._sys_fault_status = status or ""
        self._sys_fault_text = text or ""
        self._sys_fault_warn = bool(warn)
        self._refresh_system_card()

    def _refresh_system_card(self):
        """合并健康/故障为一张系统状态卡。"""
        from core.translation import _t
        if not hasattr(self, "system_status"):
            return
        warn = bool(getattr(self, "_sys_fault_warn", False) or getattr(self, "_sys_health_warn", False))
        if getattr(self, "_sys_fault_warn", False) and getattr(self, "_sys_fault_status", ""):
            status = self._sys_fault_status
        elif getattr(self, "_sys_health_status", ""):
            status = self._sys_health_status
        else:
            status = _t("status_health_ok")
        color = WARN if warn else OK
        self.system_status.setText(status)
        self.system_status.setStyleSheet(
            f"color: {color}; font-size: {cr_px(13)}px; font-weight: bold;"
        )
        if getattr(self, "_sys_fault_warn", False) and getattr(self, "_sys_fault_text", "").strip():
            detail = self._sys_fault_text.strip()
        else:
            rows = getattr(self, "_sys_health_rows", None) or {}
            parts = []
            if rows.get("probeComm"):
                parts.append("%s %s" % (_t("kv_probe_comm"), rows.get("probeComm")))
            if rows.get("irStatus"):
                parts.append("%s %s" % (_t("kv_ir_status"), rows.get("irStatus")))
            detail = " · ".join(parts) if parts else _t("desc_fault_summary_none")
        self.system_detail.setText(detail)
        self.system_detail.setStyleSheet(
            f"color: {WARN if warn else MUTED}; font-size: {cr_px(12)}px;"
        )
        if hasattr(self, "_system_card"):
            self._system_card.set_warn(warn)

    def _make_tile(self):
        tile = ProbeTile(self.probe_host)
        tile.clicked.connect(self._on_tile_clicked)
        tile.drag_started.connect(self._on_drag_started)
        tile.drag_hover.connect(self._on_drag_hover)
        tile.drag_finished.connect(self._on_drag_finished)
        tile.set_reorder_enabled(self._can_reorder)
        tile.set_nav_enabled(self._nav_enabled)
        return tile

    def update_probes(self, entries, total_cps=0):
        self._probe_entries = list(entries or [])
        n = len(self._probe_entries)
        online = sum(1 for e in self._probe_entries if e.get("online"))
        from core.translation import _t
        self.online_summary.setText(_t("control_room_online_fmt", online=online, total=n))

        while len(self._tiles) < max(n, 1):
            self._tiles.append(self._make_tile())
        for i, tile in enumerate(self._tiles):
            tile.setVisible(i < max(n, 1) and (n > 0 or i == 0))
            tile.set_index(i)

        cols = 2 if n <= 4 else (3 if n <= 9 else 4)
        if n == 0:
            cols = 1
        sig = (n, cols)
        if sig != self._layout_sig:
            self._layout_sig = sig
            while self.probe_grid.count():
                item = self.probe_grid.takeAt(0)
                w = item.widget()
                if w is not None:
                    self.probe_grid.removeWidget(w)
            if n == 0:
                self._tiles[0].setVisible(True)
                self._tiles[0].set_index(0)
                self.probe_grid.addWidget(self._tiles[0], 0, 0)
            else:
                for i in range(n):
                    self._tiles[i].set_index(i)
                    self.probe_grid.addWidget(self._tiles[i], i // cols, i % cols)

        if n == 0:
            self._tiles[0].update_data(
                {"name": "--", "location": "", "cps": 0, "online": False, "hit": False},
                self._labels,
            )
        else:
            for i in range(n):
                self._tiles[i].set_index(i)
                self._tiles[i].update_data(self._probe_entries[i], self._labels)

    def _relabel_tiles(self):
        for i, e in enumerate(self._probe_entries):
            if i < len(self._tiles):
                self._tiles[i].update_data(e, self._labels)

    def _on_tile_clicked(self, client_id):
        if self._drag_from >= 0:
            return
        if not getattr(self, "_nav_enabled", False):
            return
        self.probe_selected.emit(client_id)

    def _on_drag_started(self, index: int):
        if not self._can_reorder:
            return
        self._drag_from = int(index)
        self._drag_hover = -1
        if 0 <= index < len(self._tiles):
            self._tiles[index]._apply_chrome("drag")

    def _on_drag_hover(self, index: int):
        if not self._can_reorder or self._drag_from < 0:
            return
        if index == self._drag_hover:
            return
        # clear previous
        if 0 <= self._drag_hover < len(self._tiles) and self._drag_hover != self._drag_from:
            if self._drag_hover < len(self._probe_entries):
                self._tiles[self._drag_hover].update_data(
                    self._probe_entries[self._drag_hover], self._labels
                )
        self._drag_hover = int(index)
        if 0 <= index < len(self._tiles) and index != self._drag_from:
            self._tiles[index]._apply_chrome("drag")

    def _on_drag_finished(self, from_index: int, global_pos):
        to_index = -1
        w = QApplication.widgetAt(global_pos)
        while w is not None and not isinstance(w, ProbeTile):
            w = w.parentWidget()
        if isinstance(w, ProbeTile):
            to_index = w._index

        src = self._drag_from if self._drag_from >= 0 else from_index
        self._drag_from = -1
        self._drag_hover = -1

        # restore chrome
        for i, e in enumerate(self._probe_entries):
            if i < len(self._tiles):
                self._tiles[i].update_data(e, self._labels)

        if not self._can_reorder:
            return
        if to_index < 0 or src < 0 or to_index == src:
            return
        if src >= len(self._probe_entries) or to_index >= len(self._probe_entries):
            return
        self.reorder_requested.emit(src, to_index)

    def refresh_alarm_sidebar(self):
        from core.translation import _t
        from core.alarm_log_page import (
            format_alarm_event_client, format_alarm_event_status, format_alarm_fault_code,
        )

        def _fill_list(widget, lines, events, active_color=Qt.red):
            prev_text = ""
            cur = widget.currentItem()
            if cur is not None:
                prev_text = cur.text()
            bar = widget.verticalScrollBar()
            scroll_val = bar.value()
            if bar.isSliderDown():
                return
            old_lines = [
                widget.item(i).text()
                for i in range(widget.count())
                if widget.item(i) is not None
            ]
            if lines == old_lines:
                return
            widget.clear()
            restore_row = -1
            for i, line in enumerate(lines):
                item = QListWidgetItem(line)
                if events and i < len(events) and events[i].alarm_status:
                    item.setForeground(active_color)
                widget.addItem(item)
                if prev_text and line == prev_text:
                    restore_row = i
            if restore_row >= 0:
                widget.setCurrentRow(restore_row)
            bar.setValue(scroll_val)

        try:
            from core.alarm_logger import get_alarm_logger
            logger = get_alarm_logger()
            stats = logger.get_statistics() or {}
            active_n = int(stats.get("active_alarms", 0) or 0)
            self.kpi_active._value.setText(str(active_n))
            color = ALARM if active_n else TEXT
            self.kpi_active._value.setStyleSheet(
                f"color: {color}; font-size: {cr_px(22)}px; font-weight: bold;"
            )

            rad_events = list(logger.get_recent_events(40, category="radiation") or [])
            rad_events.reverse()
            rad_lines = []
            if not rad_events:
                rad_lines.append(_t("control_room_no_alarms"))
            else:
                for ev in rad_events[:20]:
                    try:
                        ts = datetime.fromtimestamp(float(ev.timestamp)).strftime("%H:%M:%S")
                    except Exception:
                        ts = "--:--:--"
                    st = format_alarm_event_status(ev)
                    client = format_alarm_event_client(ev)
                    peak = float(getattr(ev, "peak_count_rate", None) or ev.count_rate or 0)
                    rad_lines.append("%s  %s  %s  %.0f cps" % (
                        ts, client or "-", st, peak,
                    ))
            _fill_list(self.alarm_list, rad_lines, rad_events, Qt.red)

            if hasattr(self, "system_list"):
                sys_events = list(logger.get_recent_events(40, category="system") or [])
                sys_events.reverse()
                sys_lines = []
                # 活动主控 M 码：诊断里有、或清屏后仍活动但无历史行 → 补「当前」行
                live_codes = []
                for cid, on in (logger.get_active_alarms() or {}).items():
                    if on and str(cid).startswith("master_fault_"):
                        live_codes.append(str(cid).replace("master_fault_", "", 1))
                parent = getattr(self, "parent", None)
                if parent is not None and hasattr(parent, "_master_fault_entries"):
                    try:
                        for code in parent._master_fault_entries() or []:
                            if code not in live_codes:
                                live_codes.append(code)
                    except Exception:
                        pass
                hist_any = set()
                for ev in sys_events:
                    hist_any.add(format_alarm_fault_code(ev))

                if not sys_events and not live_codes:
                    sys_lines.append(_t("control_room_no_system_events"))
                    _fill_list(self.system_list, sys_lines, [], Qt.yellow)
                else:
                    extra_live = [c for c in live_codes if c not in hist_any]
                    for code in extra_live:
                        sys_lines.append(
                            "%s  %s  %s" % (
                                _t("control_room_system_live"),
                                code,
                                _t("log_status_link_down"),
                            )
                        )
                    for ev in sys_events[:12]:
                        try:
                            ts = datetime.fromtimestamp(float(ev.timestamp)).strftime("%H:%M:%S")
                        except Exception:
                            ts = "--:--:--"
                        code = format_alarm_fault_code(ev)
                        st = format_alarm_event_status(ev)
                        dur = ""
                        if float(getattr(ev, "duration", 0) or 0) > 0:
                            dur = "  %.0fs" % float(ev.duration)
                        sys_lines.append("%s  %s  %s%s" % (ts, code, st, dur))
                    # fake event objects only for coloring live rows
                    class _Live:
                        alarm_status = True
                    paint = [_Live() for _ in extra_live] + list(sys_events[:12])
                    _fill_list(self.system_list, sys_lines, paint, Qt.yellow)
        except Exception:
            pass
