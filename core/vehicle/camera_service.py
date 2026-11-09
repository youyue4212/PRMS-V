# -*- coding: utf-8 -*-
"""车辆通道相机：硬报沿抓拍、相机识牌写入 Passage。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional
from urllib.error import HTTPError, URLError

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from core.vehicle.alarm_clip_recorder import AlarmClipRecorder
from core.vehicle.camera_config import VehicleCameraConfig
from core.vehicle.evidence_assets import append_image_path, path_for_role
from core.vehicle.hik_isapi import fetch_isapi_snapshot
from core.vehicle.passage_fsm import Passage
from core.vehicle.plate_http_server import PlateHttpServer
from core.vehicle.rtsp_preview import normalize_rtsp_url


class _SnapshotWorker(QObject):
    done = pyqtSignal(str, str)
    failed = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._config = VehicleCameraConfig()
        self._passage_id = ""
        self._role = "alarm"
        self._fallback = None

    def configure(self, config: VehicleCameraConfig, passage_id: str, role: str, fallback):
        self._config = config
        self._passage_id = str(passage_id or "")
        self._role = str(role or "alarm").strip().lower() or "alarm"
        self._fallback = fallback

    def run(self):
        pid = self._passage_id
        if not pid:
            self.failed.emit("", "no_passage_id")
            return
        blob = None
        err = ""
        try:
            blob = fetch_isapi_snapshot(self._config)
        except (OSError, URLError, HTTPError) as exc:
            err = str(exc)
        except Exception as exc:
            err = str(exc)
        if blob is None and callable(self._fallback):
            try:
                blob = self._fallback()
            except Exception as exc:
                err = err or str(exc)
        if not blob:
            self.failed.emit(pid, err or "snapshot_empty")
            return
        try:
            out_dir = Path(self._config.capture_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            role = self._role or "alarm"
            name = "%s_%s_%d.jpg" % (
                role,
                pid.replace("/", "-"),
                int(time.time() * 1000),
            )
            path = out_dir / name
            path.write_bytes(blob)
            self.done.emit(pid, str(path))
        except OSError as exc:
            self.failed.emit(pid, str(exc))


class VehicleCameraService(QObject):
    capture_done = pyqtSignal(str, str)
    capture_failed = pyqtSignal(str, str)
    plate_ingested = pyqtSignal(str, str)
    plate_http_listening = pyqtSignal(int)
    plate_http_error = pyqtSignal(str)
    plate_http_raw = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = VehicleCameraConfig()
        self._plate_http_sig = None
        self._get_open_passage: Optional[Callable[[], Passage | None]] = None
        self._pending: set[str] = set()
        self._snap_queue: list[tuple[str, str]] = []
        self._thread: QThread | None = None
        self._worker: _SnapshotWorker | None = None
        self._rtsp_fallback: Optional[Callable[[], bytes | None]] = None
        self._plate_http: PlateHttpServer | None = None
        self._vehicle_channel_on: Callable[[], bool] = lambda: True
        self._clip = AlarmClipRecorder(self)
        self._clip.clip_ready.connect(self._on_clip_ready)
        self._clip.clip_failed.connect(self._on_clip_failed)

    def set_passage_accessor(self, fn: Callable[[], Passage | None]):
        self._get_open_passage = fn

    def set_rtsp_fallback(self, fn: Callable[[], bytes | None] | None):
        self._rtsp_fallback = fn

    def set_vehicle_channel_gate(self, fn: Callable[[], bool] | None):
        self._vehicle_channel_on = fn or (lambda: True)

    def reload_config(self, config: VehicleCameraConfig):
        self._config = config
        self._clip.set_capture_dir(config.capture_dir)
        self._sync_plate_http()

    def _plate_http_signature(self) -> tuple:
        c = self._config
        return (
            bool(c.plate_http_enabled),
            str(c.plate_http_host or "0.0.0.0"),
            int(c.plate_http_port or 8236),
            bool(self._vehicle_channel_on()),
        )

    def sync_rtsp_buffer(self, url: str):
        self._clip.set_capture_dir(self._config.capture_dir)
        self._clip.set_rtsp_url(normalize_rtsp_url(url))

    def shutdown(self):
        self._clip.stop_buffer()
        if self._plate_http is not None:
            self._plate_http.stop()
            self._plate_http = None
        self._plate_http_sig = None

    def plate_http_port(self) -> int:
        if self._plate_http is not None and self._plate_http.running():
            return self._plate_http.listen_port()
        return int(self._config.plate_http_port or 0)

    def _sync_plate_http(self):
        sig = self._plate_http_signature()
        if (
            self._plate_http_sig == sig
            and self._plate_http is not None
            and self._plate_http.running()
        ):
            return
        if self._plate_http is None:
            self._plate_http = PlateHttpServer(self)
            self._plate_http.plate_received.connect(self._on_http_plate)
            self._plate_http.listen_failed.connect(self.plate_http_error.emit)
        self._plate_http.stop()
        self._plate_http_sig = None
        if not self._config.plate_http_enabled:
            return
        if not self._vehicle_channel_on():
            return
        self._plate_http.start(
            self._config.plate_http_host or "0.0.0.0",
            int(self._config.plate_http_port or 8236),
        )
        if self._plate_http.running():
            self._plate_http_sig = sig
            self.plate_http_listening.emit(self._plate_http.listen_port())

    def _on_http_plate(self, plate: str, remote: str, image=None):
        self.plate_http_raw.emit(str(plate or ""), remote)
        row = self._resolve_passage(None)
        img = image if isinstance(image, (bytes, bytearray)) else None
        if row is not None and img:
            self._save_plate_image(row, bytes(img))
        text = str(plate or "").strip()
        if not text:
            if img:
                return
            self.plate_http_error.emit("parse_empty")
            return
        if not self.ingest_plate(text):
            self.plate_http_error.emit("no_open_passage_or_manual_plate")

    def _save_plate_image(self, row: Passage, blob: bytes):
        if not blob or row is None:
            return
        if path_for_role(row.image_paths, "plate"):
            return
        try:
            out_dir = Path(self._config.capture_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            pid = str(row.passage_id or "").replace("/", "-")
            path = out_dir / ("plate_%s_%d.jpg" % (pid, int(time.time() * 1000)))
            path.write_bytes(blob)
            row.image_paths = append_image_path(row.image_paths, "plate", str(path))
            self.capture_done.emit(str(row.passage_id or ""), str(path))
        except OSError:
            pass

    def on_passage_entry(self, passage: Passage):
        self._enqueue_snapshot(passage, "entry")

    def on_hard_alarm_edge(self, passage: Passage):
        self._enqueue_snapshot(passage, "alarm")
        if passage is not None and not path_for_role(passage.image_paths, "video"):
            self._clip.trigger_clip(str(passage.passage_id or ""))

    def on_passage_closed(self, passage: Passage):
        if passage is None:
            return
        if str(passage.invalid_reason or "").strip():
            return
        self._enqueue_snapshot(passage, "exit")
        if passage.hard_alarm and not path_for_role(passage.image_paths, "alarm"):
            self._enqueue_snapshot(passage, "alarm")

    def _enqueue_snapshot(self, passage: Passage | None, role: str):
        if passage is None or not self._config.snapshot_enabled():
            return
        pid = str(passage.passage_id or "")
        role = str(role or "alarm").strip().lower() or "alarm"
        if not pid:
            return
        key = "%s:%s" % (pid, role)
        if key in self._pending:
            return
        if path_for_role(passage.image_paths, role):
            return
        self._pending.add(key)
        self._snap_queue.append((pid, role))
        self._pump_worker()

    def ingest_plate(self, plate: str, passage_id: str | None = None) -> bool:
        text = str(plate or "").strip()
        if not text:
            return False
        row = self._resolve_passage(passage_id)
        if row is None:
            return False
        if row.plate_manual and str(row.plate or "").strip():
            return False
        row.plate = text
        self.plate_ingested.emit(str(row.passage_id or ""), text)
        return True

    def _resolve_passage(self, passage_id: str | None) -> Passage | None:
        fn = self._get_open_passage
        if fn is None:
            return None
        open_row = fn()
        if open_row is None:
            return None
        if passage_id and str(open_row.passage_id) != str(passage_id):
            return None
        return open_row

    def _pump_worker(self):
        if self._thread is not None and self._thread.isRunning():
            return
        if not self._snap_queue:
            return
        pid, role = self._snap_queue.pop(0)
        self._start_worker(pid, role)

    def _start_worker(self, passage_id: str, role: str):
        if self._thread is not None and self._thread.isRunning():
            self._snap_queue.insert(0, (passage_id, role))
            return
        self._thread = QThread(self)
        self._worker = _SnapshotWorker()
        self._worker.moveToThread(self._thread)
        fb = self._rtsp_fallback
        self._worker.configure(self._config, passage_id, role, fb)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._on_worker_finished)
        self._active_role = role
        self._thread.start()

    def _on_worker_finished(self):
        self._thread = None
        self._worker = None
        self._pump_worker()

    def _on_done(self, passage_id: str, path: str):
        role = getattr(self, "_active_role", "alarm")
        self._pending.discard("%s:%s" % (passage_id, role))
        row = self._resolve_passage_for_id(passage_id)
        if row is not None:
            row.image_paths = append_image_path(row.image_paths, role, path)
        closed = self._resolve_closed_passage(passage_id)
        if closed is not None and closed is not row:
            closed.image_paths = append_image_path(closed.image_paths, role, path)
        self.capture_done.emit(passage_id, path)

    def _on_failed(self, passage_id: str, reason: str):
        role = getattr(self, "_active_role", "alarm")
        self._pending.discard("%s:%s" % (passage_id, role))
        self.capture_failed.emit(passage_id, reason)

    def _resolve_passage_for_id(self, passage_id: str) -> Passage | None:
        open_row = self._resolve_passage(passage_id)
        if open_row is not None:
            return open_row
        return self._resolve_closed_passage(passage_id)

    def _on_clip_ready(self, passage_id: str, path: str):
        role = "video"
        self._pending.discard("%s:%s" % (passage_id, role))
        row = self._resolve_passage_for_id(passage_id)
        if row is not None:
            row.image_paths = append_image_path(row.image_paths, role, path)
        closed = self._resolve_closed_passage(passage_id)
        if closed is not None and closed is not row:
            closed.image_paths = append_image_path(closed.image_paths, role, path)
        self.capture_done.emit(passage_id, path)

    def _on_clip_failed(self, passage_id: str, reason: str):
        self.capture_failed.emit(passage_id, "clip:%s" % reason)

    def _resolve_closed_passage(self, passage_id: str) -> Passage | None:
        fn = self._get_open_passage
        if fn is None:
            return None
        parent = self.parent()
        fsm = getattr(parent, "_vehicle_fsm", None) if parent is not None else None
        if fsm is None:
            return None
        last = getattr(fsm, "last_closed", None)
        if last is not None and str(last.passage_id) == str(passage_id):
            return last
        return None
