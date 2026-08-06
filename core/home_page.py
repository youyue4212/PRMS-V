#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Public home monitor page (no login).
Shows: alarm status, per-probe CPS, channel occupancy.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QScrollArea, QPushButton
)
from PyQt5.QtSvg import QSvgWidget

from core.icons import get_icon_svg
import time

HOME_STATUS_HEIGHT = 200
PROBE_TILE_MIN_WIDTH = 160
PROBE_TILE_HEIGHT = 120
# online_mask / 短暂断包时防抖：连续离线超过该秒数才显示灰色
PROBE_OFFLINE_HOLD_SEC = 2.0


def _scroll_label(max_height=36):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setMaximumHeight(max_height)
    scroll.setStyleSheet("""
        QScrollArea { background: transparent; border: none; }
        QScrollBar:vertical { width: 4px; background: transparent; }
        QScrollBar::handle:vertical { background: #555555; border-radius: 2px; }
    """)
    label = QLabel("")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignCenter)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    scroll.setWidget(label)
    return scroll, label


class ProbeCpsTile(QFrame):
    def __init__(self, slot_index: int, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.setFixedHeight(PROBE_TILE_HEIGHT)
        self.setMinimumWidth(PROBE_TILE_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_style(False, False, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        self.name_label = QLabel("Probe %d" % (slot_index + 1))
        self.name_label.setStyleSheet("color: #bbbbbb; font-size: 13px; font-weight: bold;")
        lay.addWidget(self.name_label)

        self.cps_label = QLabel("--")
        self.cps_label.setAlignment(Qt.AlignCenter)
        self.cps_label.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold;")
        lay.addWidget(self.cps_label, 1)

        self.unit_label = QLabel("cps")
        self.unit_label.setAlignment(Qt.AlignCenter)
        self.unit_label.setStyleSheet("color: #888888; font-size: 12px;")
        lay.addWidget(self.unit_label)

        self.state_label = QLabel("--")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("color: #888888; font-size: 12px;")
        lay.addWidget(self.state_label)

    def _apply_style(self, online, hit, offline_master=False):
        if offline_master:
            border = "#555555"
        elif hit:
            border = "#ff4444"
        elif online:
            border = "#4caf50"
        else:
            border = "#888888"
        self.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 8px;
                border: 2px solid %s;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2a2a2a, stop: 1 #1f1f1f);
            }
        """ % border)

    def update_tile(self, cps, online, hit, master_online=True, lang="zh", waiting=False):
        """waiting=True: no master and no probe data yet."""
        if waiting:
            self.cps_label.setText("--")
            self.state_label.setText("Waiting" if lang == "en" else "\u7b49\u5f85\u6570\u636e")
            self.state_label.setStyleSheet("color: #888888; font-size: 12px;")
            self.cps_label.setStyleSheet("color: #888888; font-size: 32px; font-weight: bold;")
            self._apply_style(False, False, True)
            return
        self.cps_label.setText(str(int(cps)))
        if hit:
            self.state_label.setText("HIT" if lang == "en" else "\u8d85\u9650")
            self.state_label.setStyleSheet("color: #ff6666; font-size: 12px; font-weight: bold;")
            self.cps_label.setStyleSheet("color: #ff6666; font-size: 32px; font-weight: bold;")
        elif online:
            suffix = "" if master_online else (" (probe)" if lang == "en" else "(\u63a2\u5934)")
            self.state_label.setText(("Online" if lang == "en" else "\u5728\u7ebf") + suffix)
            self.state_label.setStyleSheet("color: #81c784; font-size: 12px;")
            self.cps_label.setStyleSheet("color: #ffffff; font-size: 32px; font-weight: bold;")
        else:
            self.state_label.setText("Offline" if lang == "en" else "\u79bb\u7ebf")
            self.state_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
            self.cps_label.setStyleSheet("color: #888888; font-size: 32px; font-weight: bold;")
        self._apply_style(online, hit, False)

    def set_name(self, text):
        self.name_label.setText(text)


class HomePage(QWidget):
    """Public monitor: alarm / channel / per-probe CPS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.probe_tiles = []
        # slot → {'offline_since': float|None, 'last': (cps, online, hit)}
        self._tile_hold = {}
        self._had_tile_data = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.title = QLabel("\u901a\u9053\u8f90\u5c04\u76d1\u6d4b")
        self.title.setStyleSheet("color: white; font-size: 20px; font-weight: bold;")
        top.addWidget(self.title)
        top.addStretch(1)

        self.total_cps_caption = QLabel("\u5408\u8ba1")
        self.total_cps_caption.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        top.addWidget(self.total_cps_caption)
        self.total_cps_label = QLabel("0 cps")
        self.total_cps_label.setStyleSheet(
            "color: #ffffff; font-size: 22px; font-weight: bold; padding-right: 8px;"
        )
        top.addWidget(self.total_cps_label)

        self.master_relay_label = QLabel("--")
        self.master_relay_label.setStyleSheet("color: #888888; font-size: 12px;")
        top.addWidget(self.master_relay_label)

        self.master_link_label = QLabel("\u4e3b\u63a7: \u672a\u8fde\u63a5")
        self.master_link_label.setStyleSheet("""
            QLabel {
                color: #ff9800; font-size: 12px; font-weight: bold;
                padding: 4px 10px;
                background-color: rgba(255, 152, 0, 0.12);
                border: 1px solid rgba(255, 152, 0, 0.35);
                border-radius: 8px;
            }
        """)
        top.addWidget(self.master_link_label)
        layout.addLayout(top)

        # Region: alarm + occupancy
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.alarm_card, self.alarm_title_icon, self.alarm_indicator, \
            self.alarm_title_label, self.alarm_status_label, \
            self.alarm_desc_scroll, self.alarm_desc_label, \
            self.status_indicator_bar = self._build_status_card(
                "\u62a5\u8b66\u72b6\u6001", "alarm_inactive", "\u7cfb\u7edf\u6b63\u5e38", "\u672a\u68c0\u6d4b\u5230\u5f02\u5e38"
            )
        # 通道硬报人工复位（仅主控 0x15）
        alarm_lay = self.alarm_card.layout()
        self.channel_reset_btn = QPushButton("\u901a\u9053\u62a5\u8b66\u590d\u4f4d")
        self.channel_reset_btn.setEnabled(False)
        self.channel_reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #c62828; color: white; font-weight: bold;
                border: none; border-radius: 6px; padding: 4px 10px; font-size: 12px;
            }
            QPushButton:disabled {
                background-color: #555555; color: #999999;
            }
            QPushButton:pressed { background-color: #8e0000; }
        """)
        # insert before bottom status bar
        if alarm_lay is not None and alarm_lay.count() > 0:
            alarm_lay.insertWidget(max(0, alarm_lay.count() - 1), self.channel_reset_btn)
        self.occupancy_card, self.occupancy_title_icon, self.occupancy_indicator, \
            self.occupancy_title_label, self.occupancy_status_label, \
            self.occupancy_desc_scroll, self.occupancy_desc_label, \
            self.occupancy_indicator_bar = self._build_status_card(
                "\u901a\u9053\u72b6\u6001", "occupancy_inactive", "\u901a\u9053\u7a7a\u95f2", "\u672a\u68c0\u6d4b\u5230\u4eba\u5458\u7ecf\u8fc7"
            )
        status_row.addWidget(self.alarm_card, 1)
        status_row.addWidget(self.occupancy_card, 1)
        layout.addLayout(status_row)

        # Region: per-probe CPS
        self.probe_section_title = QLabel("\u5404\u63a2\u5934\u8ba1\u6570\u7387")
        self.probe_section_title.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        layout.addWidget(self.probe_section_title)

        self.probe_scroll = QScrollArea()
        self.probe_scroll.setWidgetResizable(True)
        self.probe_scroll.setFrameShape(QFrame.NoFrame)
        self.probe_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.probe_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: #555555; border-radius: 3px; }
        """)
        self.probe_grid_host = QWidget()
        self.probe_grid = QGridLayout(self.probe_grid_host)
        self.probe_grid.setContentsMargins(0, 0, 0, 0)
        self.probe_grid.setSpacing(10)
        self.probe_scroll.setWidget(self.probe_grid_host)
        layout.addWidget(self.probe_scroll, 1)

        self.ensure_probe_tiles(2)

    def _build_status_card(self, title, icon_tag, status_text, desc_text):
        card = QFrame()
        card.setFixedHeight(HOME_STATUS_HEIGHT)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a; border-radius: 10px; border: none;
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #2a2a2a, stop: 1 #1f1f1f);
            }
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(4)

        title_row = QHBoxLayout()
        title_icon = QSvgWidget()
        title_icon.setFixedSize(16, 16)
        title_icon.load(get_icon_svg(icon_tag))
        title_row.addWidget(title_icon)
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: bold;")
        title_row.addWidget(title_label)
        title_row.addStretch()
        lay.addLayout(title_row)

        indicator = QSvgWidget()
        indicator.setFixedSize(44, 44)
        indicator.load(get_icon_svg(icon_tag))
        lay.addWidget(indicator, 0, Qt.AlignCenter)

        status_label = QLabel(status_text)
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet("""
            QLabel {
                color: #4caf50; font-size: 16px; font-weight: bold;
                padding: 2px 8px;
                background-color: rgba(76, 175, 80, 0.1);
                border-radius: 8px;
                border: 1px solid rgba(76, 175, 80, 0.3);
            }
        """)
        lay.addWidget(status_label, 0, Qt.AlignCenter)

        desc_scroll, desc_label = _scroll_label(36)
        desc_label.setText(desc_text)
        desc_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        lay.addWidget(desc_scroll)

        bar = QFrame()
        bar.setFixedHeight(2)
        bar.setStyleSheet("QFrame { background-color: #4caf50; border-radius: 1px; }")
        lay.addWidget(bar)
        return card, title_icon, indicator, title_label, status_label, desc_scroll, desc_label, bar

    def ensure_probe_tiles(self, count):
        from core.translation import _t
        count = max(0, min(int(count or 0), 16))
        while len(self.probe_tiles) < count:
            idx = len(self.probe_tiles)
            tile = ProbeCpsTile(idx)
            self.probe_grid.addWidget(tile, idx // 4, idx % 4)
            self.probe_tiles.append(tile)
        for i, tile in enumerate(self.probe_tiles):
            visible = i < count
            tile.setVisible(visible)
            if visible:
                tile.set_name(_t("probe_slot_name", n=i + 1))

    def _debounce_online(self, slot: int, want_online: bool, cps: int, now: float) -> bool:
        """Keep tile green unless offline sustained > PROBE_OFFLINE_HOLD_SEC."""
        st = self._tile_hold.setdefault(slot, {"offline_since": None, "last": None})
        # CPS>0 时视为有活数据，避免 online_mask 抖一下就变灰
        if want_online or int(cps or 0) > 0:
            st["offline_since"] = None
            return True
        if st["offline_since"] is None:
            st["offline_since"] = now
            # 刚掉线：先保持上一帧在线观感
            if st.get("last") and st["last"][1]:
                return True
            return False
        if (now - float(st["offline_since"])) < PROBE_OFFLINE_HOLD_SEC:
            return True
        return False

    def update_probe_tiles_from_master(self, summary, master_online, lang="zh"):
        if summary is None:
            # 不要整页刷成「等待」灰色；有过数据则保留最后一帧
            if self._had_tile_data:
                return
            n = max(len(self.probe_tiles), 2)
            self.ensure_probe_tiles(n)
            for tile in self.probe_tiles:
                if tile.isVisible():
                    tile.update_tile(0, False, False, False, lang=lang, waiting=True)
            return

        now = time.time()
        n = summary.active_probe_count()
        self.ensure_probe_tiles(n)
        for i in range(n):
            cps = summary.probe_cps[i] if i < len(summary.probe_cps) else 0
            raw_online = bool(summary.online_mask & (1 << i))
            hit = bool(summary.hit_probe_mask & (1 << i))
            online = self._debounce_online(i, raw_online, cps, now)
            # 防抖期内仍用上一帧 CPS，避免数字跳成灰 0
            st = self._tile_hold[i]
            if not raw_online and online and st.get("last"):
                cps = st["last"][0]
                hit = st["last"][2]
            st["last"] = (int(cps), online, hit)
            self.probe_tiles[i].update_tile(cps, online, hit, master_online, lang=lang)
        self._had_tile_data = True

    def update_probe_tiles_from_probe_list(self, entries, lang="zh", show_as_primary=False):
        """
        Per-probe CPS from probe TCP spectrum.
        show_as_primary=True: treat as main display source (no '(probe)' suffix).
        """
        if not entries:
            # 保留上一帧，避免探头列表瞬时为空时整页变灰
            if self._had_tile_data:
                return
            n = max(len(self.probe_tiles), 1)
            self.ensure_probe_tiles(n)
            for tile in self.probe_tiles:
                if tile.isVisible():
                    tile.update_tile(0, False, False, False, lang=lang, waiting=True)
            return

        now = time.time()
        n = max(len(entries), 1)
        self.ensure_probe_tiles(n)
        for i, tile in enumerate(self.probe_tiles):
            if i >= n:
                tile.setVisible(False)
                continue
            tile.setVisible(True)
            e = entries[i]
            tile.set_name(e.get("name") or ("Probe %d" % (i + 1)))
            cps = int(e.get("cps", 0) or 0)
            raw_online = bool(e.get("online", True))
            hit = bool(e.get("hit", False))
            online = self._debounce_online(i, raw_online, cps, now)
            st = self._tile_hold[i]
            if not raw_online and online and st.get("last"):
                cps = st["last"][0]
                hit = st["last"][2]
            st["last"] = (cps, online, hit)
            tile.update_tile(
                cps, online, hit,
                master_online=bool(show_as_primary),
                lang=lang,
            )
        self._had_tile_data = True

    def set_master_link_status(self, online, master_id=None, lang="zh", link_only=False):
        """
        online=True  : valid L2 within timeout
        link_only=True: TCP/L2 header seen but no fresh valid summary
        """
        if online:
            mid = "#%s" % master_id if master_id is not None else ""
            text = ("Master: Online%s" % mid) if lang == "en" else ("\u4e3b\u63a7: \u5728\u7ebf%s" % mid)
            color = "#4caf50"
            bg = "rgba(76, 175, 80, 0.12)"
            border = "rgba(76, 175, 80, 0.35)"
        elif link_only:
            text = "Master: Linked (no L2)" if lang == "en" else "\u4e3b\u63a7: \u5df2\u8fde\u63a5(\u65e0L2)"
            color = "#ff9800"
            bg = "rgba(255, 152, 0, 0.12)"
            border = "rgba(255, 152, 0, 0.35)"
        else:
            text = "Master: Offline" if lang == "en" else "\u4e3b\u63a7: \u79bb\u7ebf"
            color = "#ff9800"
            bg = "rgba(255, 152, 0, 0.12)"
            border = "rgba(255, 152, 0, 0.35)"
        self.master_link_label.setText(text)
        self.master_link_label.setStyleSheet("""
            QLabel {
                color: %s; font-size: 12px; font-weight: bold;
                padding: 4px 10px; background-color: %s;
                border: 1px solid %s; border-radius: 8px;
            }
        """ % (color, bg, border))

    def retranslate_ui(self):
        from core.translation import _t
        self.title.setText(_t("home_title"))
        self.total_cps_caption.setText(_t("card_rad_title"))
        self.probe_section_title.setText(_t("probe_section_title"))
        for i, tile in enumerate(self.probe_tiles):
            tile.set_name(_t("probe_slot_name", n=i + 1))
        self.alarm_title_label.setText(_t("card_alarm_title"))
        self.occupancy_title_label.setText(_t("card_occ_title"))
        if hasattr(self, "channel_reset_btn"):
            self.channel_reset_btn.setText(_t("btn_channel_alarm_reset"))
