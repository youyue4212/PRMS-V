# -*- coding: utf-8 -*-
"""车辆通道主界面四态自检。不启动完整监测软件。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vehicle.dashboard_model import FIELD_ORDER, build_dashboard, history_row
from core.translation import _t
from core.vehicle.passage_fsm import Passage
from core.vehicle.passage_store import PassageStore


class _Pkt:
    def __init__(self, decision, hit=0):
        self.decision_result = decision
        self.hit_probe_mask = hit


def _probes(cps, hit_flags=(), slots=()):
    out = []
    for i, value in enumerate(cps):
        slot = slots[i] if i < len(slots) else i
        out.append({
            "slot": slot,
            "label_num": slot + 1,
            "location": "左侧" if slot == 0 else "右侧",
            "cps": value,
            "online": True,
            "comm_fault": False,
            "hv_fault": False,
            "hit": slot in hit_flags,
        })
    return out


def _field_id(name: str) -> str:
    if name in FIELD_ORDER:
        return name
    for fid in FIELD_ORDER:
        if _t("vfield_" + fid) == name:
            return fid
    return name


def _field(model, name):
    fid = _field_id(name)
    for item in model["fields"]:
        if item.get("id") == fid:
            return item.get("text")
    raise KeyError(name)


def _field_ids(model) -> set:
    return {str(f.get("id") or "") for f in model.get("fields") or []}


def _check(name, cond):
    if not cond:
        raise SystemExit("FAIL " + name)


def _check_online_debounce():
    from core.probe_online_hold import PROBE_OFFLINE_HOLD_SEC, debounce_probe_online

    hold = {}
    t0 = 1_000.0
    _check("debounce online", debounce_probe_online(hold, 0, True, 50, t0) is True)
    hold[0]["last"] = (50, True, False)
    _check("debounce hold", debounce_probe_online(hold, 0, False, 0, t0 + 0.2) is True)
    _check(
        "debounce drop",
        debounce_probe_online(hold, 0, False, 0, t0 + PROBE_OFFLINE_HOLD_SEC + 0.3) is False,
    )
    _check("debounce slot keys", 0 in hold and 1 not in hold)


def main():
    _check_online_debounce()
    idle = build_dashboard(_Pkt(0x00), _probes([342, 298]), None, [], True, "03", 8)
    _check("idle banner", idle["banner"] == "通道空闲" and idle["banner_tone"] == "ok")
    _check("idle chips", idle["chips"] == ["主控在线", "辐射正常"])
    _check("idle no reset", idle["show_reset"] is False)
    _check("idle hard", _field(idle, "辐射硬报") == "无")
    _check("idle speed dash", _field(idle, "车速") == "—")
    _check("idle no survey row", "speed" not in _field_ids(idle) or _field(idle, "speed") == "—")
    _check("idle capture", idle["capture"] == "wait")
    _check("idle card count", len(idle["probes"]) == 2 and idle["probes"][0]["show_cps"] is True)

    open_hard = Passage(
        passage_id="open-1", t1_ms=1, length_m=6, v_limit_kmh=8,
        plate="京A·D12345", peak_cps=[1542, 1287], hit_probe_mask=0x3,
    )
    closed_fast = {
        "passage_id": "old-fast",
        "peak_cps": [400, 343],
        "speed_kmh": 21.0,
        "overspeed": True,
        "hard_alarm": False,
        "decision": 0,
        "plate": "京C·F6655",
        "closed_at": 1_700_000_000,
    }
    closed_alarm = {
        "passage_id": "old-alarm",
        "peak_cps": [1542, 1287],
        "speed_kmh": 15.5,
        "overspeed": True,
        "hard_alarm": True,
        "decision": 0x03,
        "plate": "京D·A9876",
        "closed_at": 1_700_000_100,
    }
    alarm = build_dashboard(
        _Pkt(0x03, 0x3), _probes([1542, 1287], (0, 1)), open_hard,
        [closed_fast, {"passage_id": "open-1", "plate": "SHOULD-SKIP", "peak_cps": [1], "closed_at": 5}],
        True, "03", 8,
    )
    _check("alarm banner", alarm["banner"] == "辐射报警")
    _check("alarm chips", "禁行" in alarm["chips"] and "车辆经过" in alarm["chips"])
    _check("alarm reset", alarm["show_reset"] is True)
    _check("alarm speed", _field(alarm, "车速") == "等待出口")
    _check("alarm peak", _field(alarm, "峰值CPS") == "1542")
    _check("alarm no gamma row", "gamma_total" not in _field_ids(alarm))
    _check("alarm no hit mask ui", "hit_mask" not in _field_ids(alarm))
    swapped = build_dashboard(
        _Pkt(0x03, 0x2),
        [
            {"slot": 1, "label_num": 2, "location": "右侧", "cps": 1542, "online": True},
            {"slot": 0, "label_num": 1, "location": "左侧", "cps": 100, "online": True},
        ],
        None, [], True, "03", 8,
    )
    _check("hit follows l2 slot", swapped["probes"][0]["title"] == "探头 1" and swapped["probes"][0]["status"] == "正常")
    _check("hit follows l2 slot 2", swapped["probes"][1]["title"] == "探头 2" and swapped["probes"][1]["status"] == "报警")
    _check("alarm open not in history", all(r["plate"] != "SHOULD-SKIP" for r in alarm["history"]))
    invalid = history_row({"invalid_reason": "timeout", "speed_kmh": 21, "overspeed": True, "closed_at": 9})
    _check("timeout not pass", invalid["result"] == "无效" and invalid["overspeed"] == "—" and invalid["radiation"] == "—")
    fast = history_row(closed_fast)
    _check("overspeed still pass", fast["overspeed"] == "是" and fast["result"] == "放行" and fast["radiation"] == "正常")
    banned = history_row(closed_alarm)
    _check("hard ban", banned["radiation"] == "硬报" and banned["result"] == "禁行" and banned["overspeed"] == "是")
    fixed = history_row({"peak_cps": [512, 812], "speed_kmh": 7.1, "closed_at": 10})
    _check("peak not above total", int(fixed["peak"]) <= int(fixed["total"]))

    open_soft = Passage(
        passage_id="soft-1", t1_ms=2, length_m=6, v_limit_kmh=8,
        plate="京A·D12345", peak_cps=[890, 760], hit_probe_mask=0x3,
    )
    soft = build_dashboard(_Pkt(0x01, 0x3), _probes([890, 760], (0, 1)), open_soft, [closed_fast], True, "03", 8)
    _check("elevated banner", soft["banner"] == "计数偏高" and soft["banner_tone"] == "amber")
    _check("elevated no normal chip", "辐射正常" not in soft["chips"] and "禁行" not in soft["chips"])
    _check("elevated no reset", soft["show_reset"] is False)
    _check("elevated speed", _field(soft, "车速") == "等待出口" and _field(soft, "辐射硬报") == "无")
    _check("elevated numbers", _field(soft, "峰值CPS") == "890" and _field(soft, "γ总计") == "1650")
    _check("elevated no hit mask ui", "hit_mask" not in _field_ids(soft))
    _check("elevated plate", soft["plate"] == "京A·D12345")
    _check("live totals not copied into history", all(r["total"] != "1650" for r in soft["history"]))

    fault_probes = [
        {"slot": 0, "label_num": 1, "location": "左侧", "cps": 342, "online": False, "comm_fault": True, "hv_fault": False},
        {"slot": 1, "label_num": 2, "location": "右侧", "cps": 298, "online": True, "comm_fault": False, "hv_fault": True},
    ]
    fault = build_dashboard(_Pkt(0x00), fault_probes, None, [], True, "03", 8)
    _check("fault banner", fault["banner"] == "系统故障")
    _check("fault master", fault["chips"] == ["主控在线"])
    _check("fault no reset", fault["show_reset"] is False and "禁行" not in fault["chips"])
    _check("fault hard none", _field(fault, "辐射硬报") == "无")
    _check("fault comm hides cps", fault["probes"][0]["status"] == "通信异常" and fault["probes"][0]["show_cps"] is False)
    _check("fault hv", fault["probes"][1]["status"] == "高压偏离" and fault["probes"][1]["show_cps"] is False)
    _check("fault idle channel", _field(fault, "通道状态") == "空闲")
    _check("elevated guide", "停车复查" in soft["guide"] and soft["show_diagnose"] is False)
    _check("fault guide", "不是辐射报警" in fault["guide"] and fault["show_diagnose"] is True)
    dropped = build_dashboard(
        _Pkt(0), _probes([1, 1]), None,
        [{"invalid_reason": "timeout", "peak_cps": [9], "closed_at": 4, "passage_id": "bad"}],
        True, "03", 8,
    )
    _check("invalid hidden", dropped["history"] == [])
    slots = build_dashboard(
        _Pkt(0),
        [{"absent": True, "online": False}, {"absent": True, "online": False}],
        None, [], True, "03", 8,
    )
    _check("absent slots", len(slots["probes"]) == 2 and all(p["status"] == "未接入" for p in slots["probes"]))
    _check("absent not fault", slots["banner"] == "通道空闲")
    kept = history_row({"decision": 0x01, "peak_cps": [10, 4], "speed_kmh": 5, "closed_at": 3})
    _check("elevated stays normal", kept["radiation"] == "正常" and kept["result"] == "放行")

    offline = build_dashboard(None, _probes([10, 10]), None, [], False, "03", 8)
    _check("master chip", offline["chips"][0] == "主控离线" and offline["banner"] == "通道空闲")

    with tempfile.TemporaryDirectory() as tmp:
        store = PassageStore(Path(tmp) / "p.sqlite")
        store.insert(open_hard.as_row() | {
            "closed_at": 20,
            "hard_alarm": True,
            "decision": 0x03,
            "speed_kmh": 15.5,
            "overspeed": True,
            "peak_cps": [1542, 1287],
        })
        got = store.recent(5)
        store.close()
        _check("store keeps peak", got and got[0]["peak_cps"] == [1542, 1287])
        _check("store plate", got[0]["plate"] == "京A·D12345")

    from PyQt5.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    from core.vehicle_dashboard_page import VehicleDashboardPage
    page = VehicleDashboardPage()
    page.show()
    app.processEvents()
    page.apply_model(soft)
    app.processEvents()
    _check("qt banner", page.banner_label.text() == "计数偏高")
    _check("qt reset hidden", page.reset_btn.isHidden() is True)
    _check("qt hard field", page._field_values["rad_hard"].text() == "无")
    page.apply_model(alarm)
    app.processEvents()
    _check("qt reset shown", page.reset_btn.isVisible() is True)
    _check("qt ban chip", any(isinstance(w, QLabel) and w.text() == "禁行" for i in range(page.chip_host.count()) for w in [page.chip_host.itemAt(i).widget()]))
    _check("qt threshold", page._field_keys["threshold_note"].isVisible() is True)
    _check("qt alarm keeps plate", page._field_rows["plate"].isVisible() is True)
    _check("qt alarm hides gamma", page._field_rows["gamma_total"].isVisible() is False)
    _check("qt reset gray", page.reset_btn.isEnabled() is False)
    headers = [page.history.horizontalHeaderItem(c).text() for c in range(page.history.columnCount())]
    _check(
        "qt history cols",
        headers == ["通行时间", "通道", "车牌", "γ总计", "峰值", "辐射结果", "速度", "超速", "通行结果"],
    )
    page.apply_model(fault)
    app.processEvents()
    _check("qt fault", page.banner_label.text() == "系统故障" and page.reset_btn.isVisible() is False)
    comm_card, hv_card = page._cards[0], page._cards[1]
    _check("qt comm word", comm_card.cps.text() == "通信异常" and comm_card.status.text() == "查链路" and comm_card.unit.isHidden())
    _check("qt hv word", hv_card.cps.text() == "高压偏离" and hv_card.status.text() == "等高压恢复" and hv_card.unit.isHidden())
    _check("qt fault same size", comm_card.cps.styleSheet() == hv_card.cps.styleSheet())
    _check("qt fault wrench", page.status_icon.isVisible() is True)
    _check("qt empty history", page.history.rowCount() == 1 and page.history.item(0, 0).text() == "暂无通行记录")
    bare = build_dashboard(_Pkt(0), [{"cps": 1}, {"cps": 2}], None, [], True, "03", 8)
    _check("loc two", [c["location"] for c in bare["probes"]] == ["左侧", "右侧"])
    bare4 = build_dashboard(_Pkt(0), [{"cps": 1}] * 4, None, [], True, "03", 8)
    _check("loc four", [c["location"] for c in bare4["probes"]] == ["左侧 · 1", "右侧 · 1", "左侧 · 2", "右侧 · 2"])
    page.apply_model(build_dashboard(_Pkt(0), _probes([342] * 8), None, [], True, "03", 8))
    app.processEvents()
    _check("qt eight compact", all(c._compact for c in page._cards[:8]) and page._cards[7].isVisible())
    page.apply_model(build_dashboard(_Pkt(0), _probes([342] * 4), None, [], True, "03", 8))
    app.processEvents()
    _check("qt four full", not any(c._compact for c in page._cards[:4]) and page._cards[4].isHidden())
    page.apply_model(fault)
    _check("qt trouble", "查链路" in page.trouble.text() and "等高压" in page.trouble.text())
    page.set_reset_allowed(True)
    page.apply_model(alarm)
    _check("qt reset live", page.reset_btn.isEnabled() is True)
    page.apply_model(soft)
    _check("qt recheck", page.recheck_btn.isVisible() is True and page.reset_btn.isVisible() is False)
    page.apply_model(idle)
    app.processEvents()
    _check("qt idle", page.banner_label.text() == "通道空闲" and page.capture.center_text() == "等待过车")
    _check("qt login", page.banner.login_btn.text() == _t("btn_login"))
    page.set_session(True, "admin")
    _check(
        "qt session",
        page.banner.login_btn.text() == _t("btn_logout")
        and page.banner.session_label.text() == "admin",
    )
    _check("qt no threshold", page._field_keys["threshold_note"].isVisible() is False)
    print("ok vehicle dashboard")


if __name__ == "__main__":
    main()
