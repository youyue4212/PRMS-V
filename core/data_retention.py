# -*- coding: utf-8 -*-
"""Cross-platform retention for Raysen data folders (Windows + Linux)."""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Only these basenames under scanned dirs
_ALLOWED_GLOBS = (
    "data_auto_*.xlsx",
    "alarm_log_*.xlsx",
    "gspc_*.bin",
    "daq_log_*.txt",
)

_MIN_KEEP_DAYS = 2
_RECENT_WRITE_SEC = 7200  # skip files touched in last 2h (likely active)
_DATE_IN_NAME = re.compile(r"20[0-9]{6}")


def raysen_root() -> Path:
    return Path.home() / "Raysen"


def keep_days_from_disk(path: Path) -> int:
    try:
        usage = shutil.disk_usage(str(path))
        if usage.total <= 0:
            return 30
        free_pct = 100.0 * usage.free / usage.total
        free_gb = usage.free / (1024 ** 3)
    except OSError:
        return 30
    if free_pct >= 50 and free_gb >= 200:
        return 180
    if free_pct >= 35 and free_gb >= 100:
        return 120
    if free_pct >= 30:
        return 90
    if free_pct >= 15:
        return 60
    return 30


def _name_date_epoch(name: str) -> Optional[float]:
    m = _DATE_IN_NAME.search(name)
    if not m:
        return None
    ymd = m.group(0)
    try:
        t = time.strptime(ymd, "%Y%m%d")
        return time.mktime(t)
    except ValueError:
        return None


def _should_delete(path: Path, cutoff_epoch: float, now: float) -> Tuple[bool, Optional[str]]:
    name = path.name
    if ".writing." in name:
        return False, None
    try:
        st = path.stat()
    except OSError:
        return False, None
    if now - st.st_mtime < _RECENT_WRITE_SEC:
        return False, None
    if st.st_mtime >= cutoff_epoch:
        return False, None
    name_epoch = _name_date_epoch(name)
    if name_epoch is None:
        return True, None
    if name_epoch >= cutoff_epoch:
        return False, None
    # If name date and mtime point to different retention decisions, keep it
    # and leave a log entry instead of deleting a possibly renamed file.
    if abs(name_epoch - st.st_mtime) > 86400:
        return False, "skip date/mtime mismatch %s" % path
    return True, None


def _scan_dir(directory: Path, cutoff_epoch: float, now: float, dry_run: bool) -> Tuple[int, List[str]]:
    deleted = 0
    lines: List[str] = []
    if not directory.is_dir():
        return 0, lines
    for pattern in _ALLOWED_GLOBS:
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            should_delete, note = _should_delete(path, cutoff_epoch, now)
            if note:
                lines.append(note)
            if not should_delete:
                continue
            if dry_run:
                lines.append("DRY-RUN delete %s" % path)
            else:
                try:
                    path.unlink()
                    lines.append("deleted %s" % path)
                except OSError as e:
                    lines.append("failed %s: %s" % (path, e))
                    continue
            deleted += 1
    return deleted, lines


def run_retention_cleanup(
    root: Optional[Path] = None,
    extra_raw_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, object]:
    """Delete old AutoSave / AlarmLogs / raw logs under Raysen. Returns summary dict."""
    base = Path(root) if root else raysen_root()
    keep = keep_days_from_disk(base if base.exists() else Path.home())
    keep = max(_MIN_KEEP_DAYS, int(keep))
    now = time.time()
    cutoff = now - keep * 86400
    total = 0
    log_lines: List[str] = []
    for sub in (base / "AutoSave", base / "AlarmLogs", base):
        n, lines = _scan_dir(sub, cutoff, now, dry_run)
        total += n
        log_lines.extend(lines)
    if extra_raw_dir:
        n, lines = _scan_dir(Path(extra_raw_dir), cutoff, now, dry_run)
        total += n
        log_lines.extend(lines)
    return {
        "root": str(base),
        "keep_days": keep,
        "deleted": total,
        "dry_run": dry_run,
        "lines": log_lines,
    }


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Raysen data retention cleanup")
    p.add_argument("--dry-run", action="store_true", help="List files only, do not delete")
    p.add_argument("--raw-dir", default="", help="Extra directory for raw packet logs")
    args = p.parse_args()
    extra = Path(args.raw_dir) if args.raw_dir else None
    out = run_retention_cleanup(extra_raw_dir=extra, dry_run=bool(args.dry_run))
    print("root=%s keep_days=%s deleted=%s" % (out["root"], out["keep_days"], out["deleted"]))
    for line in out.get("lines") or []:
        print(line)
    sys.exit(0)
