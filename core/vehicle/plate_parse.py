# -*- coding: utf-8 -*-
"""从海康/大华等 ANPR HTTP 报文中提取车牌与图片（多标签兼容）。"""

from __future__ import annotations

import base64
import binascii
import json
import re
from email import policy
from email.parser import BytesParser

_TAG_PATTERNS = (
    r"<licensePlate[^>]*>([^<]+)</licensePlate>",
    r"<plateNo[^>]*>([^<]+)</plateNo>",
    r"<PlateNumber[^>]*>([^<]+)</PlateNumber>",
    r"<carPlate[^>]*>([^<]+)</carPlate>",
    r"<originalLicensePlate[^>]*>([^<]+)</originalLicensePlate>",
)

_B64_TAGS = (
    r"<(?:picture|Picture|detectionPicture|platePic|licensePlatePicture)[^>]*>"
    r"([^<]+)</(?:picture|Picture|detectionPicture|platePic|licensePlatePicture)>",
)

# 大陆常见车牌（含新能源 8 位），用于 JSON/纯文本兜底
_PLATE_RE = re.compile(
    r"[\u4e00-\u9fa5][A-HJ-NP-Z0-9]{4,7}[\u4e00-\u9fa5A-HJ-NP-Z0-9]?",
)

_JPEG_MAGIC = b"\xff\xd8\xff"


def _clean(token: str) -> str:
    t = str(token or "").strip().upper()
    t = t.replace(" ", "").replace("\u00b7", "")
    if t in ("", "UNKNOWN", "NOPLATE", "无牌", "—", "-"):
        return ""
    return t


def _decode_b64_blob(raw: str) -> bytes | None:
    s = str(raw or "").strip()
    if not s or len(s) < 32:
        return None
    s = re.sub(r"\s+", "", s)
    try:
        data = base64.b64decode(s, validate=False)
    except (ValueError, binascii.Error):
        try:
            data = base64.b64decode(s)
        except Exception:
            return None
    if data.startswith(_JPEG_MAGIC) or len(data) > 256:
        return data
    return None


def _image_from_multipart(body: bytes, content_type: str) -> bytes | None:
    ct = str(content_type or "").strip()
    if "multipart" not in ct.lower():
        return None
    try:
        msg = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + ct.encode("ascii", errors="ignore") + b"\r\n\r\n" + body
        )
    except Exception:
        return None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or len(payload) < 64:
            continue
        subtype = (part.get_content_subtype() or "").lower()
        if subtype in ("jpeg", "jpg", "png", "bmp") or payload.startswith(_JPEG_MAGIC):
            return payload
    return None


def _image_from_xml_or_json(text: str) -> bytes | None:
    if not text:
        return None
    for pat in _B64_TAGS:
        m = re.search(pat, text, re.I | re.S)
        if m:
            blob = _decode_b64_blob(m.group(1))
            if blob:
                return blob
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        for key in (
            "image",
            "picture",
            "plateImage",
            "licensePlatePicture",
            "detectionPicture",
            "picBase64",
        ):
            blob = _decode_b64_blob(str(data.get(key) or ""))
            if blob:
                return blob
    return None


def extract_plate_from_body(body: bytes | str) -> str:
    text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else str(body or "")
    if not text.strip():
        return ""
    for pat in _TAG_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            p = _clean(m.group(1))
            if p:
                return p
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("plateNo", "licensePlate", "plate", "PlateNumber", "carPlate"):
                p = _clean(str(data.get(key) or ""))
                if p:
                    return p
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    for m in _PLATE_RE.finditer(text):
        p = _clean(m.group(0))
        if len(p) >= 7:
            return p
    return ""


def parse_plate_payload(body: bytes | str, content_type: str = "") -> tuple[str, bytes | None]:
    """返回 (plate, jpeg_or_image_bytes)。"""
    raw = body if isinstance(body, bytes) else str(body or "").encode("utf-8", errors="ignore")
    if not raw:
        return "", None
    ct = str(content_type or "")
    image = _image_from_multipart(raw, ct)
    text = raw.decode("utf-8", errors="ignore")
    plate = extract_plate_from_body(text)
    if image is None:
        image = _image_from_xml_or_json(text)
    if not plate and image is not None:
        plate = extract_plate_from_body(text)
    return plate, image
