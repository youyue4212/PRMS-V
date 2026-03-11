dark_stylesheet = """
QWidget {
    background-color: #1E1E1E;
    color: #E0E0E0;
    font-family: 'Segoe UI';
    font-size: 14px;
}
QGraphicsWidget {
        background-color: #2b2b2b;  /* Dark gray background */
        border: 1px solid #555555;  /* Subtle border */
        border-radius: 12px;
        color: #ffffff;             /* White text */
        font-size: 10pt;
        font-family: "Arial";
    }
    PlotItem {
        background: #1e1e1e;        /* Plot background */
        border: 1px solid #666666;
    }
    AxisItem {
        color: #cccccc;             /* Axis labels/ticks */
    }
    LegendItem {
        background-color: #333333;  /* Legend background */
        border: 1px solid #555555;
    }

QPushButton {
    background-color: #2F3B44;
    color: #E0E0E0;
    border: 1px solid #3C4A53;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton:hover {
    background-color: #3E4B55;
    border: 1px solid #5A6A75;
}

QPushButton:pressed {
    background-color: #242D33;
    border: 1px solid #1E2529;
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
