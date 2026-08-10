dark_stylesheet = """
QWidget {
    background-color: #1a1a1a;
    color: #E0E0E0;
    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
    font-size: 14px;
}
QGraphicsWidget {
        background-color: #2a2a2a;
        border: 1px solid #555555;
        border-radius: 10px;
        color: #ffffff;
        font-size: 10pt;
        font-family: "Microsoft YaHei", "Arial";
    }
    PlotItem {
        background: #1a1a1a;
        border: 1px solid #666666;
    }
    AxisItem {
        color: #cccccc;
    }
    LegendItem {
        background-color: #333333;
        border: 1px solid #555555;
    }

QPushButton {
    background-color: #2a2a2a;
    color: #E0E0E0;
    border: 1px solid #444444;
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 44px;
}

QPushButton:hover {
    background-color: #333333;
    border: 1px solid #555555;
}

QPushButton:pressed {
    background-color: #1f1f1f;
    border: 1px solid #333333;
}

QPushButton:disabled {
    background-color: #1E2529;
    color: #777;
    border: 1px solid #333;
}

/* 可选：QLineEdit、QComboBox 等统一暗色 */
QLineEdit, QComboBox, QTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2A2A2A;
    color: #E0E0E0;
    border: 1px solid #3C4A53;
    border-radius: 4px;
    padding: 4px;
}

QComboBox {
    padding-right: 18px; /* 预留下拉箭头空间 */
}

QSpinBox, QDoubleSpinBox {
    padding-right: 18px; /* 预留箭头按钮空间 */
}

QCheckBox {
    color: #E0E0E0;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #5A6A75;
    border-radius: 3px;
    background: #2A2A2A;
}

QCheckBox::indicator:checked {
    background: #4CAF50;
    border: 1px solid #4CAF50;
}

QCheckBox::indicator:unchecked {
    background: #2A2A2A;
    border: 1px solid #5A6A75;
}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    background-color: #2F3B44;
    border-left: 1px solid #3C4A53;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-position: top right;
    height: 12px;
    image: url(core/icons/arrow_up_white.svg);
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
    height: 12px;
    image: url(core/icons/arrow_down_white.svg);
}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #3E4B55;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #3C4A53;
    background-color: #2F3B44;
}

QComboBox::down-arrow {
    width: 10px;
    height: 10px;
    image: url(core/icons/arrow_down_white.svg);
}


QLabel {
}

QFrame {
}
"""
