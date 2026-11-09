# -*- coding: utf-8 -*-
"""车辆通道相机配置（RTSP 预览 + ISAPI 抓拍）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def parse_rtsp_host_user(url: str) -> tuple[str, str, str]:
    """Return host, user, password from rtsp://user:pass@host:554/..."""
    raw = str(url or "").strip()
    if not raw:
        return "", "", ""
    if "://" not in raw:
        raw = "rtsp://" + raw
    p = urlparse(raw)
    host = p.hostname or ""
    user = p.username or ""
    password = p.password or ""
    return host, user, password


DEFAULT_PLATE_HTTP_PORT = 8236


@dataclass
class VehicleCameraConfig:
    rtsp_url: str = ""
    host: str = ""
    user: str = ""
    password: str = ""
    isapi_channel: int = 101
    capture_dir: Path = Path.home() / "daq_tablet" / "vehicle_captures"
    plate_http_enabled: bool = True
    plate_http_host: str = "0.0.0.0"
    plate_http_port: int = DEFAULT_PLATE_HTTP_PORT
    plate_http_path_hint: str = "/hik/anpr"

    def snapshot_enabled(self) -> bool:
        return bool(self.resolved_host())

    def resolved_host(self) -> str:
        if str(self.host or "").strip():
            return str(self.host).strip()
        h, _, _ = parse_rtsp_host_user(self.rtsp_url)
        return h

    def resolved_credentials(self) -> tuple[str, str]:
        u = str(self.user or "").strip()
        pw = str(self.password or "").strip()
        if u:
            return u, pw
        _, ru, rp = parse_rtsp_host_user(self.rtsp_url)
        return ru, rp


def load_vehicle_camera_config(config_manager) -> VehicleCameraConfig:
    cfg = config_manager
    rtsp = str(getattr(cfg, "vehicle_rtsp_url", "") or "").strip()
    host = str(getattr(cfg, "vehicle_camera_host", "") or "").strip()
    user = str(getattr(cfg, "vehicle_camera_user", "") or "").strip()
    password = str(getattr(cfg, "vehicle_camera_password", "") or "")
    try:
        ch = int(getattr(cfg, "vehicle_camera_isapi_channel", 101))
    except (TypeError, ValueError):
        ch = 101
    if ch <= 0:
        ch = 101
    cap_raw = str(getattr(cfg, "vehicle_capture_dir", "") or "").strip()
    cap_dir = Path(cap_raw).expanduser() if cap_raw else Path.home() / "daq_tablet" / "vehicle_captures"
    plate_http_enabled = bool(getattr(cfg, "vehicle_plate_http_enabled", True))
    bind = str(getattr(cfg, "vehicle_plate_http_host", "0.0.0.0") or "0.0.0.0").strip()
    try:
        pport = int(getattr(cfg, "vehicle_plate_http_port", DEFAULT_PLATE_HTTP_PORT))
    except (TypeError, ValueError):
        pport = DEFAULT_PLATE_HTTP_PORT
    if pport <= 0:
        pport = DEFAULT_PLATE_HTTP_PORT
    path_hint = str(getattr(cfg, "vehicle_plate_http_path", "/hik/anpr") or "/hik/anpr").strip()
    return VehicleCameraConfig(
        rtsp_url=rtsp,
        host=host,
        user=user,
        password=password,
        isapi_channel=ch,
        capture_dir=cap_dir,
        plate_http_enabled=plate_http_enabled,
        plate_http_host=bind or "0.0.0.0",
        plate_http_port=pport,
        plate_http_path_hint=path_hint or "/hik/anpr",
    )
