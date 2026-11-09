# -*- coding: utf-8 -*-
"""车辆通道主界面的四态。只根据已有 L2 / 探头 / 已结束通行生成文案，不画控件。"""

from __future__ import annotations

from datetime import datetime

from core.translation import _t
from core.vehicle.evidence_assets import path_for_role

HARD = (0x02, 0x03)
ELEVATED = 0x01
SYSTEM_FAULT = 0xFF

FIELD_ORDER = (
    "channel_status",
    "plate",
    "speed",
    "speed_limit",
    "overspeed",
    "rad_hard",
    "peak_cps",
    "gamma_total",
    "threshold_note",
)


def _em() -> str:
    return _t("vdash_emdash")


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


def _speed_text(speed) -> str:
    if speed is None:
        return _em()
    try:
        return "%.1f" % float(speed)
    except (TypeError, ValueError):
        return _em()


def _yes_no_unknown(yes: bool, known: bool) -> str:
    if not known:
        return _em()
    return _t("vdash_yes") if yes else _t("vdash_no")


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
        stamp = _em()
    if invalid:
        radiation = _em()
        over_txt = _em()
        result = _t("vhist_result_invalid")
        speed_txt = _em()
        result_kind = "invalid"
        rad_kind = ""
    elif hard:
        radiation = _t("vhist_rad_hard")
        over_txt = _yes_no_unknown(overspeed, speed is not None)
        result = _t("vhist_result_deny")
        speed_txt = _speed_text(speed)
        result_kind = "deny"
        rad_kind = "hard"
    else:
        radiation = _t("vhist_rad_ok")
        over_txt = _yes_no_unknown(overspeed, speed is not None)
        result = _t("vhist_result_pass")
        speed_txt = _speed_text(speed)
        result_kind = "pass"
        rad_kind = "ok"
    plate = str(row.get("plate") or "").strip() or _em()
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
        "result_kind": result_kind,
        "rad_kind": rad_kind,
        "overspeed_yes": overspeed and speed is not None,
    }


def vehicle_probe_location(index: int, count: int) -> str:
    side = _t("vprobe_side_left") if index % 2 == 0 else _t("vprobe_side_right")
    if count <= 2:
        return side
    return _t("vprobe_side_row", side=side, row=index // 2 + 1)


def _probe_slot(probe: dict, fallback: int) -> int:
    try:
        return int(probe.get("slot", fallback))
    except (TypeError, ValueError):
        return fallback


def _probe_label_num(probe: dict, slot: int) -> int:
    try:
        n = int(probe.get("label_num", slot + 1))
        return n if n > 0 else slot + 1
    except (TypeError, ValueError):
        return slot + 1


def _probe_cards(probes, decision: int, hit_mask: int) -> list:
    cards = []
    probes = list(probes or [])
    probes.sort(key=lambda p: _probe_slot(p or {}, 0))
    for i, probe in enumerate(probes):
        probe = probe or {}
        slot = _probe_slot(probe, i)
        label = _probe_label_num(probe, slot)
        location = str(probe.get("location") or "").strip()
        if not location:
            location = vehicle_probe_location(slot, len(probes))
        title = _t("vprobe_title", n=label)
        meta = {
            "slot": slot,
            "label_num": label,
            "client_id": probe.get("client_id"),
        }
        if probe.get("absent"):
            cards.append({
                "title": title,
                "location": location,
                "cps_text": "",
                "status": _t("vprobe_absent"),
                "status_key": "absent",
                "tone": "offline",
                "show_cps": False,
                **meta,
            })
            continue
        comm = bool(probe.get("comm_fault"))
        hv = bool(probe.get("hv_fault"))
        online = bool(probe.get("online", True))
        masked = bool(int(hit_mask or 0) & (1 << slot))
        hit = masked or (bool(probe.get("hit")) and not hit_mask)
        cps = int(probe.get("cps") or 0)
        if comm or not online:
            cards.append({
                "title": title,
                "location": location,
                "cps_text": "",
                "status": _t("vprobe_comm_fault"),
                "status_key": "comm",
                "tone": "fault",
                "show_cps": False,
                **meta,
            })
            continue
        if hv:
            cards.append({
                "title": title,
                "location": location,
                "cps_text": "",
                "status": _t("vprobe_hv_fault"),
                "status_key": "hv",
                "tone": "fault",
                "show_cps": False,
                **meta,
            })
            continue
        if decision in HARD and hit:
            status, tone, sk = _t("vprobe_alarm"), "alarm", "alarm"
        elif decision == ELEVATED and hit:
            status, tone, sk = _t("vprobe_elevated"), "amber", "elevated"
        else:
            status, tone, sk = _t("vprobe_ok"), "ok", "ok"
        cards.append({
            "title": title,
            "location": location,
            "cps_text": str(cps),
            "status": status,
            "status_key": sk,
            "tone": tone,
            "show_cps": True,
            **meta,
        })
    return cards


def _banner(decision: int, probes_view: list, master_online: bool, passage_open: bool) -> tuple:
    probe_fault = any(
        card.get("status_key") not in ("absent", None) and card.get("tone") == "fault"
        for card in probes_view
    )
    if decision in HARD:
        tone = "alarm"
        title = _t("vbanner_rad_alarm")
    elif decision == SYSTEM_FAULT or probe_fault:
        tone = "fault"
        title = _t("vbanner_sys_fault")
    elif decision == ELEVATED:
        tone = "amber"
        title = _t("vbanner_elevated")
    else:
        tone = "ok"
        title = _t("vbanner_passing") if passage_open else _t("vbanner_idle")
    chips = [
        _t("vchip_master_online") if master_online else _t("vchip_master_offline"),
    ]
    if tone == "ok":
        chips.append(_t("vchip_rad_ok"))
    elif tone == "alarm":
        if passage_open:
            chips.append(_t("vchip_passing"))
        chips.append(_t("vchip_deny"))
    return title, tone, chips


def _mk_field(fid: str, text: str, hint: str = "") -> dict:
    return {"id": fid, "text": text, "hint": hint}


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
        guide = _t("vguide_elevated")
    elif tone == "fault":
        guide = _t("vguide_fault")
    else:
        guide = ""
    hard = decision in HARD

    plate = ""
    if passage is not None:
        plate = str(getattr(passage, "plate", "") or "").strip()
    waiting = passage is not None and getattr(passage, "t2_ms", None) is None
    speed = getattr(passage, "speed_kmh", None) if passage is not None else None

    if passage is None:
        channel_txt = _t("vval_channel_idle")
        channel_hint = "idle"
        speed_txt = _em()
        over_txt = _em()
        over_hint = ""
        capture = "wait"
    elif waiting or speed is None:
        channel_txt = _t("vval_channel_passing")
        channel_hint = "passing"
        speed_txt = _t("vval_wait_exit")
        over_txt = _em()
        over_hint = ""
        capture = "plate" if plate else "manual"
    else:
        channel_txt = _t("vval_channel_passing")
        channel_hint = "passing"
        speed_txt = _speed_text(speed)
        over_txt = _yes_no_unknown(bool(getattr(passage, "overspeed", False)), True)
        over_hint = "yes" if bool(getattr(passage, "overspeed", False)) else "no"
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

    plate_txt = plate if plate else _t("vval_plate_manual")
    rad_txt = _t("vdash_yes") if hard else _t("vval_rad_none")
    rad_hint = "yes" if hard else "no"

    fields = [
        _mk_field("channel_status", channel_txt, channel_hint),
        _mk_field("plate", plate_txt),
        _mk_field("speed", speed_txt),
        _mk_field("speed_limit", _t("vval_speed_limit", v=int(v_limit or 0))),
        _mk_field("overspeed", over_txt, over_hint),
        _mk_field("rad_hard", rad_txt, rad_hint),
        _mk_field("peak_cps", str(peak) if passage is not None else _em()),
        _mk_field("gamma_total", str(total) if passage is not None else _em()),
    ]
    alarm_image = ""
    if hard and passage is not None:
        raw_paths = str(getattr(passage, "image_paths", "") or "")
        alarm_image = (
            path_for_role(raw_paths, "alarm")
            or path_for_role(raw_paths, "exit")
            or path_for_role(raw_paths, "entry")
        )

    if hard:
        fields.append(_mk_field("threshold_note", _t("vval_threshold_dyn")))
        keep = (
            "rad_hard", "peak_cps", "threshold_note",
            "channel_status", "plate", "speed", "speed_limit", "overspeed",
        )
        fields = [f for f in fields if f["id"] in keep]
        priority = {n: i for i, n in enumerate(keep)}
        fields.sort(key=lambda f: priority.get(f["id"], 99))
    elif decision == ELEVATED:
        keep = (
            "channel_status", "plate", "rad_hard", "peak_cps", "gamma_total",
            "speed", "speed_limit", "overspeed",
        )
        fields = [f for f in fields if f["id"] in keep]
        priority = {n: i for i, n in enumerate(keep)}
        fields.sort(key=lambda f: priority.get(f["id"], 99))

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
        "alarm_image": alarm_image,
        "plate": plate,
        "probes": cards,
        "fields": fields,
        "history": rows,
        "guide": guide,
        "show_diagnose": tone == "fault",
    }
