# -*- coding: utf-8 -*-
"""口岸级通行证据包：manifest + 影像 + 辐射摘要，目录或 zip。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from core.vehicle.evidence_assets import EVIDENCE_ROLES, parse_image_paths
from core.vehicle.passage_store import vehicle_passage_document


def _site_meta(config) -> tuple[str, str, str]:
    site = str(getattr(config, "archive_site_id", "") or "").strip()
    machine = str(getattr(config, "archive_machine_id", "") or "").strip()
    lane = "03"
    return site, machine, lane


def evidence_root(capture_dir: Path) -> Path:
    return Path(capture_dir).expanduser() / "evidence"


def _bundle_relpath(role: str, src: Path) -> str:
    if role == "video":
        ext = (src.suffix or ".mp4").lower()
        if ext not in (".mp4", ".avi", ".mkv"):
            ext = ".mp4"
        return "video/alarm_clip%s" % ext
    return "images/%s.jpg" % role


def build_manifest(row: dict, config=None, label_for_slot=None) -> dict:
    site, machine, lane = _site_meta(config) if config is not None else ("", "", "03")
    doc = vehicle_passage_document(row, label_for_slot=label_for_slot)
    assets = parse_image_paths(str(row.get("image_paths") or ""))
    files = []
    for role in EVIDENCE_ROLES:
        src = assets.get(role)
        if src:
            files.append(
                {"role": role, "path": src, "file": _bundle_relpath(role, Path(src))}
            )
    manifest = {
        "schema": "PRMS-V/evidence/1.1",
        "clip_seconds": {"pre": 5, "post": 5, "total_target": 10},
        "episode_id": str(row.get("passage_id") or ""),
        "site_id": site,
        "machine_id": machine,
        "lane_id": lane,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": doc.get("status"),
        "hard_alarm": bool(row.get("hard_alarm")),
        "decision_code": int(row.get("decision") or 0),
        "plate": str(row.get("plate") or ""),
        "plate_manual": bool(str(row.get("plate_manual") or "").strip()),
        "speed_kmh": row.get("speed_kmh"),
        "v_limit_kmh": row.get("v_limit_kmh"),
        "overspeed": bool(row.get("overspeed")),
        "opened_at": row.get("opened_at"),
        "closed_at": row.get("closed_at"),
        "t1_ms": row.get("t1_ms"),
        "t2_ms": row.get("t2_ms"),
        "invalid_reason": str(row.get("invalid_reason") or ""),
        "probe_peak_cps": [int(v or 0) for v in list(row.get("peak_cps") or row.get("cps") or [])],
        "probe_trigger_cps": [int(v or 0) for v in list(row.get("trigger_cps") or [])],
        "hit_probe_mask": int(row.get("hit_probe_mask") or 0),
        "files": files,
        "passage_document": doc,
    }
    return manifest


def export_passage_evidence(
    row: dict,
    config=None,
    label_for_slot=None,
    as_zip: bool = True,
) -> Path | None:
    """报警或有效硬报趟次落库后写出 evidence/{passage_id}/。"""
    if not row:
        return None
    invalid = str(row.get("invalid_reason") or "").strip()
    hard = bool(row.get("hard_alarm")) or int(row.get("decision") or 0) in (0x02, 0x03)
    if invalid or not hard:
        return None

    cap_raw = str(getattr(config, "vehicle_capture_dir", "") or "").strip() if config else ""
    cap_dir = Path(cap_raw).expanduser() if cap_raw else Path.home() / "daq_tablet" / "vehicle_captures"
    pid = str(row.get("passage_id") or "").replace("/", "-").replace("\\", "-")
    if not pid:
        return None

    bundle_dir = evidence_root(cap_dir) / pid
    images_dir = bundle_dir / "images"
    video_dir = bundle_dir / "video"
    images_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    assets = parse_image_paths(str(row.get("image_paths") or ""))
    copied = {}
    for role in EVIDENCE_ROLES:
        src = assets.get(role)
        if not src:
            continue
        sp = Path(src)
        if not sp.is_file():
            continue
        if role == "video":
            dest = video_dir / ("alarm_clip%s" % (sp.suffix.lower() or ".mp4"))
        else:
            dest = images_dir / ("%s.jpg" % role)
        try:
            shutil.copy2(sp, dest)
            copied[role] = str(dest)
        except OSError:
            continue

    manifest = build_manifest(row, config=config, label_for_slot=label_for_slot)
    manifest["files"] = [
        {
            "role": r,
            "path": assets.get(r, ""),
            "file": _bundle_relpath(r, Path(assets.get(r, "") or "x.mp4")),
        }
        for r in EVIDENCE_ROLES
        if r in copied
    ]
    rad = {
        "episode_id": manifest["episode_id"],
        "peak_cps": manifest["probe_peak_cps"],
        "trigger_cps": manifest["probe_trigger_cps"],
        "decision_code": manifest["decision_code"],
        "hard_alarm": manifest["hard_alarm"],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (bundle_dir / "radiation.json").write_text(
        json.dumps(rad, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    readme = (
        "PRMS-V 车辆通道证据包\n"
        "episode_id: %s\n"
        "images/: entry alarm exit plate\n"
        "video/alarm_clip.mp4  hard-alarm ~10s (5s pre + 5s post)\n"
        "manifest.json / radiation.json\n"
    ) % manifest["episode_id"]
    (bundle_dir / "README.txt").write_text(readme, encoding="utf-8")

    if not as_zip:
        return bundle_dir

    zip_base = str(bundle_dir)
    archive = shutil.make_archive(zip_base, "zip", root_dir=bundle_dir)
    return Path(archive)
