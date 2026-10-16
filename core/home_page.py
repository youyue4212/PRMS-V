#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Public home monitor page — WebEngine loads hmi_web/index.html (pixel-faithful HMI).
Python pushes live CPS/alarm/health via runJavaScript(applyHmiState).
"""

import json
import os
import time

from PyQt5.QtCore import Qt, QObject, QUrl, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QPushButton, QSizePolicy,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel

PROBE_OFFLINE_HOLD_SEC = 2.0

_HMI_HTML = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hmi_web", "index.html")
)


class _DummySvg(QLabel):
    """Stand-in for QSvgWidget so main_window .load() calls stay safe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()

    def load(self, *_args, **_kwargs):
        return True


class HmiBridge(QObject):
    """JS → Python callbacks."""

    reset_requested = pyqtSignal()
    health_requested = pyqtSignal()
    fault_requested = pyqtSignal()
    probe_requested = pyqtSignal(int, str)
    login_requested = pyqtSignal()
    page_ready = pyqtSignal()
    language_requested = pyqtSignal()
    reorder_requested = pyqtSignal(int, int)

    @pyqtSlot()
    def requestReset(self):
        self.reset_requested.emit()

    @pyqtSlot()
    def openHealth(self):
        self.health_requested.emit()

    @pyqtSlot()
    def openFault(self):
        self.fault_requested.emit()

    @pyqtSlot(int, str)
    def openProbe(self, index, client_id):
        self.probe_requested.emit(int(index), client_id or "")

    @pyqtSlot()
    def requestLogin(self):
        self.login_requested.emit()

    @pyqtSlot()
    def pageReady(self):
        self.page_ready.emit()

    @pyqtSlot()
    def toggleLanguage(self):
        self.language_requested.emit()

    @pyqtSlot(int, int)
    def reorderProbes(self, from_index, to_index):
        self.reorder_requested.emit(int(from_index), int(to_index))


class HomePage(QWidget):
    """Web HMI home; keeps stub widgets for main_window compatibility.

    headless=True：仅保留数据桩（主控室模式），不创建 QWebEngineView。
    """

    def __init__(self, parent=None, headless=False):
        super().__init__(parent)
        self.parent = parent
        self.headless = bool(headless)
        self.probe_tiles = []  # unused; kept for isinstance checks
        self._tile_hold = {}
        self._had_tile_data = False
        self._web_ready = False
        self._pending_state = {}
        self._probe_entries = []
        self._reset_alarm_active = False
        self._reset_enabled = False
        self._alarm_kind = "normal"
        self._alarm_latch_text = ""
        self._alarm_clear_mode_latch = False
        self._health_rows = {}
        self._fault_rows = {}
        self._passage_busy = False
        self._occupancy_kind = "noconn"
        self._flush_pending = False
        self._last_web_payload = None
        self._defer_flush_until = 0.0
        self._battery_cache = ("--%", 0.0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Hidden stubs so existing main_window attribute access keeps working
        self._stubs = QWidget(self)
        self._stubs.hide()
        self._stubs.setFixedSize(0, 0)
        self._build_stubs()

        self.browser = None
        self.bridge = None
        self.channel = None
        if not self.headless:
            self.browser = QWebEngineView(self)
            self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.browser.setAttribute(Qt.WA_OpaquePaintEvent, True)
            try:
                st = self.browser.settings()
                st.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, False)
                st.setAttribute(QWebEngineSettings.PluginsEnabled, False)
                st.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
                st.setAttribute(QWebEngineSettings.ErrorPageEnabled, False)
            except Exception:
                pass
            root.addWidget(self.browser, 1)

            self.bridge = HmiBridge(self)
            self.channel = QWebChannel(self)
            self.channel.registerObject("bridge", self.bridge)
            self.browser.page().setWebChannel(self.channel)

            self.bridge.page_ready.connect(self._on_page_ready)
            self.bridge.reset_requested.connect(self._on_js_reset)
            self.bridge.health_requested.connect(self._on_js_health)
            self.bridge.fault_requested.connect(lambda: self._nav(3))
            self.bridge.probe_requested.connect(self._on_js_probe)
            self.bridge.login_requested.connect(self._on_js_login)
            self.bridge.language_requested.connect(self._on_js_language)
            self.bridge.reorder_requested.connect(self._on_js_reorder)

            url = QUrl.fromLocalFile(_HMI_HTML.replace("\\", "/"))
            try:
                with open(_HMI_HTML, "r", encoding="utf-8") as f:
                    html = f.read()
                self.browser.setHtml(html, url)
            except Exception:
                self.browser.setUrl(url)

            self._flush_timer = QTimer(self)
            self._flush_timer.setSingleShot(True)
            self._flush_timer.timeout.connect(self._flush_to_web)

            self._tools_timer = QTimer(self)
            self._tools_timer.timeout.connect(self.schedule_web_flush)
            self._tools_timer.start(10000)
        else:
            self._flush_timer = QTimer(self)
            self._flush_timer.setSingleShot(True)
            self._tools_timer = QTimer(self)

        _install_label_hooks(self)
        _install_reset_enable_hook(self)

    # ---- stubs ----
    def _build_stubs(self):
        self.title = QLabel("行人通道辐射监测系统", self._stubs)
        self.mode_badge = QLabel("", self._stubs)
        self.total_cps_caption = QLabel("", self._stubs)
        self.total_cps_label = QLabel("0", self._stubs)
        self.master_relay_label = QLabel("--", self._stubs)
        self.master_link_label = QLabel("未接入主控", self._stubs)
        self.probe_section_title = QLabel("", self._stubs)

        self.alarm_card = QFrame(self._stubs)
        self.alarm_title_icon = _DummySvg(self._stubs)
        self.alarm_indicator = _DummySvg(self._stubs)
        self.alarm_title_label = QLabel("报警状态", self._stubs)
        self.alarm_status_label = QLabel("通道辐射状态正常", self._stubs)
        self.alarm_desc_label = QLabel("", self._stubs)
        self.alarm_desc_scroll = QWidget(self._stubs)
        self.status_indicator_bar = QFrame(self._stubs)

        self.occupancy_card = QFrame(self._stubs)
        self.occupancy_title_icon = _DummySvg(self._stubs)
        self.occupancy_indicator = _DummySvg(self._stubs)
        self.occupancy_title_label = QLabel("", self._stubs)
        self.occupancy_status_label = QLabel("未接入主控", self._stubs)
        self.occupancy_desc_label = QLabel("", self._stubs)
        self.occupancy_desc_scroll = QWidget(self._stubs)
        self.occupancy_indicator_bar = QFrame(self._stubs)

        self.health_card = QFrame(self._stubs)
        self.health_title_icon = _DummySvg(self._stubs)
        self.health_indicator = _DummySvg(self._stubs)
        self.health_title_label = QLabel("设备健康", self._stubs)
        self.health_status_label = QLabel("待接入设备", self._stubs)
        self.health_desc_label = QLabel("", self._stubs)
        self.health_desc_scroll = QWidget(self._stubs)
        self.health_indicator_bar = QFrame(self._stubs)

        self.fault_card = QFrame(self._stubs)
        self.fault_title_icon = _DummySvg(self._stubs)
        self.fault_indicator = _DummySvg(self._stubs)
        self.fault_title_label = QLabel("故障摘要", self._stubs)
        self.fault_status_label = QLabel("无活动故障", self._stubs)
        self.fault_desc_label = QLabel("", self._stubs)
        self.fault_desc_scroll = QWidget(self._stubs)
        self.fault_indicator_bar = QFrame(self._stubs)

        self.side_rad_stat = QLabel("全组正常", self._stubs)
        self.alarm_latch_status = QLabel("无锁存", self._stubs)
        self.side_header_tag = QLabel("● 正常", self._stubs)

        self.channel_reset_btn = QPushButton("通道报警复位", self._stubs)
        self.channel_reset_btn.setEnabled(False)
        self.channel_reset_btn.hide()

    def _web_page_visible(self):
        if self.headless or self.browser is None:
            return False
        return bool(self.isVisible())

    def note_user_input(self):
        """Postpone JS push so a click is not queued behind applyHmiState."""
        if self.headless:
            return
        # 换语推送窗口内禁止 defer，避免冲掉刚推上的新语种
        if time.monotonic() < float(getattr(self, "_language_flush_until", 0.0) or 0.0):
            return
        self._defer_flush_until = time.monotonic() + 0.16
        if self._web_page_visible():
            self._flush_timer.start(180)

    def schedule_web_flush(self, immediate=False):
        if self.headless:
            return
        if immediate:
            self._flush_pending = False
            self._flush_timer.stop()
            self._flush_to_web(force=False)
            return
        if not self._web_page_visible():
            self._flush_pending = True
            return
        delay_ms = 220
        remain = self._defer_flush_until - time.monotonic()
        if remain > 0:
            delay_ms = max(delay_ms, int(remain * 1000) + 40)
            self._flush_timer.start(delay_ms)
            return
        if not self._flush_timer.isActive():
            self._flush_timer.start(delay_ms)

    def showEvent(self, event):
        super().showEvent(event)
        # 仅补推藏页期间积压的状态；已在当前页时由调用方决定是否 immediate
        if self._flush_pending:
            self._flush_pending = False
            self.force_web_flush()

    def _on_page_ready(self):
        self._web_ready = True
        self._last_web_payload = None
        self._flush_to_web()

    def _nav(self, page_index):
        parent = self.parent
        if parent is None or not hasattr(parent, "switch_page"):
            return
        parent.switch_page(page_index)

    def _on_js_health(self):
        parent = self.parent
        if parent is not None and hasattr(parent, "open_health_or_commissioning"):
            parent.open_health_or_commissioning()
            return
        self._nav(3)

    def _on_js_reset(self):
        # 触发 main_window 已连接的 clicked 槽（二次确认 + 0x15）
        self.channel_reset_btn.click()

    def _on_js_probe(self, index, client_id):
        parent = self.parent
        if parent is None:
            return
        if hasattr(parent, "is_logged_in") and not parent.is_logged_in():
            return
        cid = client_id or None
        if hasattr(parent, "open_probe_overview"):
            parent.open_probe_overview(cid, slot_index=index)

    def _on_js_login(self):
        if self.parent is not None and hasattr(self.parent, "login"):
            # Stay on home after login so card navigation becomes active there
            self.parent.login(preferred_page=0)
            self.schedule_web_flush(immediate=True)

    def _on_js_reorder(self, from_index, to_index):
        """Swap two home probe slots (data order + location labels) and persist."""
        a = int(from_index)
        b = int(to_index)
        n = len(self._probe_entries)
        if a == b or a < 0 or b < 0 or a >= n or b >= n:
            return
        parent = self.parent
        # Require login for layout edits
        if parent is not None and hasattr(parent, "is_logged_in") and not parent.is_logged_in():
            return

        # Ensure every card has a stable identity before swap (placeholders included)
        for i, e in enumerate(self._probe_entries):
            if e.get("slot_id") is None:
                e["slot_id"] = i
            if not str(e.get("location") or "").strip():
                e["location"] = self._slot_location(i)

        entries = list(self._probe_entries)
        entries[a], entries[b] = entries[b], entries[a]
        self._probe_entries = entries

        # Persist identity order (client_id or stable slot_id — never display index)
        order = [self._entry_order_key(e, i) for i, e in enumerate(self._probe_entries)]
        cfg = getattr(parent, "config", None) if parent is not None else None
        if cfg is not None and hasattr(cfg, "set_probe_display_order"):
            cfg.set_probe_display_order(order)
            cfg.save_settings()

        # Location tags travel with the card (entry field), then sync to config by display slot
        locs = []
        for i, e in enumerate(self._probe_entries):
            loc = str(e.get("location") or "").strip()
            if not loc:
                loc = self._slot_location(i)
                e["location"] = loc
            locs.append(loc)
        if cfg is not None and hasattr(cfg, "set_probe_slot_locations"):
            cfg.set_probe_slot_locations(locs)
            cfg.save_settings()

        # Refresh settings page edits if present
        if parent is not None and hasattr(parent, "refresh_probe_location_edits"):
            try:
                parent.refresh_probe_location_edits()
            except Exception:
                pass

        self.schedule_web_flush(immediate=True)

    def _on_js_language(self):
        # 离开 Web 点击回调再切语言，否则当帧 runJavaScript 常被吃掉
        QTimer.singleShot(0, self._apply_language_toggle_from_web)

    def _apply_language_toggle_from_web(self):
        if self.parent is not None and hasattr(self.parent, "status_bar"):
            sb = self.parent.status_bar
            if hasattr(sb, "toggle_language"):
                sb.toggle_language()
                return
        try:
            from core.translation import TranslationManager
            tm = TranslationManager()
            new_lang = "en" if tm.get_language() == "zh" else "zh"
            tm.set_language(new_lang)
            if self.parent is not None and hasattr(self.parent, "on_language_changed"):
                self.parent.on_language_changed(new_lang)
                return
        except Exception:
            pass
        self.schedule_language_web_flush()

    # ---- state → JS ----

    def _probe_name(self, i):
        try:
            from core.translation import _t
            return _t("probe_slot_name", n=i + 1)
        except Exception:
            return "Probe %d" % (i + 1)

    def _live_probe_name(self, i, entry=None):
        """Always resolve name in current UI language (never keep stale zh cache)."""
        entry = entry or {}
        cid = entry.get("client_id")
        if cid and self.parent is not None and hasattr(self.parent, "get_probe_label"):
            try:
                label = self.parent.get_probe_label(cid)
                if label:
                    return label
            except Exception:
                pass
        # Drag-reorder moves the card identity; name must follow slot_id, not display index
        sid = entry.get("slot_id")
        try:
            sid = int(sid) if sid is not None else int(i)
        except (TypeError, ValueError):
            sid = int(i)
        return self._probe_name(sid)

    def _entry_order_key(self, entry, display_index=0):
        cid = (entry or {}).get("client_id")
        if cid is not None and str(cid).strip():
            return str(cid).strip()
        sid = (entry or {}).get("slot_id")
        try:
            sid = int(sid) if sid is not None else int(display_index)
        except (TypeError, ValueError):
            sid = int(display_index)
        return "slot:%d" % sid

    def _apply_saved_display_order(self):
        """Reorder _probe_entries by persisted probe_display_order."""
        cfg = getattr(self.parent, "config", None) if self.parent is not None else None
        order = list(getattr(cfg, "probe_display_order", None) or []) if cfg is not None else []
        if not order or not self._probe_entries:
            return
        keyed = []
        for i, e in enumerate(self._probe_entries):
            if e.get("slot_id") is None:
                e["slot_id"] = i
            keyed.append((self._entry_order_key(e, i), e))
        by_key = {}
        for k, e in keyed:
            if k not in by_key:
                by_key[k] = e
        new_list = []
        used = set()
        for key in order:
            e = by_key.get(str(key).strip())
            if e is not None and id(e) not in used:
                new_list.append(e)
                used.add(id(e))
        for _, e in keyed:
            if id(e) not in used:
                new_list.append(e)
                used.add(id(e))
        if len(new_list) == len(self._probe_entries):
            self._probe_entries = new_list

    def _mode_label(self):
        from core.translation import _t
        parent = self.parent
        user = getattr(parent, "current_user", None) if parent is not None else None
        if user and isinstance(user, dict):
            role = user.get("role")
            role_val = getattr(role, "value", None) or str(role)
            if "maintainer" in str(role_val).lower():
                return _t("mode_maintainer")
            if "admin" in str(role_val).lower():
                return _t("mode_admin")
            return _t("mode_viewer")
        return _t("mode_monitor")

    def _ui_strings(self):
        from core.translation import _t
        return {
            "title": _t("home_title_full"),
            "titleTip": _t("tip_title_login"),
            "mode": self._mode_label(),
            "totalCpsLabel": _t("card_rad_title_channel"),
            "probeSection": _t("probe_section_title_cps"),
            "resetTitle": _t("card_reset_control_title"),
            "radStatus": _t("label_rad_status"),
            "alarmLatch": _t("label_alarm_latch"),
            "resetBtn": _t("btn_channel_alarm_reset"),
            "resetBtnActive": _t("btn_channel_alarm_reset_active"),
            "sideTagOk": _t("side_tag_ok"),
            "sideTagAlarm": _t("side_tag_alarm"),
            "sideTagOffline": _t("side_tag_offline"),
            "sideTagWarn": _t("side_tag_warn"),
            "latchNone": _t("latch_none"),
            "latchPending": _t("latch_pending", n=1),
            "latchAutoHold": _t("latch_auto_hold"),
            "latchModeAuto": _t("latch_mode_auto"),
            "latchModeLatch": _t("latch_mode_latch"),
            "healthTitle": _t("card_health_title"),
            "faultTitle": _t("card_fault_summary_title"),
            "tipHealth": _t("tip_health_card_nav"),
            "tipFault": _t("tip_fault_card_nav"),
            "kvProbeComm": _t("kv_probe_comm"),
            "kvIrStatus": _t("kv_ir_status"),
            "kvMasterHw": _t("kv_master_hw"),
            "kvLastFault": _t("kv_last_fault"),
            "clickDetail": _t("btn_click_detail"),
            "probeOk": _t("probe_tile_ok"),
            "probeAlarm": _t("probe_tile_alarm"),
            "probeOffline": _t("probe_tile_offline"),
            "groupOk": _t("status_group_ok"),
            "vacant": _t("status_vacant"),
            "passing": _t("status_passing"),
            "occupiedAlarm": _t("status_occupied_alarm"),
            "noMaster": _t("status_occ_no_master"),
        }

    def _slot_location(self, i):
        """Slot position label: config override > translation default."""
        saved = ""
        try:
            cfg = getattr(self.parent, "config", None) if self.parent is not None else None
            locs = list(getattr(cfg, "probe_slot_locations", None) or [])
            if i < len(locs):
                saved = str(locs[i] or "").strip()
        except Exception:
            saved = ""
        try:
            from core.translation import localize_probe_location
            return localize_probe_location(saved, i)
        except Exception:
            from core.translation import default_probe_location
            return default_probe_location(i)

    def sync_probe_slot_locations(self, immediate=True):
        """Rewrite cached card locations from Settings (stop old/new label flicker)."""
        for i, e in enumerate(self._probe_entries):
            e["location"] = self._slot_location(i)
        self.schedule_web_flush(immediate=immediate)

    def _link_level(self):
        t = self.master_link_label.text()
        if "未接入" in t or "No Master" in t:
            return "offline"
        if "离线" in t or "Offline" in t:
            return "offline"
        if "等待数据" in t or "awaiting" in t.lower() or "无L2" in t or "Linked" in t or "降级" in t:
            return "warn"
        return "ok"

    def _alarm_web_kind(self):
        if self._alarm_kind == "channel_alarm":
            return "alarm"
        if self._alarm_kind == "offline":
            return "offline"
        if self._alarm_kind in ("over_threshold", "soft_cleared", "fault", "acked", "warn"):
            return "warn"
        return "normal"

    def radiation_side_rad(self):
        """辐射状态与右上角标签同一套 kind，禁止离线时仍写「系统正常」。"""
        from core.translation import _t
        kind = self._alarm_web_kind()
        title = self.alarm_status_label.text() or ""
        if kind == "offline":
            return _t("status_rad_offline")
        if kind == "normal":
            return _t("status_group_ok")
        return title or _t("status_group_ok")

    def radiation_banner_title(self):
        from core.translation import _t
        kind = self._alarm_web_kind()
        title = self.alarm_status_label.text() or ""
        if kind == "offline":
            return _t("status_rad_offline")
        if kind == "normal":
            return title or _t("status_normal")
        return title or _t("status_normal")

    def radiation_side_tag(self):
        """Alarm-card top-right tag: radiation decision, not device health."""
        from core.translation import _t
        kind = self._alarm_web_kind()
        if kind == "alarm":
            return _t("side_tag_alarm"), "#FF4D4D"
        if kind == "offline":
            return _t("side_tag_offline"), "#ff9800"
        if kind == "warn":
            return _t("side_tag_warn"), "#ff9800"
        return _t("side_tag_ok"), "#4caf50"

    def set_alarm_kind(self, kind: str):
        self._alarm_kind = str(kind or "normal")
        self.schedule_web_flush()

    def build_hmi_state(self):
        probes = []
        for i, e in enumerate(self._probe_entries):
            probes.append({
                # name 跟卡片身份；location 始终跟设置页槽位标签（避免两路刷新来回跳）
                "name": self._live_probe_name(i, e),
                "location": self._slot_location(i),
                "cps": int(e.get("cps", 0) or 0),
                "threshold": int(e.get("threshold", 1000) or 1000),
                "isAlarm": bool(e.get("hit", False)),
                "online": bool(e.get("online", True)),
                "clientId": e.get("client_id") or "",
            })
        if not probes and not self._had_tile_data:
            n = self._expected_placeholder_count()
            probes = [
                {
                    "name": self._live_probe_name(i),
                    "location": self._slot_location(i),
                    "cps": 0,
                    "threshold": 1000,
                    "isAlarm": False,
                    "online": False,
                    "clientId": "",
                }
                for i in range(n)
            ]

        total_txt = self.total_cps_label.text().replace(" cps", "").replace("CPS", "").strip()
        try:
            total = int(float(total_txt)) if total_txt else 0
        except Exception:
            total = sum(p["cps"] for p in probes)

        health_color = "#4caf50"
        health_warn = False
        hs = self.health_status_label.text()
        hs_l = hs.lower()
        # Card/tag yellow only for degraded/fault — not mere master offline / awaiting
        # (offline stays green tag; amber only on the Master HW row).
        if (
            "降级" in hs
            or "通信故障" in hs
            or ("故障" in hs and "无" not in hs)
            or "degrad" in hs_l
            or "link fault" in hs_l
            or ("fault" in hs_l and "no " not in hs_l and "offline" not in hs_l and "await" not in hs_l)
        ):
            health_color = "#ff9800"
            health_warn = True
        elif "待接入" in hs or "await" in hs_l:
            health_color = "#9e9e9e"
            health_warn = False
        elif "离线" in hs or "offline" in hs_l:
            health_color = "#4caf50"
            health_warn = False

        fault_color = "#4caf50"
        fault_warn = False
        fs = self.fault_status_label.text()
        if "故障" in fs and "无" not in fs and "0" not in fs:
            fault_color = "#ff9800"
            fault_warn = True
        elif "活动" in fs and not fs.strip().startswith("0"):
            fault_color = "#ff9800"
            fault_warn = True

        return {
            "totalCps": total,
            "masterLink": {
                "text": self.master_link_label.text(),
                "level": self._link_level(),
            },
            "probes": probes,
            "alarm": {
                "kind": self._alarm_web_kind(),
                "title": self.radiation_banner_title(),
                "desc": self.alarm_desc_label.text(),
                "sideRad": self.radiation_side_rad(),
                "sideTag": self.radiation_side_tag()[0],
                "sideTagColor": self.radiation_side_tag()[1],
                "latched": bool(self._reset_alarm_active),
                "latchText": getattr(self, "_alarm_latch_text", None)
                or self.alarm_latch_status.text()
                or "",
                "clearModeLatch": bool(getattr(self, "_alarm_clear_mode_latch", False)),
                "resetEnabled": bool(self._reset_enabled),
            },
            "passage": {
                "kind": getattr(self, "_occupancy_kind", None) or (
                    "passing" if self._passage_busy else "vacant"
                ),
                "busy": bool(self._passage_busy),
                "text": self.occupancy_status_label.text(),
            },
            "health": {
                "status": self.health_status_label.text(),
                "desc": self.health_desc_label.text(),
                "color": health_color,
                "warn": health_warn,
                "rows": getattr(self, "_health_rows", None) or {},
            },
            "fault": {
                "status": self.fault_status_label.text(),
                "desc": self.fault_desc_label.text(),
                "color": fault_color,
                "warn": fault_warn,
                "rows": getattr(self, "_fault_rows", None) or {},
            },
            "battery": self._battery_text(),
            "langLabel": self._lang_btn_label(),
            "modeLabel": self._mode_label(),
            "lang": self._ui_lang(),
            "ui": self._ui_strings(),
            "canNavigate": self._can_navigate(),
            "canOpenAlarmLog": True,
            "canReorder": self._can_navigate(),
        }

    def _can_navigate(self):
        parent = self.parent
        if parent is None:
            return False
        if hasattr(parent, "is_logged_in"):
            return bool(parent.is_logged_in())
        return bool(getattr(parent, "current_user", None))

    def _ui_lang(self):
        try:
            from core.translation import TranslationManager
            return TranslationManager().get_language()
        except Exception:
            return "zh"

    def _lang_btn_label(self):
        return "EN" if self._ui_lang() == "zh" else "中文"

    def _battery_text(self):
        now = time.monotonic()
        cached, ts = self._battery_cache
        if now - ts < 15.0:
            return cached
        try:
            from core.utils import get_battery_percentage
            level, _plugged = get_battery_percentage()
            if level is None:
                text = "--%"
            else:
                text = "%d%%" % int(level)
        except Exception:
            text = "--%"
        self._battery_cache = (text, now)
        return text

    def _flush_to_web(self, force=False):
        if self.headless or self.browser is None:
            return
        if not self._web_ready:
            self._flush_pending = True
            return
        state = self.build_hmi_state()
        # 换语时带 nonce，避免 Web/去重层把「同内容」当成无更新
        if force:
            state = dict(state)
            state["_langNonce"] = time.monotonic()
        payload = json.dumps(state, ensure_ascii=False)
        if not force and payload == self._last_web_payload:
            return
        self._last_web_payload = payload
        # setTimeout：避开与输入事件同栈时 WebEngine 丢弃脚本的问题
        js = (
            "(function(){ var s=%s; "
            "setTimeout(function(){ if (window.applyHmiState) applyHmiState(s); }, 0); "
            "})();"
        ) % payload
        try:
            self.browser.page().runJavaScript(js)
        except Exception:
            self._flush_pending = True

    def push_web_language_chrome(self):
        """只推静态 UI 文案+语言按钮，体积小、优先保证顶栏/标题立刻换语。"""
        if self.headless or self.browser is None or not self._web_ready:
            return
        patch = {
            "ui": self._ui_strings(),
            "langLabel": self._lang_btn_label(),
            "modeLabel": self._mode_label(),
            "lang": self._ui_lang(),
            "_langNonce": time.monotonic(),
        }
        body = json.dumps(patch, ensure_ascii=False)
        js = (
            "(function(){ var s=%s; "
            "setTimeout(function(){ if (window.applyHmiState) applyHmiState(s); }, 0); "
            "})();"
        ) % body
        try:
            self.browser.page().runJavaScript(js)
        except Exception:
            pass

    def force_web_flush(self):
        """Push HMI state even if payload unchanged (language switch / page return)."""
        if self.headless or self.browser is None:
            return
        self._defer_flush_until = 0.0
        self._flush_pending = False
        if hasattr(self, "_flush_timer"):
            self._flush_timer.stop()
        self._last_web_payload = None
        self._flush_to_web(force=True)

    def schedule_language_web_flush(self):
        """Language click races WebEngine JS; re-push after the click event settles."""
        if self.headless or self.browser is None:
            return
        self._language_flush_until = time.monotonic() + 0.6
        self.push_web_language_chrome()
        self.force_web_flush()
        # 点击当帧/随后几帧的 runJavaScript 常被吃掉；分拍再推
        QTimer.singleShot(0, self._language_flush_tick)
        QTimer.singleShot(80, self._language_flush_tick)
        QTimer.singleShot(200, self._language_flush_tick)

    def _language_flush_tick(self):
        self.push_web_language_chrome()
        self.force_web_flush()

    def reorder_probes(self, from_index, to_index):
        """Public API for control-room drag reorder (same as Web HMI)."""
        self._on_js_reorder(from_index, to_index)

    # ---- API used by main_window ----
    def _expected_placeholder_count(self):
        """Empty-load tile count follows Settings → expected_probe_count."""
        try:
            cfg = getattr(self.parent, "config", None) if self.parent is not None else None
            n = int(getattr(cfg, "expected_probe_count", 2) or 0) if cfg is not None else 2
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            n = 2
        return max(1, min(n, 16))

    def _apply_empty_probe_placeholders(self):
        """Show offline placeholder tiles (no TCP probes yet)."""
        n = self._expected_placeholder_count()
        self.ensure_probe_tiles(n)
        self._apply_saved_display_order()
        for i, e in enumerate(self._probe_entries):
            if e.get("slot_id") is None:
                e["slot_id"] = i
            e["location"] = self._slot_location(i)
            e["cps"] = 0
            e["online"] = False
            e["hit"] = False
        self.schedule_web_flush()

    def ensure_probe_tiles(self, count):
        count = max(0, min(int(count or 0), 16))
        while len(self._probe_entries) < count:
            i = len(self._probe_entries)
            self._probe_entries.append({
                "name": self._probe_name(i),
                "location": self._slot_location(i),
                "cps": 0, "online": False, "hit": False, "client_id": None,
                "threshold": 1000,
                "slot_id": i,
            })
        self._probe_entries = self._probe_entries[:count]

    def on_probe_tile_clicked(self, slot_index, client_id=None):
        if self.parent is not None and hasattr(self.parent, "open_probe_overview"):
            self.parent.open_probe_overview(client_id, slot_index=slot_index)

    def _debounce_online(self, slot: int, want_online: bool, cps: int, now: float) -> bool:
        st = self._tile_hold.setdefault(slot, {"offline_since": None, "last": None})
        if want_online or int(cps or 0) > 0:
            st["offline_since"] = None
            return True
        if st["offline_since"] is None:
            st["offline_since"] = now
            if st.get("last") and st["last"][1]:
                return True
            return False
        if (now - float(st["offline_since"])) < PROBE_OFFLINE_HOLD_SEC:
            return True
        return False

    def update_probe_tiles_from_master(self, summary, master_online, lang="zh"):
        if summary is None:
            if self._had_tile_data:
                return
            self._apply_empty_probe_placeholders()
            return

        now = time.time()
        n = summary.active_probe_count()
        self.ensure_probe_tiles(n)
        for i in range(n):
            cps = summary.probe_cps[i] if i < len(summary.probe_cps) else 0
            raw_online = bool(summary.online_mask & (1 << i))
            hit = bool(summary.hit_probe_mask & (1 << i))
            online = self._debounce_online(i, raw_online, cps, now)
            st = self._tile_hold[i]
            if not raw_online and online and st.get("last"):
                cps = st["last"][0]
                hit = st["last"][2]
            st["last"] = (int(cps), online, hit)
            self._probe_entries[i].update({
                "cps": int(cps), "online": online, "hit": hit,
                "name": self._live_probe_name(i, self._probe_entries[i]),
                "location": self._slot_location(i),
            })
        self._had_tile_data = True
        self.schedule_web_flush()

    def update_probe_tiles_from_probe_list(self, entries, lang="zh", show_as_primary=False):
        if not entries:
            if self._had_tile_data:
                return
            self._apply_empty_probe_placeholders()
            return

        now = time.time()
        n = max(len(entries), 1)
        # Keep prior identities so reorder (slot_id) survives CPS refresh
        prev_by_cid = {}
        for pe in self._probe_entries:
            cid = pe.get("client_id")
            if cid is not None and str(cid).strip():
                prev_by_cid[str(cid).strip()] = pe

        self.ensure_probe_tiles(n)
        self._probe_entries = self._probe_entries[:n]
        for i in range(n):
            e = entries[i]
            cps = int(e.get("cps", 0) or 0)
            raw_online = bool(e.get("online", True))
            hit = bool(e.get("hit", False))
            online = self._debounce_online(i, raw_online, cps, now)
            st = self._tile_hold[i]
            if not raw_online and online and st.get("last"):
                cps = st["last"][0]
                hit = st["last"][2]
            st["last"] = (cps, online, hit)
            cid = e.get("client_id")
            prev = prev_by_cid.get(str(cid).strip()) if cid is not None and str(cid).strip() else None
            slot_id = prev.get("slot_id") if prev else None
            if slot_id is None:
                slot_id = i
            self._probe_entries[i] = {
                "name": self._live_probe_name(i, {
                    "client_id": cid,
                    "slot_id": slot_id,
                    "name": e.get("name"),
                }),
                "location": self._slot_location(i),
                "cps": cps,
                "online": online,
                "hit": hit,
                "client_id": cid,
                "threshold": int(e.get("threshold", 1000) or 1000),
                "slot_id": slot_id,
            }
        self._had_tile_data = True
        self.schedule_web_flush()

    def set_master_link_status(self, online, master_id=None, lang="zh", link_only=False, never_seen=False):
        if online:
            text = "Master Online" if lang == "en" else "主控在线"
        elif never_seen:
            text = "No Master Link" if lang == "en" else "未接入主控"
        elif link_only:
            text = "Master Linked (awaiting data)" if lang == "en" else "主控已连接(等待数据)"
        else:
            text = "Master Offline" if lang == "en" else "主控离线"
        self.master_link_label.setText(text)
        self.schedule_web_flush()

    def set_channel_reset_alarm_active(self, active: bool):
        self._reset_alarm_active = bool(active)
        if active:
            self._alarm_kind = "channel_alarm"
        elif self._alarm_kind == "channel_alarm":
            self._alarm_kind = "normal"
        self.schedule_web_flush()

    def sync_side_rad_from_alarm(self, status_text: str, alarm: bool):
        self.side_rad_stat.setText(status_text or "")
        self.schedule_web_flush()

    def apply_alarm_banner_style(self, color=None):
        if color in ("#ff4444", "#EF4444"):
            self._alarm_kind = "channel_alarm"
        elif color is None:
            # 正常：必须清掉 offline/warn，否则会「系统正常 + 黄叹号」
            self._alarm_kind = "normal"
        else:
            if self._alarm_kind not in ("offline", "over_threshold", "soft_cleared", "fault", "acked"):
                self._alarm_kind = "warn"
        self.schedule_web_flush()

    def apply_aux_card_style(self, card, bar, color=None):
        self.schedule_web_flush()

    def apply_status_label_style(self, label, color, _bg=None, _border=None):
        if label is self.occupancy_status_label:
            c = str(color or "").lower()
            if c in ("#ff4444", "#ef4444"):
                self._occupancy_kind = "alarm"
                self._passage_busy = True
            elif c in ("#2196f3",):
                self._occupancy_kind = "passing"
                self._passage_busy = True
            elif c in ("#ff9800", "#f59e0b", "#ffb74d"):
                # offline / ungated（门控未配置）统一偏黄
                self._occupancy_kind = "ungated" if c == "#ffb74d" else "offline"
                self._passage_busy = False
            else:
                self._occupancy_kind = "vacant"
                self._passage_busy = False
        self.schedule_web_flush()

    def set_header_alarm(self, active: bool):
        self._alarm_kind = "channel_alarm" if active else "normal"
        self.schedule_web_flush()

    def retranslate_ui(self):
        from core.translation import _t
        self.title.setText(_t("home_title_full"))
        self.channel_reset_btn.setText(_t("btn_channel_alarm_reset"))
        # 切语言后刷新探头名/位置；Web 推送留给 on_language_changed 重建动态文案后再 force
        for i, e in enumerate(self._probe_entries):
            e["name"] = self._live_probe_name(i, e)
            e["location"] = self._slot_location(i)


def _install_label_hooks(page: "HomePage"):
    labels = (
        page.total_cps_label, page.alarm_status_label, page.alarm_desc_label,
        page.occupancy_status_label, page.health_status_label, page.health_desc_label,
        page.fault_status_label, page.fault_desc_label, page.side_rad_stat,
        page.master_link_label,
    )
    for lab in labels:
        orig = lab.setText

        def _make(o=orig, p=page):
            def _set(text):
                o(text)
                p.schedule_web_flush()
            return _set

        lab.setText = _make()  # type: ignore[method-assign]


def _install_reset_enable_hook(page: "HomePage"):
    btn = page.channel_reset_btn
    orig = btn.setEnabled

    def _set(enabled):
        orig(bool(enabled))
        page._reset_enabled = bool(enabled)
        page.schedule_web_flush()

    btn.setEnabled = _set  # type: ignore[method-assign]
