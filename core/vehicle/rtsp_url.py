# -*- coding: utf-8 -*-
"""从 RTSP URL 解析主机与凭据（供 ISAPI 抓图复用）。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class RtspEndpoint:
    host: str
    port: int
    username: str
    password: str


def parse_rtsp_endpoint(url: str) -> RtspEndpoint | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "rtsp://" + raw
    p = urlparse(raw)
    host = (p.hostname or "").strip()
    if not host:
        return None
    port = int(p.port or 554)
    user = unquote(p.username or "")
    pwd = unquote(p.password or "")
    return RtspEndpoint(host=host, port=port, username=user, password=pwd)
