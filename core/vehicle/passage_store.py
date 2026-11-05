# -*- coding: utf-8 -*-
"""PRMS-V-11 通行记录。2B/2C 字段先留列，本阶段只写测速和 L2。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class PassageStore:
    def __init__(self, path: Path):
        self.path = Path(path)
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

    def insert(self, row: dict) -> None:
        cps = row.get("cps") or []
        self._conn.execute(
            """
            INSERT OR REPLACE INTO passage (
                passage_id, t1_ms, t2_ms, length_m, speed_kmh, v_limit_kmh,
                overspeed, decision, hit_probe_mask, cps_json,
                plate, plate_manual, image_paths, r2_on, invalid_reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
