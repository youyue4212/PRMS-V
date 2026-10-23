#!/usr/bin/env python3
"""显示逻辑：配置浮点 M 不被 sen_coef 整数覆盖（无 GUI）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class FakeConfig:
    def __init__(self):
        self.sensitivity = 3.0
        self.client_probe_settings = {"192.168.0.8": {"sensitivity": 3.7}}


class FakeUI:
    def __init__(self):
        self.config = FakeConfig()
        self.client_data = {
            "c1": {"sensitivity": 3.5},
        }
        self.primary_client_id = "c1"

    def _current_probe_key(self, cid):
        return "192.168.0.8" if cid == "c1" else None

    # 与 ui_base 同步的纯逻辑
    def _display_sensitivity_m(self, client_id=None, packet=None):
        from core.sensitivity_m import clamp_m

        cid = client_id or getattr(self, "primary_client_id", None)
        key = self._current_probe_key(cid) if cid else None
        if key:
            entry = (getattr(self.config, "client_probe_settings", None) or {}).get(key, {})
            if "sensitivity" in entry:
                return clamp_m(float(entry["sensitivity"]))
        if cid and getattr(self, "client_data", None):
            prev = self.client_data.get(cid) or {}
            v = prev.get("sensitivity")
            if v not in (None, "", "--"):
                return clamp_m(float(v))
        if packet is not None and getattr(packet, "sen_coef", None) not in (None, 0):
            return clamp_m(float(packet.sen_coef))
        return clamp_m(getattr(self.config, "sensitivity", 3.0))


class Pkt:
    sen_coef = 4


def main():
    ui = FakeUI()
    p = Pkt()
    assert ui._display_sensitivity_m("c1", p) == 3.7, "config 3.7 must beat sen_coef 4"
    ui.config.client_probe_settings = {}
    assert ui._display_sensitivity_m("c1", p) == 3.5, "client_data 3.5 beats sen_coef"
    ui.client_data = {}
    assert ui._display_sensitivity_m("c1", p) == 4.0, "fallback sen_coef"
    print("selfcheck_sensitivity_display OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
