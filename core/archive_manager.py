# -*- coding: utf-8 -*-
"""Audit manifest and optional external archive copy for finalized data files."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import shutil
import socket
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple


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


_MANIFEST_LOCK = threading.Lock()
_SOURCE_LOCKS_GUARD = threading.Lock()
_SOURCE_LOCKS: Dict[str, threading.Lock] = {}
_SKIP_INDEX: Dict[Tuple[str, str, str], str] = {}
_SKIP_META: Dict[str, Dict[str, object]] = {}
_SKIP_INDEX_SIG: Optional[Tuple[float, int]] = None
_SKIP_INDEX_PATH: Optional[str] = None
# 已写过 failed 的 (source|name, category, sha256)，避免网盘掉线时重复追加
_FAILED_LOGGED: Set[Tuple[str, str, str]] = set()
# 进程内最近一次外拷失败时刻，用于限频重试（重启后允许立刻再试）
_FAILED_ATTEMPT_AT: Dict[Tuple[str, str, str], float] = {}

_RECORDED_STATUSES = frozenset({"archived", "manifest_only"})
_MTIME_MATCH_SEC = 2.0
_FAIL_RETRY_COOLDOWN_SEC = 120.0
_MANIFEST_COMPACT_BYTES = 2 * 1024 * 1024
_MANIFEST_COMPACT_LINES = 20000
_REMOTE_INDEX: Dict[str, Set[str]] = {}
_REMOTE_INDEX_SIG: Dict[str, Optional[Tuple[float, int]]] = {}
_LOCK_BUSY_ERRNO = frozenset(
    e for e in (
        errno.EACCES,
        errno.EAGAIN,
        errno.EWOULDBLOCK,
        getattr(errno, "EDEADLK", None),
    ) if e is not None
)
_LOCK_UNSUPPORTED_ERRNO = frozenset(
    e for e in (
        errno.EINVAL,
        errno.ENOSYS,
        errno.ENOSPC,
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EDQUOT", None),
        getattr(errno, "ENOLCK", None),
    ) if e is not None
)
_LOCK_BUSY_WIN = frozenset({32, 33, 36})
# 5 = access denied (share cannot lock)
# 15 = invalid drive, 21 = device not ready (USB yanked)
# 19 = write protect, 39/112 = disk full
# 53/64/67/1231/1232 = net path gone / unreachable
_LOCK_UNSUPPORTED_WIN = frozenset({
    1, 5, 15, 19, 21, 39, 50, 53, 64, 67, 82, 87, 112, 1231, 1232,
})


def _norm_source(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _named_lock(key: str) -> threading.Lock:
    with _SOURCE_LOCKS_GUARD:
        lock = _SOURCE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SOURCE_LOCKS[key] = lock
        return lock


def _file_sig(path: Path) -> Optional[Tuple[float, int]]:
    try:
        if not path.exists():
            return None
        st = path.stat()
        return (float(st.st_mtime), int(st.st_size))
    except OSError:
        return None


def _sidecar_lock_path(target: Path) -> Path:
    return Path(str(target) + ".lock")


def _lock_error_kind(exc: BaseException) -> str:
    winerr = getattr(exc, "winerror", None)
    errn = getattr(exc, "errno", None)
    if winerr in _LOCK_UNSUPPORTED_WIN or errn in _LOCK_UNSUPPORTED_ERRNO:
        return "unsupported"
    if winerr in _LOCK_BUSY_WIN or errn in _LOCK_BUSY_ERRNO:
        return "busy"
    if os.name == "nt":
        return "busy"
    return "unsupported"


def _try_acquire_fd(fh) -> None:
    if os.name == "nt":
        import msvcrt
        fh.seek(0, os.SEEK_END)
        if fh.tell() < 1:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_fd(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def _process_lock(lock_path: Path, timeout: float = 60.0) -> Iterator[None]:
    """Cross-process lock. If the filesystem cannot lock, continue with thread locks."""
    lock_path = Path(lock_path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(str(lock_path), "a+b")
    except OSError:
        yield
        return
    locked = False
    start = time.time()
    try:
        while True:
            try:
                _try_acquire_fd(fh)
                locked = True
                break
            except OSError as exc:
                kind = _lock_error_kind(exc)
                if kind == "unsupported":
                    break
                if (time.time() - start) >= float(timeout):
                    raise RuntimeError("timeout waiting for lock %s" % lock_path) from exc
                time.sleep(0.05)
        yield
    finally:
        if locked:
            _release_fd(fh)
        try:
            fh.close()
        except OSError:
            pass


def _local_manifest_process_lock(timeout: float = 60.0) -> Iterator[None]:
    return _process_lock(_sidecar_lock_path(_manifest_path()), timeout=timeout)


def _write_manifest_line(path: Path, record: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()


def _manifest_record_key(filename: str, category: str, digest: str) -> str:
    return "%s|%s|%s" % (filename, category, digest)


def _fail_key(source: str, filename: str, category: str, digest: str) -> Tuple[str, str, str]:
    return _skip_key(str(source or ""), str(filename or ""), str(category or ""), str(digest or ""))


def _record_fail_key(record: Dict[str, object]) -> Tuple[str, str, str]:
    return _fail_key(
        str(record.get("source_path") or ""),
        str(record.get("filename") or ""),
        str(record.get("category") or ""),
        str(record.get("sha256") or ""),
    )


def _remember_failed(record: Dict[str, object]) -> None:
    key = _record_fail_key(record)
    _FAILED_LOGGED.add(key)
    _FAILED_ATTEMPT_AT[key] = time.time()


def _clear_failed(record: Dict[str, object]) -> None:
    key = _record_fail_key(record)
    _FAILED_LOGGED.discard(key)
    _FAILED_ATTEMPT_AT.pop(key, None)


def _should_write_failed(record: Dict[str, object]) -> bool:
    """同一文件同一 hash 只落一条 failed；仍返回失败给调用方，外拷按冷却重试。"""
    key = _record_fail_key(record)
    if not key[2]:
        return True
    return key not in _FAILED_LOGGED


def _failed_retry_blocked(source: Path, category: str, digest: str) -> bool:
    if not digest:
        return False
    key = _fail_key(str(source), source.name, category, digest)
    ts = _FAILED_ATTEMPT_AT.get(key)
    if ts is None:
        return False
    return (time.time() - float(ts)) < float(_FAIL_RETRY_COOLDOWN_SEC)


def _status_rank(status: str) -> int:
    if status == "archived":
        return 2
    if status == "manifest_only":
        return 1
    return 0


def _compact_manifest_locked(path: Path) -> bool:
    """Keep latest successful row per source/name/category/sha256; drop failed noise.

    Caller must hold the local manifest process lock (+ thread lock when from archive_file).
    """
    global _FAILED_LOGGED
    if not path.exists():
        return False
    try:
        size = int(path.stat().st_size)
    except OSError:
        return False
    if size < int(_MANIFEST_COMPACT_BYTES):
        return False

    best: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    line_count = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line_count += 1
                text = line.strip()
                if not text:
                    continue
                try:
                    rec = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "archive_record":
                    continue
                status = str(rec.get("archive_status") or "")
                if status not in _RECORDED_STATUSES:
                    continue
                digest = str(rec.get("sha256") or "")
                if not digest:
                    continue
                key = _fail_key(
                    str(rec.get("source_path") or ""),
                    str(rec.get("filename") or ""),
                    str(rec.get("category") or ""),
                    digest,
                )
                prev = best.get(key)
                if prev is None or _status_rank(status) >= _status_rank(str(prev.get("archive_status") or "")):
                    best[key] = rec
    except OSError:
        return False

    # 行数不多且没有可丢掉的噪音时不动盘
    if line_count < int(_MANIFEST_COMPACT_LINES) and line_count <= len(best):
        return False
    if line_count <= len(best):
        return False

    tmp = path.with_name(path.name + ".compacting")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for rec in best.values():
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False
    # 不在这里清 _FAILED_LOGGED：压缩会丢掉磁盘上的 failed 行，
    # 进程内去重记忆要留给 _rebuild_skip_index 与 _FAILED_ATTEMPT_AT 合并保留。
    return True


def _maybe_compact_manifest_locked(path: Path) -> bool:
    """Return True when the on-disk manifest was rewritten."""
    return _compact_manifest_locked(path)


def _scan_manifest_keys(path: Path) -> Set[str]:
    keys: Set[str] = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") != "archive_record":
                continue
            status = str(rec.get("archive_status") or "")
            digest = str(rec.get("sha256") or "")
            if status not in _RECORDED_STATUSES or not digest:
                continue
            keys.add(_manifest_record_key(
                str(rec.get("filename") or ""),
                str(rec.get("category") or ""),
                digest,
            ))
    return keys


def _remote_keys_locked(archive_root: str, path: Path) -> Set[str]:
    sig = _file_sig(path)
    if archive_root in _REMOTE_INDEX and _REMOTE_INDEX_SIG.get(archive_root) == sig:
        return _REMOTE_INDEX[archive_root]
    keys = _scan_manifest_keys(path)
    _REMOTE_INDEX[archive_root] = keys
    _REMOTE_INDEX_SIG[archive_root] = sig
    return keys


def _remember_remote_key(archive_root: str, path: Path, key: str) -> None:
    keys = _REMOTE_INDEX.setdefault(archive_root, set())
    keys.add(key)
    _REMOTE_INDEX_SIG[archive_root] = _file_sig(path)


def _remote_payload(record: Dict[str, object]) -> Dict[str, object]:
    payload = dict(record)
    prior = str(payload.get("prior_status") or "")
    if str(payload.get("archive_status") or "") == "already_recorded":
        payload["archive_status"] = prior or "archived"
        payload.pop("prior_status", None)
    return payload


def _ensure_remote_record(record: Dict[str, object], archive_root: str) -> None:
    if not archive_root:
        return
    payload = _remote_payload(record)
    if str(payload.get("archive_status") or "") != "archived":
        return
    digest = str(payload.get("sha256") or "")
    if not digest:
        return
    key = _manifest_record_key(
        str(payload.get("filename") or ""),
        str(payload.get("category") or ""),
        digest,
    )
    path = _manifest_path(Path(archive_root))
    with _remote_manifest_lock(archive_root):
        with _process_lock(_sidecar_lock_path(path)):
            keys = _remote_keys_locked(archive_root, path)
            if key in keys:
                return
            _write_manifest_line(path, payload)
            _remember_remote_key(archive_root, path, key)


def _dest_directory(root: Path, category: str, mtime: float) -> Path:
    lt = time.localtime(mtime)
    return (
        root
        / _safe_part(category)
        / time.strftime("%Y", lt)
        / time.strftime("%m", lt)
        / time.strftime("%d", lt)
    )


def _norm_root(root: str) -> str:
    """Stabilize archive root spelling without Path.resolve().

    resolve() on a mapped/UNC path can hang for minutes when the share is down.
    Trailing slashes and slash direction are normalized so D:\\archive, D:/archive/
    and D:\\archive\\ share the same dest/remote locks.
    """
    text = str(root or "").strip()
    if not text:
        return ""
    if os.name == "nt":
        text = text.replace("/", "\\")
        if len(text) >= 2 and text[1] == ":":
            text = text[0].upper() + text[1:]
    text = os.path.normpath(text)
    if os.name == "nt" and len(text) == 2 and text[1] == ":":
        return text + "\\"
    return text


def _source_lock(path: Path) -> threading.Lock:
    """同一本地文件的检查/外拷/写 manifest 串行。"""
    return _named_lock("src:" + _norm_source(path))


def _dest_dir_lock(archive_root: str, category: str, mtime: float) -> threading.Lock:
    """同一外部日期目录串行，覆盖 canonical 名和 _copyN，避免互抢。"""
    lt = time.localtime(mtime)
    key = "dstdir:%s|%s|%s/%s/%s" % (
        _norm_root(archive_root),
        category,
        time.strftime("%Y", lt),
        time.strftime("%m", lt),
        time.strftime("%d", lt),
    )
    return _named_lock(key)


def _remote_manifest_lock(archive_root: str) -> threading.Lock:
    return _named_lock("rmanifest:" + _norm_root(archive_root))


def _skip_key(source_path: str, filename: str, category: str, digest: str) -> Tuple[str, str, str]:
    return ("%s|%s" % (source_path, filename), str(category or ""), str(digest or ""))


def _path_meta_keys(source: Path, category: str) -> Tuple[str, ...]:
    src = _norm_source(source) if isinstance(source, Path) else str(source)
    raw = str(source) if isinstance(source, Path) else str(source)
    cat = str(category or "")
    keys = []
    if src:
        keys.append("p:%s|%s" % (src, cat))
    if raw and raw != src:
        keys.append("p:%s|%s" % (raw, cat))
    return tuple(keys)


def _remember_meta(record: Dict[str, object]) -> None:
    status = str(record.get("archive_status") or "")
    if status not in _RECORDED_STATUSES:
        return
    category = str(record.get("category") or "")
    source = str(record.get("source_path") or "")
    info = {
        "status": status,
        "size": int(record.get("size") or 0),
        "mtime": float(record.get("mtime") or 0.0),
        "sha256": str(record.get("sha256") or ""),
    }
    dummy = Path(source) if source else Path(str(record.get("filename") or "unknown"))
    for key in _path_meta_keys(dummy, category):
        _SKIP_META[key] = info
    if source:
        _SKIP_META["p:%s|%s" % (source, category)] = info


def _rebuild_skip_index(manifest: Path) -> None:
    global _SKIP_INDEX, _SKIP_META, _SKIP_INDEX_SIG, _SKIP_INDEX_PATH, _FAILED_LOGGED
    index: Dict[Tuple[str, str, str], str] = {}
    meta: Dict[str, Dict[str, object]] = {}
    failed: Set[Tuple[str, str, str]] = set()
    cleared: Set[Tuple[str, str, str]] = set()
    try:
        with manifest.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "archive_record":
                    continue
                digest = str(rec.get("sha256") or "")
                status = str(rec.get("archive_status") or "")
                category = str(rec.get("category") or "")
                filename = str(rec.get("filename") or "")
                source = str(rec.get("source_path") or "")
                if status == "failed" and digest:
                    failed.add(_fail_key(source, filename, category, digest))
                    continue
                if status in _RECORDED_STATUSES:
                    if digest:
                        if source:
                            index[_skip_key(source, filename, category, digest)] = status
                        if filename:
                            index[_skip_key("", filename, category, digest)] = status
                        fk = _fail_key(source, filename, category, digest)
                        failed.discard(fk)
                        cleared.add(fk)
                    info = {
                        "status": status,
                        "size": int(rec.get("size") or 0),
                        "mtime": float(rec.get("mtime") or 0.0),
                        "sha256": digest,
                    }
                    if source:
                        meta["p:%s|%s" % (source, category)] = info
        _SKIP_INDEX = index
        _SKIP_META = meta
        # 压缩可能删掉磁盘 failed；合并本进程记忆，且去掉已成功入账的 key
        _FAILED_LOGGED = (failed | set(_FAILED_ATTEMPT_AT.keys()) | _FAILED_LOGGED) - cleared
        for fk in cleared:
            _FAILED_ATTEMPT_AT.pop(fk, None)
        _SKIP_INDEX_SIG = _file_sig(manifest)
        _SKIP_INDEX_PATH = str(manifest)
    except OSError:
        _SKIP_INDEX = {}
        _SKIP_META = {}
        _FAILED_LOGGED = set(_FAILED_ATTEMPT_AT.keys()) | _FAILED_LOGGED
        _SKIP_INDEX_SIG = None
        _SKIP_INDEX_PATH = str(manifest)


def _ensure_skip_index() -> None:
    global _SKIP_INDEX_SIG, _SKIP_INDEX_PATH
    manifest = _manifest_path()
    sig = _file_sig(manifest)
    path_text = str(manifest)
    if (
        _SKIP_INDEX_PATH != path_text
        or sig is None
        or _SKIP_INDEX_SIG is None
        or sig != _SKIP_INDEX_SIG
    ):
        if manifest.exists():
            _maybe_compact_manifest_locked(manifest)
            _rebuild_skip_index(manifest)
        else:
            _SKIP_INDEX.clear()
            _SKIP_META.clear()
            _SKIP_INDEX_SIG = None
            _SKIP_INDEX_PATH = path_text


def _status_still_done(status: str, want_external: bool) -> bool:
    if status == "archived":
        return True
    if status == "manifest_only" and not want_external:
        return True
    return False


def _unchanged_recorded(source: Path, category: str, size: int, mtime: float,
                        want_external: bool) -> Optional[Tuple[str, str]]:
    """Skip hashing when the same path + size + mtime already match a finished record.

    不用文件名做快查：同名不同路径的文件可能大小/mtime 碰巧接近，会误跳过。
    Returns (status, sha256) when a finished record matches.
    """
    _ensure_skip_index()
    for key in _path_meta_keys(source, category):
        info = _SKIP_META.get(key)
        if not info:
            continue
        stored_size = info.get("size")
        if stored_size is None:
            continue
        try:
            if int(stored_size) != int(size):
                continue
        except (TypeError, ValueError):
            continue
        try:
            stored_mtime = float(info.get("mtime"))
        except (TypeError, ValueError):
            continue
        if abs(stored_mtime - float(mtime)) > _MTIME_MATCH_SEC:
            continue
        status = str(info.get("status") or "")
        if _status_still_done(status, want_external):
            return status, str(info.get("sha256") or "")
    return None


def _recorded_status(source: Path, digest: str, category: str) -> Optional[str]:
    _ensure_skip_index()
    src = _norm_source(source)
    name = source.name
    cat = str(category or "")
    for key in (
        _skip_key(src, name, cat, digest),
        _skip_key(str(source), name, cat, digest),
        _skip_key("", name, cat, digest),
    ):
        status = _SKIP_INDEX.get(key)
        if status in _RECORDED_STATUSES:
            return status
    return None


def _remember_record(record: Dict[str, object]) -> None:
    digest = str(record.get("sha256") or "")
    category = str(record.get("category") or "")
    filename = str(record.get("filename") or "")
    source = str(record.get("source_path") or "")
    status = str(record.get("archive_status") or "")
    if digest and status in _RECORDED_STATUSES:
        if source:
            _SKIP_INDEX[_skip_key(source, filename, category, digest)] = status
        if filename:
            _SKIP_INDEX[_skip_key("", filename, category, digest)] = status
    _remember_meta(record)


def _refresh_skip_mtime() -> None:
    global _SKIP_INDEX_SIG, _SKIP_INDEX_PATH
    manifest = _manifest_path()
    _SKIP_INDEX_SIG = _file_sig(manifest)
    _SKIP_INDEX_PATH = str(manifest)


def _append_manifest(record: Dict[str, object], root: Optional[Path] = None) -> None:
    path = _manifest_path(root)
    with _process_lock(_sidecar_lock_path(path)):
        _write_manifest_line(path, record)


def _external_target(root: Path, category: str, source: Path, mtime: float,
                     digest: str = "") -> Path:
    directory = _dest_directory(root, category, mtime)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    if not target.exists():
        return target
    if digest:
        try:
            if _sha256(target) == digest:
                return target
        except OSError:
            pass
    stem = target.stem
    suffix = target.suffix
    for i in range(1, 1000):
        candidate = directory / ("%s_copy%d%s" % (stem, i, suffix))
        if not candidate.exists():
            return candidate
        if digest:
            try:
                if _sha256(candidate) == digest:
                    return candidate
            except OSError:
                pass
    raise RuntimeError("Too many archive name collisions for %s" % target)


def _copy_and_verify(source: Path, target: Path, expected_sha256: str) -> Path:
    if target.exists():
        try:
            if _sha256(target) == expected_sha256:
                return target
        except OSError:
            pass
        raise RuntimeError("archive target exists with different hash: %s" % target)
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

    同一 ``source_path``/文件名 + ``sha256`` 若已成功入账（archived / manifest_only），
    不再追加第二行，也不再复制。记录格式不变。上次失败的会按冷却重试外拷，
    但同 key 的 failed 行只写一次，避免网盘掉线时撑爆 manifest。
    """
    settings = dict(settings or {})
    source = Path(source_path)
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
    if archive_root:
        archive_root = _norm_root(str(archive_root))
    enabled = _to_bool(
        settings.get("archive_enabled", os.environ.get("RAYSEN_ARCHIVE_ENABLED")),
        default=bool(archive_root),
    )
    category_text = str(category or "data")
    want_external = bool(enabled and archive_root)

    with _source_lock(source):
        st = source.stat()

        def _skip_record(prior: str, digest: str = "") -> Dict[str, object]:
            return {
                "created_at": now_text,
                "event": "archive_record",
                "category": category_text,
                "source_path": str(source),
                "filename": source.name,
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
                "sha256": digest,
                "machine_id": str(machine),
                "site_id": str(site),
                "metadata": dict(metadata or {}),
                "archive_enabled": bool(enabled),
                "archive_status": "already_recorded",
                "prior_status": prior,
            }

        local_path = _manifest_path()
        with _MANIFEST_LOCK:
            with _local_manifest_process_lock():
                prior = _unchanged_recorded(
                    source, category_text, int(st.st_size), float(st.st_mtime), want_external
                )
        if prior:
            prior_status, prior_digest = prior
            skipped = _skip_record(prior_status, prior_digest)
            if want_external and prior_status == "archived":
                try:
                    if not skipped.get("sha256"):
                        skipped["sha256"] = _sha256(source)
                    _ensure_remote_record(skipped, str(archive_root))
                except Exception as e:
                    skipped["manifest_error"] = str(e)
            return skipped

        digest = _sha256(source)
        st_after = source.stat()
        if int(st_after.st_size) != int(st.st_size):
            digest = _sha256(source)
            st = source.stat()
        else:
            st = st_after
        record: Dict[str, object] = {
            "created_at": now_text,
            "event": "archive_record",
            "category": category_text,
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

        with _MANIFEST_LOCK:
            with _local_manifest_process_lock():
                already = _recorded_status(source, digest, category_text)
        if already and _status_still_done(already, want_external):
            skipped = _skip_record(already, digest)
            if want_external and already == "archived":
                try:
                    _ensure_remote_record(skipped, str(archive_root))
                except Exception as e:
                    skipped["manifest_error"] = str(e)
            return skipped

        if want_external and _failed_retry_blocked(source, category_text, digest):
            blocked = dict(record)
            blocked["archive_status"] = "failed"
            blocked["error"] = "retry cooldown after previous archive failure"
            return blocked

        dest_lock = (
            _dest_dir_lock(str(archive_root), category_text, float(st.st_mtime))
            if want_external else None
        )
        dest_dir_path = (
            _dest_directory(Path(archive_root), category_text, float(st.st_mtime))
            if want_external else None
        )
        if dest_dir_path is not None:
            dest_dir_path.mkdir(parents=True, exist_ok=True)
        if dest_lock is not None:
            dest_lock.acquire()
        local_ok = False
        skipped_out = None
        try:
            dest_proc = (
                _process_lock(dest_dir_path / ".archive_dir.lock", timeout=300.0)
                if dest_dir_path is not None else None
            )
            dest_entered = False
            try:
                if dest_proc is not None:
                    dest_proc.__enter__()
                    dest_entered = True
                if want_external:
                    try:
                        target = _external_target(
                            Path(archive_root), category_text, source, st.st_mtime, digest
                        )
                        archived = _copy_and_verify(source, target, digest)
                        record["archive_status"] = "archived"
                        record["archive_path"] = str(archived)
                    except Exception as e:
                        record["archive_status"] = "failed"
                        record["error"] = str(e)
                elif enabled and not archive_root:
                    record["archive_status"] = "failed"
                    record["error"] = "archive enabled but no archive path configured"

                with _MANIFEST_LOCK:
                    with _local_manifest_process_lock():
                        _ensure_skip_index()
                        already = _recorded_status(source, digest, category_text)
                        new_status = str(record.get("archive_status") or "")
                        if already == "archived":
                            skipped_out = _skip_record(already, digest)
                        elif already == "manifest_only" and new_status == "manifest_only":
                            skipped_out = _skip_record(already, digest)
                        elif new_status == "failed" and not _should_write_failed(record):
                            # 已有同 key failed 行：更新限频时钟，不再追加
                            _remember_failed(record)
                        else:
                            try:
                                _write_manifest_line(local_path, record)
                                if new_status == "failed":
                                    _remember_failed(record)
                                else:
                                    _remember_record(record)
                                    _clear_failed(record)
                                _refresh_skip_mtime()
                                if _maybe_compact_manifest_locked(local_path):
                                    _rebuild_skip_index(local_path)
                                local_ok = new_status in _RECORDED_STATUSES
                            except Exception as e:
                                record["manifest_error"] = str(e)
            finally:
                if dest_proc is not None and dest_entered:
                    dest_proc.__exit__(None, None, None)
        finally:
            if dest_lock is not None:
                dest_lock.release()
        if skipped_out is not None:
            if want_external and str(skipped_out.get("prior_status") or "") == "archived":
                try:
                    _ensure_remote_record(skipped_out, str(archive_root))
                except Exception as e:
                    skipped_out["manifest_error"] = str(e)
            return skipped_out
        if local_ok:
            try:
                _ensure_remote_record(record, str(archive_root) if want_external else "")
            except Exception as e:
                record["manifest_error"] = str(e)
        return record









