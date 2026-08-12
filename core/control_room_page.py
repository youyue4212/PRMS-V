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
    RADIUS_CARD, RADIUS_BTN, cr_px, cr_cps_px,
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
        self.setObjectName("probeTile")
        self.setCursor(Qt.PointingHandCursor)
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

        self.cps_label = QLabel("--")
        self.cps_label.setAlignment(Qt.AlignCenter)
        self.cps_label.setStyleSheet(
            f"color: {OK}; font-size: {cr_cps_px(36)}px; font-weight: bold; font-family: Consolas, monospace;"
        )
        lay.addWidget(self.cps_label, 1)

        foot = QHBoxLayout()
        self.unit_label = QLabel("CPS")
        self.unit_label.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(13)}px;")
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setStyleSheet(
            f"color: {MUTED}; font-size: {cr_px(13)}px; font-weight: bold;"
        )
        foot.addWidget(self.unit_label)
        foot.addWidget(self.status_label, 1)
        lay.addLayout(foot)

        self._apply_chrome("offline")

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
            self.setCursor(Qt.OpenHandCursor if self.property("canReorder") else Qt.PointingHandCursor)
        super().mouseReleaseEvent(event)

    def set_reorder_enabled(self, enabled: bool):
        self.setProperty("canReorder", bool(enabled))
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.PointingHandCursor)

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
        self.cps_label.setStyleSheet(
            f"color: {cps}; font-size: {cr_cps_px(36)}px; font-weight: bold; font-family: Consolas, monospace;"
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
            self.cps_label.setText(str(cps))
        else:
            self.cps_label.setText("--")
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


class ControlRoomPage(QWidget):
    """PC control-room home: probe wall + duty sidebar."""

    probe_selected = pyqtSignal(object)
    open_alarm_log = pyqtSignal()
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
        self.hint_label.setText(self._hint_text())

    def _hint_text(self):
        from core.translation import _t
        if self._can_reorder:
            return _t("control_room_hint_reorder")
        return _t("control_room_hint")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(10)

        # ---- Header (desktop-readable) ----
        header = QHBoxLayout()
        header.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            f"color: {TEXT}; font-size: {cr_px(20)}px; font-weight: bold; background: transparent; border: none;"
        )
        header.addWidget(self.title_label)

        self.master_link_label = QLabel("--")
        self.master_link_label.setAlignment(Qt.AlignCenter)
        self.master_link_label.setMinimumWidth(cr_px(140))
        self.master_link_label.setStyleSheet(self._pill_qss(MUTED))
        header.addWidget(self.master_link_label)

        header.addStretch(1)

        self.total_cps_label = QLabel("0")
        self.total_cps_label.setAlignment(Qt.AlignCenter)
        self.total_cps_label.setStyleSheet(
            f"color: {OK}; font-size: {cr_cps_px(30)}px; font-weight: bold; padding: 2px 10px;"
        )
        header.addWidget(self.total_cps_label)
        self.total_cps_unit = QLabel("CPS")
        self.total_cps_unit.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(14)}px;")
        header.addWidget(self.total_cps_unit)

        self.alarm_banner = QLabel()
        self.alarm_banner.setAlignment(Qt.AlignCenter)
        self.alarm_banner.setMinimumWidth(cr_px(120))
        self.alarm_banner.setStyleSheet(self._pill_qss(OK))
        header.addWidget(self.alarm_banner)

        btn_h = cr_px(36)
        self.reset_btn = QPushButton()
        self.reset_btn.setFixedHeight(btn_h)
        self.reset_btn.setEnabled(False)
        self.reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #455a64; color: white; border: none;
                border-radius: {RADIUS_BTN}px; font-size: {cr_px(12)}px; font-weight: bold;
                padding: 0 14px; min-height: {btn_h}px;
            }}
            QPushButton:enabled {{ background-color: {ALARM}; }}
            QPushButton:pressed:enabled {{ background-color: #c62828; }}
            QPushButton:disabled {{ background-color: #333; color: #777; }}
        """)
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        header.addWidget(self.reset_btn)

        self.login_btn = QPushButton()
        self.login_btn.setFixedHeight(btn_h)
        self.login_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {OK}; color: white; border: none;
                border-radius: {RADIUS_BTN}px; font-size: {cr_px(12)}px; font-weight: bold;
                padding: 0 14px; min-height: {btn_h}px;
            }}
            QPushButton:pressed {{ background-color: #45a049; }}
        """)
        self.login_btn.clicked.connect(self.login_requested.emit)
        header.addWidget(self.login_btn)

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
            f"color: {TEXT_DIM}; font-size: {cr_px(14)}px; font-weight: bold;"
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

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.kpi_active = self._make_kpi()
        self.kpi_today = self._make_kpi()
        self.kpi_online = self._make_kpi()
        kpi_row.addWidget(self.kpi_active)
        kpi_row.addWidget(self.kpi_today)
        kpi_row.addWidget(self.kpi_online)
        side.addLayout(kpi_row)

        occ_card = _card_frame()
        occ_lay = QVBoxLayout(occ_card)
        occ_lay.setContentsMargins(12, 10, 12, 10)
        self.occ_title = QLabel()
        self.occ_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {cr_px(12)}px; font-weight: bold;"
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

        alarm_card = _card_frame()
        alarm_lay = QVBoxLayout(alarm_card)
        alarm_lay.setContentsMargins(12, 10, 12, 10)
        alarm_head = QHBoxLayout()
        self.alarm_list_title = QLabel()
        self.alarm_list_title.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: {cr_px(12)}px; font-weight: bold;"
        )
        alarm_head.addWidget(self.alarm_list_title, 1)
        self.open_log_btn = QPushButton()
        self.open_log_btn.setFixedHeight(cr_px(32))
        self.open_log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #333; color: {INFO}; border: 1px solid {INFO};
                border-radius: 6px; font-size: {cr_px(12)}px; font-weight: bold; padding: 0 10px;
            }}
            QPushButton:pressed {{ background-color: {INFO}; color: white; }}
        """)
        self.open_log_btn.clicked.connect(self.open_alarm_log.emit)
        alarm_head.addWidget(self.open_log_btn)
        alarm_lay.addLayout(alarm_head)

        self.alarm_list = QListWidget()
        self.alarm_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.alarm_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.alarm_list.setStyleSheet(f"""
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
        """)
        alarm_lay.addWidget(self.alarm_list, 1)
        side.addWidget(alarm_card, 1)

        body.addLayout(side, 3)
        root.addLayout(body, 1)

        self.hint_label = QLabel()
        self.hint_label.setStyleSheet(f"color: {MUTED}; font-size: {cr_px(11)}px;")
        root.addWidget(self.hint_label)

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
    def _pill_qss(color: str) -> str:
        return f"""
            QLabel {{
                color: {color}; font-size: {cr_px(12)}px; font-weight: bold;
                padding: {cr_px(6)}px {cr_px(10)}px; border: 1px solid {color};
                border-radius: 8px; background: rgba(0,0,0,0.25);
            }}
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
        self.alarm_list_title.setText(_t("control_room_recent_alarms"))
        self.open_log_btn.setText(_t("control_room_open_log"))
        self.reset_btn.setText(_t("btn_channel_alarm_reset_active"))
        self.login_btn.setText(_t("btn_login"))
        self.hint_label.setText(self._hint_text())
        self.kpi_active._title.setText(_t("control_room_kpi_active"))
        self.kpi_today._title.setText(_t("control_room_kpi_today"))
        self.kpi_online._title.setText(_t("control_room_kpi_online"))
        self.total_cps_unit.setText("CPS")
        self.refresh_alarm_sidebar()
        self._relabel_tiles()

    def set_login_visible(self, visible: bool):
        self.login_btn.setVisible(bool(visible))

    def set_master_link(self, text: str, level: str = "ok"):
        self.master_link_label.setText(text or "--")
        color = {"ok": OK, "warn": WARN, "offline": ALARM}.get(level, MUTED)
        self.master_link_label.setStyleSheet(self._pill_qss(color))

    def set_channel_alarm(self, active: bool, latch_text: str = ""):
        from core.translation import _t
        if active:
            self.alarm_banner.setText(latch_text or _t("side_tag_alarm"))
            self.alarm_banner.setStyleSheet(self._pill_qss(ALARM))
            self.reset_btn.setEnabled(True)
        else:
            self.alarm_banner.setText(_t("side_tag_ok"))
            self.alarm_banner.setStyleSheet(self._pill_qss(OK))
            self.reset_btn.setEnabled(False)

    def set_occupancy(self, busy: bool, status: str, desc: str = ""):
        self.occ_status.setText(status or "--")
        self.occ_desc.setText(desc or "")
        color = INFO if busy else OK
        self.occ_status.setStyleSheet(
            f"color: {color}; font-size: {cr_px(16)}px; font-weight: bold;"
        )

    def _make_tile(self):
        tile = ProbeTile(self.probe_host)
        tile.clicked.connect(self._on_tile_clicked)
        tile.drag_started.connect(self._on_drag_started)
        tile.drag_hover.connect(self._on_drag_hover)
        tile.drag_finished.connect(self._on_drag_finished)
        tile.set_reorder_enabled(self._can_reorder)
        return tile

    def update_probes(self, entries, total_cps=0):
        self._probe_entries = list(entries or [])
        self.total_cps_label.setText(str(int(total_cps or 0)))
        n = len(self._probe_entries)
        online = sum(1 for e in self._probe_entries if e.get("online"))
        from core.translation import _t
        self.online_summary.setText(_t("control_room_online_fmt", online=online, total=n))
        self.kpi_online._value.setText("%d/%d" % (online, n))

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
        # Preserve selection across refresh
        prev_text = ""
        cur = self.alarm_list.currentItem()
        if cur is not None:
            prev_text = cur.text()
        try:
            from core.alarm_logger import get_alarm_logger
            logger = get_alarm_logger()
            stats = logger.get_statistics() or {}
            active_n = int(stats.get("active_alarms", 0) or 0)
            today_n = int(stats.get("today_events", 0) or 0)
            self.kpi_active._value.setText(str(active_n))
            self.kpi_today._value.setText(str(today_n))
            color = ALARM if active_n else TEXT
            self.kpi_active._value.setStyleSheet(
                f"color: {color}; font-size: {cr_px(22)}px; font-weight: bold;"
            )

            events = list(logger.get_recent_events(40) or [])
            events.reverse()
            self.alarm_list.clear()
            if not events:
                self.alarm_list.addItem(QListWidgetItem(_t("control_room_no_alarms")))
                return
            restore_row = -1
            for i, ev in enumerate(events[:30]):
                try:
                    ts = datetime.fromtimestamp(float(ev.timestamp)).strftime("%H:%M:%S")
                except Exception:
                    ts = "--:--:--"
                st = _t("log_status_active") if ev.alarm_status else _t("log_status_cleared")
                line = "%s  %s  %s  %.0f cps" % (
                    ts, ev.client_id or "-", st, float(ev.count_rate or 0),
                )
                item = QListWidgetItem(line)
                if ev.alarm_status:
                    item.setForeground(Qt.red)
                self.alarm_list.addItem(item)
                if prev_text and line == prev_text:
                    restore_row = i
            if restore_row >= 0:
                self.alarm_list.setCurrentRow(restore_row)
        except Exception:
            pass
