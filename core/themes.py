import os
import sys


def _icon_file(filename: str) -> str:
    """Locate a QSS icon so it still loads after PyInstaller freeze."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "icons", filename)]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = os.path.dirname(sys.executable)
        if meipass:
            candidates.extend(
                [
                    os.path.join(meipass, "core", "icons", filename),
                    os.path.join(meipass, "icons", filename),
                ]
            )
        candidates.extend(
            [
                os.path.join(exe_dir, "_internal", "core", "icons", filename),
                os.path.join(exe_dir, "core", "icons", filename),
            ]
        )
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path).replace("\\", "/")
    return os.path.abspath(candidates[0]).replace("\\", "/")


def _qss_url(filename: str) -> str:
    return 'url("%s")' % _icon_file(filename)


def build_dark_stylesheet(control_room: bool = False) -> str:
    arrow_up = _qss_url("arrow_up_white.svg")
    arrow_down = _qss_url("arrow_down_white.svg")
    if control_room:
        from core.ui_tokens import CR_CHROME_H, CR_CHROME_FONT_PX
        font_px = CR_CHROME_FONT_PX
        btn_h = CR_CHROME_H
        btn_pad = "4px 12px"
    else:
        font_px = 14
        btn_h = 44
        btn_pad = "8px 14px"
    return """
QWidget {{
    background-color: #1a1a1a;
    color: #E0E0E0;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: {font_px}px;
}}
QGraphicsWidget {{
    background-color: transparent;
    border: none;
    color: #ffffff;
}}
PlotItem {{
    background: #1a1a1a;
    border: none;
}}
AxisItem {{
    color: #cccccc;
    background-color: transparent;
    border: none;
}}
LegendItem {{
    background-color: #1a1a1a;
    border: 1px solid #444444;
}}

QPushButton {{
    background-color: #2a2a2a;
    color: #E0E0E0;
    border: 1px solid #444444;
    border-radius: 8px;
    padding: {btn_pad};
    min-height: {btn_h}px;
}}

QPushButton:hover {{
    background-color: #333333;
    border: 1px solid #555555;
}}

QPushButton:pressed {{
    background-color: #1f1f1f;
    border: 1px solid #333333;
}}

QPushButton:disabled {{
    background-color: #1E2529;
    color: #777;
    border: 1px solid #333;
}}

/* 可选：QLineEdit、QComboBox 等统一暗色 */
QLineEdit, QComboBox, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: #2A2A2A;
    color: #E0E0E0;
    border: 1px solid #3C4A53;
    border-radius: 4px;
    padding: 4px;
}}

QComboBox {{
    padding-right: 18px; /* 预留下拉箭头空间 */
}}

QSpinBox, QDoubleSpinBox {{
    padding-right: 18px; /* 预留箭头按钮空间 */
}}

QCheckBox {{
    color: #E0E0E0;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #5A6A75;
    border-radius: 3px;
    background: #2A2A2A;
}}

QCheckBox::indicator:checked {{
    background: #4CAF50;
    border: 1px solid #4CAF50;
}}

QCheckBox::indicator:unchecked {{
    background: #2A2A2A;
    border: 1px solid #5A6A75;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    background-color: #2F3B44;
    border-left: 1px solid #3C4A53;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    height: 12px;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    height: 12px;
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 8px;
    height: 8px;
    image: {arrow_up};
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 8px;
    height: 8px;
    image: {arrow_down};
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: #3E4B55;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #3C4A53;
    background-color: #2F3B44;
}}

QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
    image: {arrow_down};
}}


QLabel {{
}}

QFrame {{
}}
""".format(
        arrow_up=arrow_up,
        arrow_down=arrow_down,
        font_px=font_px,
        btn_h=btn_h,
        btn_pad=btn_pad,
    )


dark_stylesheet = build_dark_stylesheet()
