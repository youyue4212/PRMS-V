# -*- coding: utf-8 -*-
"""Compact dialogs for 7-inch industrial panels."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _screen_geo(widget=None):
    app = QApplication.instance()
    screen = None
    if widget is not None:
        try:
            wh = widget.window().windowHandle() if widget.window() else None
            if wh is not None:
                screen = wh.screen()
        except Exception:
            screen = None
    if screen is None and app is not None:
        screen = app.primaryScreen()
    if screen is None:
        return 1024, 600
    g = screen.availableGeometry()
    return int(g.width()), int(g.height())


def fit_dialog_to_screen(dialog: QWidget, preferred_w: int, preferred_h: int,
                         max_w_ratio: float = 0.92, max_h_ratio: float = 0.88,
                         *, compact_max_w: int = 420, compact_max_h: int = 280):
    """Clamp dialog size for 7-inch panels (800x480 / 1024x600).

    compact_max_h defaults to 280 for short confirm dialogs; login should pass a
    larger value so inputs are not crushed/overlapping.
    """
    sw, sh = _screen_geo(dialog)
    is_compact = sh <= 600 or sw <= 1024
    if is_compact:
        max_w_ratio = min(max_w_ratio, 0.90)
        max_h_ratio = min(max_h_ratio, 0.90)
        preferred_w = min(preferred_w, compact_max_w)
        preferred_h = min(preferred_h, compact_max_h)

    w = max(280, min(int(preferred_w), int(sw * max_w_ratio)))
    # Keep enough height for real content (login fields need >280)
    h = max(200, min(int(preferred_h), int(sh * max_h_ratio)))
    dialog.setFixedSize(w, h)

    parent = dialog.parentWidget()
    if parent is not None:
        gp = parent.mapToGlobal(parent.rect().topLeft())
        x = gp.x() + max(0, (parent.width() - w) // 2)
        y = gp.y() + max(8, int(parent.height() * 0.04))
    else:
        x = max(0, (sw - w) // 2)
        y = max(8, int(sh * 0.05))
    dialog.move(QPoint(x, y))
    return w, h


class CompactConfirmDialog(QDialog):
    """Small confirm dialog with large touch buttons."""

    def __init__(self, parent, title: str, text: str, *,
                 danger: bool = True, ok_text: str = None, cancel_text: str = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)

        from core.translation import _t
        from core.ui_tokens import DANGER, INFO, BG, RADIUS_CARD, RADIUS_BTN, TOUCH_H
        ok_text = ok_text or _t("btn_confirm_yes")
        cancel_text = cancel_text or _t("btn_confirm_no")

        accent = DANGER if danger else INFO
        pressed = "#8e0000" if danger else "#1976d2"
        self.setStyleSheet("""
            QDialog {
                background-color: %s;
                border: 2px solid %s;
                border-radius: %dpx;
            }
            QLabel#titleLabel {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
                background: transparent;
            }
            QLabel#bodyLabel {
                color: #dddddd;
                font-size: 13px;
                background: transparent;
            }
            QPushButton {
                min-height: %dpx;
                border: none;
                border-radius: %dpx;
                font-size: 14px;
                font-weight: bold;
                padding: 0 16px;
            }
            QPushButton#okBtn {
                background-color: %s;
                color: white;
            }
            QPushButton#okBtn:pressed { background-color: %s; }
            QPushButton#cancelBtn {
                background-color: #455a64;
                color: white;
            }
            QPushButton#cancelBtn:pressed { background-color: #37474f; }
        """ % (BG, accent, RADIUS_CARD, TOUCH_H, RADIUS_BTN, accent, pressed))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("titleLabel")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        body = QLabel(text)
        body.setObjectName("bodyLabel")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(body, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(ok_text)
        ok_btn.setObjectName("okBtn")
        ok_btn.clicked.connect(self.accept)
        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 1)
        layout.addLayout(row)

        lines = max(2, text.count("\n") + 1)
        pref_h = 170 + min(80, lines * 18)
        fit_dialog_to_screen(self, 400, pref_h)
        cancel_btn.setFocus()


class CompactMessageDialog(QDialog):
    """Compact single-button notice."""

    def __init__(self, parent, title: str, text: str, *, level: str = "warn"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)

        from core.translation import _t
        from core.ui_tokens import WARN, DANGER, INFO, BG, RADIUS_CARD, RADIUS_BTN, TOUCH_H
        accent = {"warn": WARN, "error": DANGER, "info": INFO}.get(level, WARN)
        self.setStyleSheet("""
            QDialog {
                background-color: %s;
                border: 2px solid %s;
                border-radius: %dpx;
            }
            QLabel#titleLabel {
                color: #ffffff; font-size: 15px; font-weight: bold; background: transparent;
            }
            QLabel#bodyLabel {
                color: #dddddd; font-size: 13px; background: transparent;
            }
            QPushButton {
                min-height: %dpx; border: none; border-radius: %dpx;
                font-size: 14px; font-weight: bold;
                background-color: %s; color: white;
            }
        """ % (BG, accent, RADIUS_CARD, TOUCH_H, RADIUS_BTN, accent))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("titleLabel")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        body = QLabel(text)
        body.setObjectName("bodyLabel")
        body.setWordWrap(True)
        layout.addWidget(body, 1)
        ok_btn = QPushButton(_t("btn_confirm_ok"))
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)

        lines = max(1, text.count("\n") + 1)
        fit_dialog_to_screen(self, 380, 150 + min(70, lines * 16))
        ok_btn.setFocus()


def ask_confirm(parent, title: str, text: str, *, danger: bool = True) -> bool:
    dlg = CompactConfirmDialog(parent, title, text, danger=danger)
    return dlg.exec_() == QDialog.Accepted


def show_warn(parent, title: str, text: str):
    CompactMessageDialog(parent, title, text, level="warn").exec_()


def show_info(parent, title: str, text: str):
    CompactMessageDialog(parent, title, text, level="info").exec_()


def show_error(parent, title: str, text: str):
    CompactMessageDialog(parent, title, text, level="error").exec_()
