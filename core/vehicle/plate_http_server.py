# -*- coding: utf-8 -*-
"""HTTP 报警主机：接收相机 ANPR POST → 车牌 + 可选图片。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from core.vehicle.plate_parse import parse_plate_payload


class _PlateHandler(BaseHTTPRequestHandler):
    server_version = "PRMS-V-Plate/1.0"

    def log_message(self, fmt, *args):
        return

    def _emit(self, plate: str, image: bytes | None):
        srv: _PlateHttpServerImpl = self.server  # type: ignore[assignment]
        if srv.on_plate:
            srv.on_plate(plate, self.client_address[0], image)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        ct = str(self.headers.get("Content-Type") or "")
        plate, image = parse_plate_payload(body, ct)
        self._emit(plate, image)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_PUT(self):
        self.do_POST()

    def do_GET(self):
        if self.path.rstrip("/").endswith("health"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return
        self.send_response(405)
        self.end_headers()


class _PlateHttpServerImpl(ThreadingHTTPServer):
    def __init__(self, addr, handler, on_plate):
        super().__init__(addr, handler)
        self.on_plate = on_plate


class PlateHttpServer(QObject):
    """在独立线程监听；plate_received 在主线程连接 ingest_plate。"""

    plate_received = pyqtSignal(str, str, object)

    listen_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._httpd: Optional[_PlateHttpServerImpl] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0

    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    def listen_port(self) -> int:
        return int(self._port or 0)

    def start(self, host: str = "0.0.0.0", port: int = 8236):
        self.stop()
        port = int(port)
        if port <= 0 or port > 65535:
            self.listen_failed.emit("invalid_port")
            return

        def _on_plate(plate: str, remote: str, image: bytes | None):
            self.plate_received.emit(plate, remote, image)

        try:
            self._httpd = _PlateHttpServerImpl((host, port), _PlateHandler, _on_plate)
        except OSError as exc:
            self.listen_failed.emit(str(exc))
            self._httpd = None
            return
        self._port = port
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
        self._httpd = None
        self._thread = None
        self._port = 0
