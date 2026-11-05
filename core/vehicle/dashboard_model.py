# -*- coding: utf-8 -*-
"""车辆通道主界面的四态。只根据已有 L2 / 探头 / 已结束通行生成文案，不画控件。"""

from __future__ import annotations

from datetime import datetime

HARD = (0x02, 0x03)
ELEVATED = 0x01
SYSTEM_FAULT = 0xFF


def _num_list(values) -> list:
    out = []
    for item in list(values or []):
        try:
            out.append(int(item or 0))
        except (TypeError, ValueError):
            out.append(0)
    return out


def _totals(values) -> tuple:
    nums = _num_list(values)
    if not nums:
        return 0, 0
    peak = max(nums)
    total = sum(nums)
    if total < peak:
        total = peak
    return total, peak


def _hit_text(mask: int) -> str:
    bits = [i for i in range(16) if int(mask or 0) & (1 << i)]
    if not bits:
        return "—"
    return "探头" + "+".join(str(i + 1) for i in bits)


def _speed_text(speed) -> str:
    if speed is None:
        return "—"
    try:
        return "%.1f" % float(speed)
    except (TypeError, ValueError):
        return "—"


def history_row(row: dict, lane: str = "03") -> dict:
    """一条已结束通行。峰值不会大于总计。未完成的本趟不要传进来。"""
    total, peak = _totals(row.get("peak_cps") or row.get("cps"))
    invalid = str(row.get("invalid_reason") or "")
    decision = int(row.get("decision") or 0)
    hard = bool(row.get("hard_alarm")) or decision in HARD
    speed = row.get("speed_kmh")
    overspeed = bool(row.get("overspeed")) and speed is not None
    when = float(row.get("closed_at") or row.get("opened_at") or 0)
    if when <= 0:
        head = str(row.get("passage_id") or "").split("-")[0]
        if head.isdigit() and len(head) >= 10:
            when = float(head)
    if when > 0:
        stamp = datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S")
    else:
        stamp = "—"
    if invalid:
        radiation = "—"
        over_txt = "—"
        result = "无效"
        speed_txt = "—"
    elif hard:
        radiation = "硬报"
        over_txt = "是" if overspeed else ("否" if speed is not None else "—")
        result = "禁行"
        speed_txt = _speed_text(speed)
    else:
        radiation = "正常"
        over_txt = "是" if overspeed else ("否" if speed is not None else "—")
        result = "放行"
        speed_txt = _speed_text(speed)
    plate = str(row.get("plate") or "").strip() or "—"
    return {
        "time": stamp,
        "lane": str(lane or "03"),
        "plate": plate,
        "total": str(total),
        "peak": str(peak),
        "radiation": radiation,
        "speed": speed_txt,
        "overspeed": over_txt,
        "result": result,
    }


def _probe_cards(probes, decision: int, hit_mask: int) -> list:
    cards = []
    for i, probe in enumerate(list(probes or [])):
        probe = probe or {}
        location = str(probe.get("location") or "").strip()
        if not location:
            location = "左侧" if i == 0 else ("右侧" if i == 1 else "")
        if probe.get("absent"):
            cards.append({
                "title": "探头 %d" % (i + 1),
                "location": location,
                "cps_text": "",
                "status": "未接入",
                "tone": "offline",
                "show_cps": False,
            })
            continue
        comm = bool(probe.get("comm_fault"))
        hv = bool(probe.get("hv_fault"))
        online = bool(probe.get("online", True))
        hit = bool(int(hit_mask or 0) & (1 << i)) or bool(probe.get("hit"))
        cps = int(probe.get("cps") or 0)
        if comm or not online:
            cards.append({
                "title": "探头 %d" % (i + 1),
                "location": location,
                "cps_text": "",
                "status": "通信异常",
                "tone": "fault",
                "show_cps": False,
            })
            continue
        if hv:
            status, tone = "高压偏离", "fault"
        elif decision in HARD and hit:
            status, tone = "报警", "alarm"
        elif decision == ELEVATED and hit:
            status, tone = "偏高", "amber"
        else:
            status, tone = "正常", "ok"
        cards.append({
            "title": "探头 %d" % (i + 1),
            "location": location,
            "cps_text": str(cps),
            "status": status,
            "tone": tone,
            "show_cps": True,
        })
    return cards


def _banner(decision: int, probes_view: list, master_online: bool, passage_open: bool) -> tuple:
    probe_fault = any(
        card["tone"] == "fault" for card in probes_view if card["status"] != "未接入"
    )
    if decision in HARD:
        tone = "alarm"
        title = "辐射报警"
    elif decision == SYSTEM_FAULT or probe_fault:
        tone = "fault"
        title = "系统故障"
    elif decision == ELEVATED:
        tone = "amber"
        title = "计数偏高"
    else:
        tone = "ok"
        title = "通道空闲"
    chips = ["主控在线" if master_online else "主控离线"]
    if tone == "ok":
        chips.append("辐射正常")
    elif tone == "alarm":
        if passage_open:
            chips.append("车辆经过")
        chips.append("禁行")
    return title, tone, chips


def build_dashboard(
    packet,
    probes,
    passage,
    history,
    master_online: bool = True,
    lane: str = "03",
    v_limit: float = 8.0,
) -> dict:
    decision = 0
    hit_mask = 0
    if packet is not None:
        try:
            decision = int(getattr(packet, "decision_result", 0) or 0)
        except (TypeError, ValueError):
            decision = 0
        try:
            hit_mask = int(getattr(packet, "hit_probe_mask", 0) or 0)
        except (TypeError, ValueError):
            hit_mask = 0
    if passage is not None:
        hit_mask = hit_mask or int(getattr(passage, "hit_probe_mask", 0) or 0)

    cards = _probe_cards(probes, decision, hit_mask)
    title, tone, chips = _banner(decision, cards, bool(master_online), passage is not None)
    if tone == "amber":
        guide = "请停车复查，确认不是硬报后再放行"
    elif tone == "fault":
        guide = "这是设备故障，不是辐射报警。通信或高压要在设备侧恢复"
    else:
        guide = ""
    hard = decision in HARD

    plate = ""
    if passage is not None:
        plate = str(getattr(passage, "plate", "") or "").strip()
    waiting = passage is not None and getattr(passage, "t2_ms", None) is None
    speed = getattr(passage, "speed_kmh", None) if passage is not None else None

    if passage is None:
        channel = "空闲"
        speed_txt = "—"
        over_txt = "—"
        capture = "wait"
    elif waiting or speed is None:
        channel = "车辆经过"
        speed_txt = "等待出口"
        over_txt = "—"
        capture = "plate" if plate else "manual"
    else:
        channel = "车辆经过"
        speed_txt = _speed_text(speed)
        over_txt = "是" if bool(getattr(passage, "overspeed", False)) else "否"
        capture = "plate" if plate else "manual"

    live_nums = []
    if passage is not None:
        live_nums = _num_list(getattr(passage, "peak_cps", None) or getattr(passage, "cps", None))
    if not live_nums:
        live_nums = [
            int(card["cps_text"])
            for card in cards
            if card["show_cps"] and str(card["cps_text"]).isdigit()
        ]
    total, peak = _totals(live_nums) if passage is not None else (0, 0)

    fields = [
        ("通道状态", channel),
        ("车牌", plate if plate else "— 可手补"),
        ("车速", speed_txt),
        ("限速", "%.0f km/h" % float(v_limit or 0)),
        ("超速", over_txt),
        ("辐射硬报", "是" if hard else "无"),
        ("峰值CPS", str(peak) if passage is not None else "—"),
        ("γ总计", str(total) if passage is not None else "—"),
        ("命中掩码", _hit_text(hit_mask) if (hard or decision == ELEVATED) else "—"),
    ]
    if hard:
        fields.append(("阈值说明", "动态阈值"))

    rows = []
    for item in list(history or []):
        if str(item.get("invalid_reason") or ""):
            continue
        if passage is not None and str(item.get("passage_id") or "") == str(getattr(passage, "passage_id", "") or ""):
            continue
        rows.append(history_row(item, lane))
        if len(rows) >= 8:
            break

    return {
        "banner": title,
        "banner_tone": tone,
        "chips": chips,
        "show_reset": hard,
        "lane": str(lane or "03"),
        "capture": capture,
        "plate": plate,
        "probes": cards,
        "fields": fields,
        "history": rows,
        "guide": guide,
        "show_diagnose": tone == "fault",
    }
