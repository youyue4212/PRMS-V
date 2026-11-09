# -*- coding: utf-8 -*-
"""车辆通道证据图路径：role|path，兼容旧版纯路径（视为 alarm）。"""

from __future__ import annotations

EVIDENCE_ROLES = ("entry", "alarm", "exit", "plate", "video")


def parse_image_paths(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    text = str(raw or "").strip()
    if not text:
        return out
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "|" in part:
            role, path = part.split("|", 1)
            role = role.strip().lower()
            path = path.strip()
            if role and path:
                out[role] = path
        else:
            out.setdefault("alarm", part)
    return out


def path_for_role(raw: str, role: str) -> str:
    return parse_image_paths(raw).get(str(role or "").lower(), "")


def append_image_path(raw: str, role: str, path: str) -> str:
    role = str(role or "").strip().lower()
    path = str(path or "").strip()
    if not role or not path:
        return str(raw or "")
    data = parse_image_paths(raw)
    data[role] = path
    order = [r for r in EVIDENCE_ROLES if r in data]
    for k in data:
        if k not in order:
            order.append(k)
    return ";".join("%s|%s" % (k, data[k]) for k in order)


def serialize_image_paths(data: dict[str, str]) -> str:
    parts = []
    for role in EVIDENCE_ROLES:
        p = str(data.get(role) or "").strip()
        if p:
            parts.append("%s|%s" % (role, p))
    for k, v in sorted(data.items()):
        if k in EVIDENCE_ROLES or not str(v or "").strip():
            continue
        parts.append("%s|%s" % (k, str(v).strip()))
    return ";".join(parts)
