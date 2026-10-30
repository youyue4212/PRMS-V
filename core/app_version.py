# -*- coding: utf-8 -*-
"""上位机监测软件版本（与送检 doc_ui_alignment.SOFTWARE_NAME 对齐，JJF 1.4 取证）。"""

# 与 PMT 工程 tools/doc_ui_alignment.py 中 SOFTWARE_NAME 同步
APP_VERSION = "V17.1"
APP_BUILD = "2026-10-30"
APP_PRODUCT_ZH = "daq_tablet 监测软件"
APP_PRODUCT_EN = "daq_tablet Monitor"


def software_version_short() -> str:
    return APP_VERSION


def software_version_display(lang: str = "zh") -> str:
    product = APP_PRODUCT_ZH if str(lang or "").startswith("zh") else APP_PRODUCT_EN
    return f"{product} {APP_VERSION}"


def software_version_about(lang: str = "zh") -> str:
    product = APP_PRODUCT_ZH if str(lang or "").startswith("zh") else APP_PRODUCT_EN
    return f"{product}\n{APP_VERSION} ({APP_BUILD})"
