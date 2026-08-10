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
from PyQt5.QtWebEngineWidgets import QWebEngineView
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
    """Web HMI home; keeps stub widgets for main_window compatibility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.browser = QWebEngineView(self)
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.browser, 1)

        # Hidden stubs so existing main_window attribute access keeps working
        self._stubs = QWidget(self)
        self._stubs.hide()
        self._stubs.setFixedSize(0, 0)
        self._build_stubs()

        self.bridge = HmiBridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.browser.page().setWebChannel(self.channel)

        self.bridge.page_ready.connect(self._on_page_ready)
        self.bridge.reset_requested.connect(self._on_js_reset)
        self.bridge.health_requested.connect(lambda: self._nav(3))
        self.bridge.fault_requested.connect(lambda: self._nav(4))
        self.bridge.probe_requested.connect(self._on_js_probe)
        self.bridge.login_requested.connect(self._on_js_login)
        self.bridge.language_requested.connect(self._on_js_language)
        self.bridge.reorder_requested.connect(self._on_js_reorder)

        url = QUrl.fromLocalFile(_HMI_HTML.replace("\\", "/"))
        # 强制按 UTF-8 读入再 setHtml，避免 Windows 下本地文件被当成系统编码导致乱码
        try:
            with open(_HMI_HTML, "r", encoding="utf-8") as f:
                html = f.read()
            self.browser.setHtml(html, url)
        except Exception:
            self.browser.setUrl(url)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_to_web)

        # 顶栏电池刷新
        self._tools_timer = QTimer(self)
        self._tools_timer.timeout.connect(self.schedule_web_flush)
        self._tools_timer.start(10000)

        _install_label_hooks(self)
        _install_reset_enable_hook(self)

    # ---- stubs ----
    def _build_stubs(self):
        self.title = QLabel("行人通道辐射监测系统", self._stubs)
        self.mode_badge = QLabel("", self._stubs)
        self.total_cps_caption = QLabel("", self._stubs)
        self.total_cps_label = QLabel("0", self._stubs)
        self.master_relay_label = QLabel("--", self._stubs)
        self.master_link_label = QLabel("主控离线", self._stubs)
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
        self.occupancy_status_label = QLabel("通道空闲", self._stubs)
        self.occupancy_desc_label = QLabel("", self._stubs)
        self.occupancy_desc_scroll = QWidget(self._stubs)
        self.occupancy_indicator_bar = QFrame(self._stubs)

        self.health_card = QFrame(self._stubs)
        self.health_title_icon = _DummySvg(self._stubs)
        self.health_indicator = _DummySvg(self._stubs)
        self.health_title_label = QLabel("设备健康", self._stubs)
        self.health_status_label = QLabel("设备正常", self._stubs)
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

    def schedule_web_flush(self):
        if not self._flush_timer.isActive():
            self._flush_timer.start(50)

    def _on_page_ready(self):
        self._web_ready = True
        self._flush_to_web()

    def _nav(self, page_index):
        parent = self.parent
        if parent is None or not hasattr(parent, "switch_page"):
            return
        # Public monitor: card taps must not navigate / prompt login
        if hasattr(parent, "is_logged_in") and not parent.is_logged_in():
            return
        parent.switch_page(page_index)

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
            self.schedule_web_flush()

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

        entries = list(self._probe_entries)
        entries[a], entries[b] = entries[b], entries[a]
        self._probe_entries = entries

        # Persist client order
        order = []
        for i, e in enumerate(self._probe_entries):
            cid = e.get("client_id")
            order.append(str(cid).strip() if cid else ("slot:%d" % i))
        cfg = getattr(parent, "config", None) if parent is not None else None
        if cfg is not None and hasattr(cfg, "set_probe_display_order"):
            cfg.set_probe_display_order(order)
            cfg.save_settings()

        # Swap location labels so the whole card (including tag) moves
        locs = [self._slot_location(i) for i in range(n)]
        locs[a], locs[b] = locs[b], locs[a]
        if cfg is not None and hasattr(cfg, "set_probe_slot_locations"):
            cfg.set_probe_slot_locations(locs)
            cfg.save_settings()

        # Refresh settings page edits if present
        if parent is not None and hasattr(parent, "refresh_probe_location_edits"):
            try:
                parent.refresh_probe_location_edits()
            except Exception:
                pass

        self.schedule_web_flush()

    def _on_js_language(self):
        if self.parent is not None and hasattr(self.parent, "status_bar"):
            sb = self.parent.status_bar
            if hasattr(sb, "toggle_language"):
                sb.toggle_language()
                self.schedule_web_flush()
                return
        # fallback
        try:
            from core.translation import TranslationManager
            tm = TranslationManager()
            new_lang = "en" if tm.get_language() == "zh" else "zh"
            tm.set_language(new_lang)
            if self.parent is not None and hasattr(self.parent, "on_language_changed"):
                self.parent.on_language_changed(new_lang)
        except Exception:
            pass
        self.schedule_web_flush()

    # ---- state → JS ----

    def _probe_name(self, i):
        try:
            from core.translation import _t
            return _t("probe_slot_name", n=i + 1)
        except Exception:
            return "Probe %d" % (i + 1)

    def _mode_label(self):
        from core.translation import _t
        parent = self.parent
        user = getattr(parent, "current_user", None) if parent is not None else None
        if user and isinstance(user, dict):
            role = user.get("role")
            role_val = getattr(role, "value", None) or str(role)
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
            "latchNone": _t("latch_none"),
            "latchPending": _t("latch_pending", n=1),
            "latchAutoHold": _t("latch_auto_hold"),
            "latchModeAuto": _t("latch_mode_auto"),
            "latchModeLatch": _t("latch_mode_latch"),
            "healthTitle": _t("card_health_title"),
            "faultTitle": _t("card_fault_summary_title"),
            "kvProbeComm": _t("kv_probe_comm"),
            "kvIrStatus": _t("kv_ir_status"),
            "kvMasterHw": _t("kv_master_hw"),
            "kvLastFault": _t("kv_last_fault"),
            "kvIrShield": _t("kv_ir_shield"),
            "clickDetail": _t("btn_click_detail"),
            "probeOk": _t("probe_tile_ok"),
            "probeAlarm": _t("probe_tile_alarm"),
            "probeOffline": _t("probe_tile_offline"),
            "groupOk": _t("status_group_ok"),
            "vacant": _t("status_vacant"),
            "passing": _t("status_passing"),
        }

    def _slot_location(self, i):
        """Slot position label: config override > translation default."""
        # 1) config.probe_slot_locations (settable)
        try:
            cfg = getattr(self.parent, "config", None) if self.parent is not None else None
            locs = list(getattr(cfg, "probe_slot_locations", None) or [])
            if i < len(locs) and str(locs[i]).strip():
                return str(locs[i]).strip()
        except Exception:
            pass
        # 2) translation defaults (zh/en)
        try:
            from core.translation import _t
            if i <= 3:
                return _t("probe_loc_%d" % i)
            return _t("probe_loc_n", n=i + 1)
        except Exception:
            fallback = ["左侧 · 上", "右侧 · 上", "左侧 · 下", "右侧 · 下"]
            return fallback[i] if i < len(fallback) else ("#%d" % (i + 1))

    def _link_level(self):
        t = self.master_link_label.text()
        if "离线" in t or "Offline" in t:
            return "offline"
        if "无L2" in t or "Linked" in t or "降级" in t:
            return "warn"
        return "ok"

    def _alarm_web_kind(self):
        if self._alarm_kind == "channel_alarm":
            return "alarm"
        if self._alarm_kind in ("over_threshold", "fault", "offline", "acked"):
            return "warn"
        return "normal"

    def build_hmi_state(self):
        probes = []
        for i, e in enumerate(self._probe_entries):
            probes.append({
                "name": e.get("name") or self._probe_name(i),
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
                    "name": self._probe_name(i),
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

        health_color = "#10B981"
        health_warn = False
        hs = self.health_status_label.text()
        hs_l = hs.lower()
        # Card/tag yellow only for degraded/fault — not mere master offline
        # (offline stays green tag; amber only on the Master HW row).
        if (
            "降级" in hs
            or ("故障" in hs and "无" not in hs)
            or "degrad" in hs_l
            or ("fault" in hs_l and "no " not in hs_l and "offline" not in hs_l)
        ):
            health_color = "#F59E0B"
            health_warn = True
        elif "离线" in hs or "offline" in hs_l:
            health_color = "#10B981"
            health_warn = False

        fault_color = "#10B981"
        fault_warn = False
        fs = self.fault_status_label.text()
        if "故障" in fs and "无" not in fs and "0" not in fs:
            fault_color = "#F59E0B"
            fault_warn = True
        elif "活动" in fs and not fs.strip().startswith("0"):
            fault_color = "#F59E0B"
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
                "title": self.alarm_status_label.text(),
                "desc": self.alarm_desc_label.text(),
                "sideRad": self.side_rad_stat.text() or self.alarm_status_label.text(),
                "latched": bool(self._reset_alarm_active),
                "latchText": getattr(self, "_alarm_latch_text", None)
                or self.alarm_latch_status.text()
                or "",
                "clearModeLatch": bool(getattr(self, "_alarm_clear_mode_latch", False)),
                "resetEnabled": bool(self._reset_enabled),
            },
            "passage": {
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
        try:
            from core.utils import get_battery_percentage
            level, _plugged = get_battery_percentage()
            if level is None:
                return "--%"
            return "%d%%" % int(level)
        except Exception:
            return "--%"

    def _flush_to_web(self):
        if not self._web_ready:
            return
        state = self.build_hmi_state()
        payload = json.dumps(state, ensure_ascii=False)
        js = "if (window.applyHmiState) { applyHmiState(%s); }" % payload
        self.browser.page().runJavaScript(js)

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
        for e in self._probe_entries:
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
                "name": self._probe_entries[i].get("name") or self._probe_name(i),
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
            self._probe_entries[i] = {
                "name": e.get("name") or self._probe_name(i),
                "location": self._slot_location(i),
                "cps": cps,
                "online": online,
                "hit": hit,
                "client_id": e.get("client_id"),
                "threshold": int(e.get("threshold", 1000) or 1000),
            }
        self._had_tile_data = True
        self.schedule_web_flush()

    def set_master_link_status(self, online, master_id=None, lang="zh", link_only=False):
        if online:
            mid = " #%s" % master_id if master_id is not None else ""
            text = ("Master Online%s" % mid) if lang == "en" else ("主控在线%s" % mid)
        elif link_only:
            text = "Master Linked (no L2)" if lang == "en" else "主控已连接(无L2)"
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
            if self._alarm_kind == "channel_alarm":
                self._alarm_kind = "normal"
        else:
            self._alarm_kind = "warn"
        self.schedule_web_flush()

    def apply_aux_card_style(self, card, bar, color=None):
        self.schedule_web_flush()

    def apply_status_label_style(self, label, color, _bg=None, _border=None):
        if label is self.occupancy_status_label:
            self._passage_busy = color in ("#2196f3", "#F59E0B")
        self.schedule_web_flush()

    def set_header_alarm(self, active: bool):
        self._alarm_kind = "channel_alarm" if active else "normal"
        self.schedule_web_flush()

    def retranslate_ui(self):
        from core.translation import _t
        self.title.setText(_t("home_title_full"))
        self.channel_reset_btn.setText(_t("btn_channel_alarm_reset"))
        self.schedule_web_flush()


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
