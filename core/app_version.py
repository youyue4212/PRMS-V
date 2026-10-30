# -*- coding: utf-8 -*-
"""上位机软件版本（JJF 1.4 / 送检资料与 doc_ui_alignment.SOFTWARE_NAME 对齐）。"""

APP_VERSION = "V17.1"
APP_NAME_ZH = "daq_tablet 监测软件"
APP_NAME_EN = "daq_tablet Monitoring Software"


def software_version_short() -> str:
    return APP_VERSION


def _app_title(lang: str) -> str:
    return APP_NAME_EN if str(lang or "zh").lower().startswith("en") else APP_NAME_ZH


def software_version_display(lang: str = "zh", multi_port: bool = False) -> str:
    text = "%s %s" % (_app_title(lang), APP_VERSION)
    if multi_port:
        text += " · " + (
            "TCP 多端口 (探头/主控分 listen)"
            if not str(lang or "zh").lower().startswith("en")
            else "multi-port TCP (probe + master)"
        )
    return text


def software_version_about(lang: str = "zh") -> str:
    from core.translation import _t

    multi = False
    try:
        from core.config import ConfigManager

        multi = bool(getattr(ConfigManager(), "tcp_multi_port", False))
    except Exception:
        pass
    line = software_version_display(lang, multi_port=multi)
    return "%s\n%s" % (line, _t("tip_software_version"))
