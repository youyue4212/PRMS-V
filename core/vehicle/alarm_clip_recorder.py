# -*- coding: utf-8 -*-
"""硬报前后约 10s 子码流片段（前 5s 环形缓冲 + 后 5s 续录）。"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, pyqtSignal

PRE_SECONDS = 5.0
POST_SECONDS = 5.0
TARGET_FPS = 8


class _ClipWorker(QObject):
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._url = ""
        self._passage_id = ""
        self._out_path = ""
        self._pre_frames: list = []

    def configure(self, url: str, passage_id: str, out_path: str, pre_frames: list):
        self._url = str(url or "").strip()
        self._passage_id = str(passage_id or "")
        self._out_path = str(out_path or "")
        self._pre_frames = list(pre_frames or [])

    def run(self):
        pid = self._passage_id
        if not pid or not self._out_path:
            self.failed.emit(pid, "clip_config")
            return
        try:
            import cv2
        except ImportError:
            self.failed.emit(pid, "no_opencv")
            return

        url = self._url
        frames = []
        for item in self._pre_frames:
            if isinstance(item, tuple) and len(item) == 2:
                frames.append(item[1])

        cap = None
        if url:
            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
            )
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        deadline = time.monotonic() + POST_SECONDS
        while time.monotonic() < deadline:
            if cap is not None and cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append(frame.copy())
            else:
                time.sleep(0.05)
            time.sleep(max(0.0, 1.0 / TARGET_FPS - 0.01))

        if cap is not None:
            cap.release()

        if not frames:
            self.failed.emit(pid, "clip_no_frames")
            return

        h, w = frames[0].shape[:2]
        out = Path(self._out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out), fourcc, TARGET_FPS, (w, h))
        if not writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"XVID")
            alt = out.with_suffix(".avi")
            writer = cv2.VideoWriter(str(alt), fourcc, TARGET_FPS, (w, h))
            out = alt
        if not writer.isOpened():
            self.failed.emit(pid, "clip_writer")
            return
        for fr in frames:
            if fr.shape[0] != h or fr.shape[1] != w:
                fr = cv2.resize(fr, (w, h))
            writer.write(fr)
        writer.release()
        self.finished.emit(pid, str(out))


class AlarmClipRecorder(QObject):
    """与预览并行：独立拉子码流填环形缓冲，硬报时导出片段。"""

    clip_ready = pyqtSignal(str, str)
    clip_failed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ""
        self._capture_dir = Path.home() / "daq_tablet" / "vehicle_captures"
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=int(PRE_SECONDS * TARGET_FPS) + 2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._clip_thread: QThread | None = None
        self._clip_worker: _ClipWorker | None = None
        self._recording_clip = False

    def set_rtsp_url(self, url: str):
        url = str(url or "").strip()
        if url == self._url:
            return
        self.stop_buffer()
        self._url = url
        if url:
            self.start_buffer()

    def set_capture_dir(self, path: Path | str):
        self._capture_dir = Path(path).expanduser()

    def start_buffer(self):
        if not self._url or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._buffer_loop, daemon=True)
        self._thread.start()

    def stop_buffer(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._buffer.clear()

    def trigger_clip(self, passage_id: str):
        pid = str(passage_id or "").strip()
        if not pid or not self._url:
            return
        if self._recording_clip:
            return
        if self._clip_thread is not None and self._clip_thread.isRunning():
            return
        with self._lock:
            pre = list(self._buffer)
        out_dir = self._capture_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        name = "clip_%s_%d.mp4" % (pid.replace("/", "-"), int(time.time() * 1000))
        out_path = out_dir / name
        self._recording_clip = True
        self._clip_thread = QThread(self)
        self._clip_worker = _ClipWorker()
        self._clip_worker.moveToThread(self._clip_thread)
        self._clip_worker.configure(self._url, pid, str(out_path), pre)
        self._clip_thread.started.connect(self._clip_worker.run)
        self._clip_worker.finished.connect(self._on_clip_done)
        self._clip_worker.failed.connect(self._on_clip_fail)
        self._clip_worker.finished.connect(self._clip_thread.quit)
        self._clip_worker.failed.connect(self._clip_thread.quit)
        self._clip_thread.finished.connect(self._on_clip_thread_done)
        self._clip_thread.start()

    def _buffer_loop(self):
        try:
            import cv2
        except ImportError:
            return
        url = self._url
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
        )
        cap = None
        interval = 1.0 / TARGET_FPS
        while not self._stop.is_set():
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    time.sleep(0.8)
                    continue
            t0 = time.monotonic()
            ok, frame = cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._buffer.append((time.monotonic(), frame.copy()))
            else:
                cap.release()
                cap = None
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))
        if cap is not None:
            cap.release()

    def _on_clip_done(self, passage_id: str, path: str):
        self.clip_ready.emit(passage_id, path)

    def _on_clip_fail(self, passage_id: str, reason: str):
        self.clip_failed.emit(passage_id, reason)

    def _on_clip_thread_done(self):
        self._recording_clip = False
        self._clip_thread = None
        self._clip_worker = None
