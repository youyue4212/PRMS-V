# -*- coding: utf-8 -*-
"""通用 RTSP 预览（OpenCV + FFmpeg）。未安装 opencv-python 时显示占位提示。"""

from __future__ import annotations

import os

from PyQt5.QtCore import QObject, Qt, QBuffer, QIODevice, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.vehicle.theme import COLOR as _C, FONT as _FONT, SIZE as _S


def normalize_rtsp_url(raw: str) -> str:
    """Trim; prepend rtsp:// when user omits scheme."""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "rtsp://" + s
    return s


class _RtspWorker(QObject):
    frame_ready = pyqtSignal(QImage)
    status = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._url = ""
        self._stop = False

    def configure(self, url: str):
        self._url = str(url or "").strip()
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.status.emit("请安装 opencv-python 以预览 RTSP")
            self.finished.emit()
            return

        import cv2

        url = self._url
        if not url:
            self.status.emit("")
            self.finished.emit()
            return

        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
        )
        cap = None
        fail_count = 0
        while not self._stop:
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                    cap = None
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    fail_count += 1
                    self.status.emit("连接 RTSP 失败" if fail_count >= 2 else "正在连接…")
                    self.msleep(800)
                    continue
                fail_count = 0
                self.status.emit("")

            ok, frame = cap.read()
            if self._stop:
                break
            if not ok or frame is None:
                cap.release()
                cap = None
                self.status.emit("视频中断，重连中…")
                self.msleep(400)
                continue

            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except cv2.error:
                continue
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
            self.frame_ready.emit(img)
            self.msleep(66)

        if cap is not None:
            cap.release()
        self.finished.emit()


class RtspPreviewWidget(QWidget):
    """车辆页中间区：有 URL 时拉流；否则显示大号占位文案。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashCapture")
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._url = ""
        self._center_text = "等待过车"
        self._badge = ""
        self._last_image = None
        self._alarm_path = ""
        self._thread = None
        self._worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.video = QLabel()
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setScaledContents(False)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.badge = QLabel("")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.hide()
        for w in (self.video, self.status, self.badge):
            lay.addWidget(w, 1 if w is self.video else 0)
        self._apply_style()

    def _apply_style(self):
        bg = _C["capture-bg"]
        self.setStyleSheet(
            "QWidget#dashCapture { background: %s; border: none; border-radius: 4px; }"
            % bg
        )
        self.video.setStyleSheet("background: transparent; border: none;")
        self.status.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 700; font-family: %s; background: transparent;"
            % (_C["white"], _S.get("field-value", 16) + 14, _FONT)
        )
        self.badge.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 700; font-family: %s;"
            " background: rgba(0,0,0,0.45); padding: 4px 10px; border-radius: 4px;"
            % (_C["white"], _S.get("section-title", 18), _FONT)
        )

    def stream_enabled(self) -> bool:
        return bool(self._url)

    def center_text(self) -> str:
        return self._center_text

    def set_stream_url(self, url: str):
        url = normalize_rtsp_url(url)
        if url == self._url:
            return
        self._url = url
        self._stop_worker()
        if self.isVisible() and self._url:
            self._start_worker()
        self._paint_placeholder()

    def set_center_text(self, text: str):
        self._center_text = str(text or "")
        if not self.stream_enabled():
            self._paint_placeholder()

    def set_alarm_image(self, path: str):
        """硬报留证图；非空时优先显示本地 JPEG。"""
        p = str(path or "").strip()
        if p == self._alarm_path:
            return
        self._alarm_path = p
        if not p:
            self._scale_frame()
            return
        from pathlib import Path

        if not Path(p).is_file():
            return
        pm = QPixmap(p)
        if pm.isNull():
            return
        scaled = pm.scaled(self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video.setPixmap(scaled)
        self.status.setText("留证抓拍")

    def grab_jpeg_bytes(self) -> bytes | None:
        img = self._last_image
        if img is None or img.isNull():
            return None
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        if not img.save(buf, "JPEG", 85):
            return None
        return bytes(buf.data())

    def set_badge_text(self, text: str):
        t = str(text or "").strip()
        self._badge = t
        if t and self.stream_enabled():
            self.badge.setText(t)
            self.badge.show()
        else:
            self.badge.hide()

    def _paint_placeholder(self):
        if self.stream_enabled():
            if self._last_image is None:
                self.video.setText("")
                self.status.setText(self._center_text or "正在连接…")
            return
        self._last_image = None
        self.video.clear()
        self.video.setText(self._center_text or "等待过车")
        self.video.setStyleSheet(
            "color: %s; font-size: 30px; font-weight: 700; font-family: %s; background: transparent;"
            % (_C["white"], _FONT)
        )
        self.status.setText("")

    def _on_frame(self, image: QImage):
        if not self.stream_enabled():
            return
        self._last_image = image
        self.status.setText("")
        self._scale_frame()

    def _on_status(self, text: str):
        if self._last_image is None or text:
            self.status.setText(str(text or ""))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_frame()

    def _scale_frame(self):
        if self._alarm_path:
            self.set_alarm_image(self._alarm_path)
            return
        if self._last_image is None or self._last_image.isNull():
            return
        pm = QPixmap.fromImage(self._last_image)
        scaled = pm.scaled(self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video.setPixmap(scaled)
        self.video.setStyleSheet("background: transparent; border: none;")

    def showEvent(self, event):
        super().showEvent(event)
        if self._url:
            self._start_worker()

    def hideEvent(self, event):
        self._stop_worker()
        super().hideEvent(event)

    def _start_worker(self):
        if not self._url:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = QThread(self)
        self._worker = _RtspWorker()
        self._worker.moveToThread(self._thread)
        self._worker.configure(self._url)
        self._thread.started.connect(self._worker.run)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _stop_worker(self):
        w = self._worker
        t = self._thread
        if w is not None:
            w.request_stop()
        if t is not None and t.isRunning():
            t.quit()
            t.wait(1500)
        self._worker = None
        self._thread = None
        self._last_image = None
