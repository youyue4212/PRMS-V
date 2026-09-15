# -*- coding: utf-8 -*-
"""Audit manifest and optional external archive copy for finalized data files."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Dict, Optional


def _to_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    return text in ("1", "true", "yes", "on", "enabled")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_part(text: str) -> str:
    raw = str(text or "").strip()
    out = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in raw)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("._") or "unknown"


def _manifest_path(root: Optional[Path] = None) -> Path:
    base = Path(root) if root else Path.home() / "Raysen"
    return base / "archive_manifest.jsonl"


def _append_manifest(record: Dict[str, object], root: Optional[Path] = None) -> None:
    path = _manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _external_target(root: Path, category: str, source: Path, mtime: float) -> Path:
    lt = time.localtime(mtime)
    directory = (
        root
        / _safe_part(category)
        / time.strftime("%Y", lt)
        / time.strftime("%m", lt)
        / time.strftime("%d", lt)
    )
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for i in range(1, 1000):
        candidate = directory / ("%s_copy%d%s" % (stem, i, suffix))
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many archive name collisions for %s" % target)


def _copy_and_verify(source: Path, target: Path, expected_sha256: str) -> Path:
    tmp = target.with_name(target.name + ".writing")
    if tmp.exists():
        tmp.unlink()
    try:
        shutil.copy2(str(source), str(tmp))
        actual = _sha256(tmp)
        if actual != expected_sha256:
            raise RuntimeError("archive hash mismatch for %s" % target)
        os.replace(str(tmp), str(target))
        return target
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def archive_file(
    source_path,
    category: str,
    metadata: Optional[Dict[str, object]] = None,
    settings: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Record a finalized file and optionally copy it to external archive storage.

    The manifest is always local. External copy is enabled only when configured.
    Failures are returned to the caller; callers should not treat archive failure
    as data-save failure.
    """
    settings = dict(settings or {})
    source = Path(source_path)
    st = source.stat()
    digest = _sha256(source)
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    machine = settings.get("machine_id") or os.environ.get("RAYSEN_MACHINE_ID")
    if not machine:
        machine = socket.gethostname() or platform.node() or "unknown"
    site = settings.get("site_id") or os.environ.get("RAYSEN_SITE_ID") or ""
    archive_root = (
        settings.get("archive_path")
        or os.environ.get("RAYSEN_ARCHIVE_DIR")
        or ""
    )
    enabled = _to_bool(
        settings.get("archive_enabled", os.environ.get("RAYSEN_ARCHIVE_ENABLED")),
        default=bool(archive_root),
    )

    record: Dict[str, object] = {
        "created_at": now_text,
        "event": "archive_record",
        "category": str(category or "data"),
        "source_path": str(source),
        "filename": source.name,
        "size": int(st.st_size),
        "mtime": float(st.st_mtime),
        "sha256": digest,
        "machine_id": str(machine),
        "site_id": str(site),
        "metadata": dict(metadata or {}),
        "archive_enabled": bool(enabled),
        "archive_status": "manifest_only",
    }

    if enabled:
        if not archive_root:
            record["archive_status"] = "failed"
            record["error"] = "archive enabled but no archive path configured"
        else:
            try:
                target = _external_target(Path(archive_root), category, source, st.st_mtime)
                archived = _copy_and_verify(source, target, digest)
                record["archive_status"] = "archived"
                record["archive_path"] = str(archived)
            except Exception as e:
                record["archive_status"] = "failed"
                record["error"] = str(e)

    try:
        _append_manifest(record)
        external_path = record.get("archive_path")
        if external_path:
            _append_manifest(record, Path(archive_root))
    except Exception as e:
        record["manifest_error"] = str(e)
    return record
