# -*- coding: utf-8 -*-
"""PRMS-V-11 通行记录。SQLite 留在本机，同时写入 PRMS.vehicle_passages。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None


def vehicle_passage_document(row: dict, label_for_slot=None) -> dict:
    """一辆车一次通行。字段与行人报警对齐，并带上车速。"""
    opened = float(row.get("opened_at") or 0)
    closed = float(row.get("closed_at") or opened or 0)
    if opened <= 0:
        opened = closed
    t1 = row.get("t1_ms")
    t2 = row.get("t2_ms")
    duration = 0.0
    if t1 is not None and t2 is not None:
        duration = ((int(t2) - int(t1)) & 0xFFFFFFFF) / 1000.0
    elif opened and closed:
        duration = max(0.0, closed - opened)
    invalid = str(row.get("invalid_reason") or "")
    hard = bool(row.get("hard_alarm")) or int(row.get("decision") or 0) in (0x02, 0x03)
    if invalid:
        status = "invalid"
    elif hard:
        status = "alarm"
    else:
        status = "passed"
    ctx = dict(row.get("context") or {})
    hit = int(row.get("hit_probe_mask") or 0)
    slots = [i for i in range(16) if hit & (1 << i)]
    labels = []
    for slot in slots:
        if label_for_slot is not None:
            try:
                labels.append(str(label_for_slot(slot) or ""))
            except Exception:
                labels.append("探头 %d" % (slot + 1))
        else:
            labels.append("探头 %d" % (slot + 1))
    peak_list = [int(v or 0) for v in list(row.get("peak_cps") or row.get("cps") or [])]
    trigger_list = [int(v or 0) for v in list(row.get("trigger_cps") or [])]
    peak = max(peak_list) if peak_list else 0
    trigger = max(trigger_list) if trigger_list else peak
    speed = row.get("speed_kmh")
    speed_txt = "%.2f km/h" % float(speed) if speed is not None else ""
    if invalid:
        note = invalid
    elif hard and speed_txt:
        note = "辐射报警 %s" % speed_txt
    else:
        note = speed_txt or status
    if row.get("overspeed") and speed_txt:
        note = "%s 超速" % note
    when = closed or opened
    doc = {
        "episode_id": str(row.get("passage_id") or ""),
        "time": datetime.fromtimestamp(when) if when else datetime.now(),
        "started_at": datetime.fromtimestamp(opened) if opened else None,
        "ended_at": datetime.fromtimestamp(closed) if closed else None,
        "status": status,
        "decision": status,
        "duration": float(duration),
        "client_id": "vehicle_channel",
        "master_id": ctx.get("master_id"),
        "alarm_type": "VehiclePassage",
        "counts_stat": not bool(invalid),
        "probe_slot": slots[0] if slots else None,
        "probe_label": "、".join(x for x in labels if x),
        "trigger_cps": float(trigger),
        "peak_cps": float(peak),
        "cps": float(peak),
        "probe_cps": peak_list,
        "total_cps": ctx.get("total_cps"),
        "decision_code": int(row.get("decision") or 0),
        "decision_text": str(row.get("decision_text") or ""),
        "hit_mask": hit,
        "online_mask": ctx.get("online_mask"),
        "ir_entry": True,
        "ir_exit": t2 is not None,
        "radar_gate": ctx.get("radar_gate"),
        "sensor_mode": ctx.get("sensor_mode"),
        "ungated": ctx.get("ungated"),
        "latch_mode": ctx.get("latch_mode"),
        "match_threshold_n": ctx.get("match_threshold_n"),
        "window_x_sec": ctx.get("window_x_sec"),
        "window_y_sec": ctx.get("window_y_sec"),
        "length_m": row.get("length_m"),
        "speed_kmh": None if speed is None else float(speed),
        "v_limit_kmh": row.get("v_limit_kmh"),
        "overspeed": bool(row.get("overspeed")),
        "t1_ms": t1,
        "t2_ms": t2,
        "r2_on": bool(row.get("r2_on")),
        "invalid_reason": invalid,
        "note": note,
    }
    return doc


def insert_vehicle_passage_mongo(row: dict, label_for_slot=None) -> None:
    """写入 PRMS.vehicle_passages。连不上就跳过，不影响本机 SQLite。"""
    if MongoClient is None:
        return
    try:
        client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=800)
        client.admin.command("ping")
        client["PRMS"]["vehicle_passages"].insert_one(
            vehicle_passage_document(row, label_for_slot)
        )
        client.close()
    except Exception as exc:
        print("Mongo vehicle insert skipped:", exc)


class PassageStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.label_for_slot = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS passage (
                passage_id TEXT PRIMARY KEY,
                t1_ms INTEGER,
                t2_ms INTEGER,
                length_m REAL,
                speed_kmh REAL,
                v_limit_kmh REAL,
                overspeed INTEGER,
                decision INTEGER,
                hit_probe_mask INTEGER,
                cps_json TEXT,
                plate TEXT,
                plate_manual TEXT,
                image_paths TEXT,
                r2_on INTEGER,
                invalid_reason TEXT
            )
            """
        )
        self._conn.commit()
        have = {r[1] for r in self._conn.execute("PRAGMA table_info(passage)")}
        for name, typ in (
            ("peak_json", "TEXT"),
            ("opened_at", "REAL"),
            ("closed_at", "REAL"),
            ("hard_alarm", "INTEGER"),
        ):
            if name not in have:
                self._conn.execute("ALTER TABLE passage ADD COLUMN %s %s" % (name, typ))
        self._conn.commit()

    def insert(self, row: dict) -> None:
        cps = row.get("cps") or []
        self._conn.execute(
            """
            INSERT OR REPLACE INTO passage (
                passage_id, t1_ms, t2_ms, length_m, speed_kmh, v_limit_kmh,
                overspeed, decision, hit_probe_mask, cps_json,
                plate, plate_manual, image_paths, r2_on, invalid_reason,
                peak_json, opened_at, closed_at, hard_alarm
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["passage_id"],
                row.get("t1_ms"),
                row.get("t2_ms"),
                row.get("length_m"),
                row.get("speed_kmh"),
                row.get("v_limit_kmh"),
                1 if row.get("overspeed") else 0,
                int(row.get("decision") or 0),
                int(row.get("hit_probe_mask") or 0),
                json.dumps(list(cps)),
                row.get("plate") or "",
                row.get("plate_manual") or "",
                row.get("image_paths") or "",
                1 if row.get("r2_on") else 0,
                row.get("invalid_reason") or "",
                json.dumps([int(v or 0) for v in list(row.get("peak_cps") or cps)]),
                float(row.get("opened_at") or 0),
                float(row.get("closed_at") or 0),
                1 if row.get("hard_alarm") else 0,
            ),
        )
        self._conn.commit()
        insert_vehicle_passage_mongo(row, self.label_for_slot)

    def recent(self, limit: int = 8) -> list:
        """已结束的通行，新的在前。未出出口的本趟不在表里。"""
        cur = self._conn.execute(
            """
            SELECT passage_id, speed_kmh, v_limit_kmh, overspeed, decision,
                   hit_probe_mask, cps_json, peak_json, plate, plate_manual,
                   invalid_reason, opened_at, closed_at, hard_alarm
            FROM passage
            ORDER BY COALESCE(closed_at, opened_at, 0) DESC, rowid DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = []
        for rec in cur.fetchall():
            cps = _json_list(rec[6])
            peak = _json_list(rec[7]) or cps
            when = float(rec[12] or rec[11] or 0)
            rows.append({
                "passage_id": rec[0],
                "speed_kmh": rec[1],
                "v_limit_kmh": rec[2],
                "overspeed": bool(rec[3]),
                "decision": int(rec[4] or 0),
                "hit_probe_mask": int(rec[5] or 0),
                "cps": cps,
                "peak_cps": peak,
                "plate": rec[9] or rec[8] or "",
                "invalid_reason": rec[10] or "",
                "opened_at": float(rec[11] or 0),
                "closed_at": when,
                "hard_alarm": bool(rec[13]),
            })
        return rows

    def close(self) -> None:
        self._conn.close()


def _json_list(raw) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        try:
            out.append(int(item or 0))
        except (TypeError, ValueError):
            out.append(0)
    return out
