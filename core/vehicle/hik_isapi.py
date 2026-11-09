# -*- coding: utf-8 -*-
"""海康 ISAPI 抓图（Digest）。DS-TCG405-E 等出入口机通用。"""

from __future__ import annotations

import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, build_opener

from core.vehicle.camera_config import VehicleCameraConfig


def fetch_isapi_snapshot(config: VehicleCameraConfig, timeout: float = 8.0) -> bytes | None:
    host = config.resolved_host()
    if not host:
        return None
    user, password = config.resolved_credentials()
    channel = int(config.isapi_channel or 101)
    url = "http://%s/ISAPI/Streaming/channels/%d/picture" % (host, channel)
    mgr = HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, url, user, password)
    opener = build_opener(HTTPDigestAuthHandler(mgr))
    ctx = ssl.create_default_context()
    try:
        resp = opener.open(url, timeout=timeout, context=ctx)
    except TypeError:
        resp = opener.open(url, timeout=timeout)
    try:
        data = resp.read()
    finally:
        resp.close()
    if not data or len(data) < 128:
        return None
    if data[:2] != b"\xff\xd8" and b"<?xml" in data[:200].lower():
        return None
    return data
