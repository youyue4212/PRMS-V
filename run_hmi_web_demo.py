#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone HMI shell: WebEngine loads hmi_web/index.html and pushes CPS.

  python run_hmi_web_demo.py

Prefers PySide6, then PyQt6, then PyQt5.
Formal product entry remains: python main.py
"""

import os
import sys
import random

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "hmi_web", "index.html")

QT_API = None
try:
    from PySide6.QtCore import QUrl, QTimer, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView
    QT_API = "PySide6"
except ImportError:
    try:
        from PyQt6.QtCore import QUrl, QTimer, Qt
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        QT_API = "PyQt6"
    except ImportError:
        from PyQt5.QtCore import QUrl, QTimer, Qt
        from PyQt5.QtGui import QFont
        from PyQt5.QtWidgets import QApplication, QMainWindow
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        QT_API = "PyQt5"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("行人通道辐射监测系统")
        self.resize(1280, 720)

        self.browser = QWebEngineView()
        html_path = os.path.abspath(HTML_PATH)
        url = QUrl.fromLocalFile(html_path.replace("\\", "/"))
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                self.browser.setHtml(f.read(), url)
        except Exception:
            self.browser.setUrl(url)
        self.setCentralWidget(self.browser)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.push_data_to_web)
        self.timer.start(1000)

    def push_data_to_web(self):
        cps1 = random.randint(400, 450)
        cps2 = random.randint(1980, 2020)
        js_code = (
            "if (typeof updateCpsData === 'function') "
            "updateCpsData(%d, %d); "
            "else if (typeof updateData === 'function') "
            "updateData(%d, %d);"
        ) % (cps1, cps2, cps1, cps2)
        self.browser.page().runJavaScript(js_code)


if __name__ == "__main__":
    if QT_API == "PyQt5":
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    else:
        attr = getattr(Qt, "AA_ShareOpenGLContexts", None)
        if attr is None:
            attr = Qt.ApplicationAttribute.AA_ShareOpenGLContexts
        QApplication.setAttribute(attr)

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))
    window = MainWindow()
    window.show()
    print("HMI demo using", QT_API, "->", HTML_PATH)
    if QT_API == "PyQt5":
        sys.exit(app.exec_())
    sys.exit(app.exec())
