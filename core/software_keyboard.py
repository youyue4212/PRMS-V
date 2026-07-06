# -*- coding: utf-8 -*-
"""
软件键盘组件 - 作为onboard虚拟键盘的替代方案
当onboard无法正常输入时，提供内置的软件数字键盘
"""
import sys
from PyQt5.QtWidgets import (QWidget, QGridLayout, QPushButton, QLineEdit, 
                             QVBoxLayout, QHBoxLayout, QLabel, QDialog, QApplication,
                             QSpinBox, QDoubleSpinBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

class SoftwareKeyboard(QDialog):
    """软件数字键盘对话框"""
    
    # 信号：按键按下
    key_pressed = pyqtSignal(str)
    # 信号：退格键
    backspace_pressed = pyqtSignal()
    # 信号：回车键
    enter_pressed = pyqtSignal()
    # 信号：关闭键盘
    keyboard_closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_input = None  # 目标输入框
        self.is_uppercase = False
        self.replace_on_first_input = False
        self.dragging = False
        self.drag_offset = None
        self.initUI()
        
    def initUI(self):
        """初始化UI"""
        self.setWindowTitle("软件数字键盘")
        self.setFixedSize(400, 300)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        
        # 标题栏
        title_layout = QHBoxLayout()
        self.title_label = QLabel("软件数字键盘")
        self.title_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignCenter)
        title_layout.addWidget(self.title_label)
        
        # 切换按钮（数字/字母）
        self.toggle_btn = QPushButton("ABC")
        self.toggle_btn.setFixedSize(50, 30)
        self.toggle_btn.clicked.connect(self.toggle_mode)
        title_layout.addWidget(self.toggle_btn)

        # 大小写切换
        self.case_btn = QPushButton("A⇄a")
        self.case_btn.setFixedSize(50, 30)
        self.case_btn.clicked.connect(self.toggle_case)
        title_layout.addWidget(self.case_btn)

        # 关闭按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(self.close_keyboard)
        title_layout.addWidget(self.close_btn)
        
        main_layout.addLayout(title_layout)
        
        # 显示区域（模拟输入框）
        self.display_label = QLabel("")
        self.display_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 2px solid #cccccc;
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 16px;
                color: #333333;
                min-height: 28px;
                max-height: 36px;
            }
        """)
        self.display_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.display_label)
        
        # 键盘布局容器
        self.keyboard_layout = QGridLayout()
        self.keyboard_layout.setSpacing(4)
        self.keyboard_layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.keyboard_mode = "numeric"
        self.adjust_size_for_mode()
        self.build_keyboard_layout()

        main_layout.addLayout(self.keyboard_layout)
        
        self.setLayout(main_layout)
        
        # 设置样式
        self.setStyleSheet("""
            QDialog {
                background-color: #2a2a2a;
                border: 2px solid #444444;
                border-radius: 10px;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                color: #ffffff;
                font-weight: bold;
                text-align: center;
                padding: 0px;
            }
        """)
        
        # 初始化显示文本
        self.display_text = ""
        self.update_display()

    def adjust_size_for_mode(self):
        """根据键盘模式调整对话框尺寸，保证字母键显示清晰"""
        screen_geometry = QApplication.desktop().screenGeometry()
        if self.keyboard_mode == "alpha":
            width = min(700, max(540, screen_geometry.width() - 20))
            height = min(380, max(320, screen_geometry.height() - 20))
            self.setFixedSize(width, height)
        else:
            width = min(500, max(420, screen_geometry.width() - 20))
            height = min(330, max(300, screen_geometry.height() - 20))
            self.setFixedSize(width, height)

    def clear_keyboard_layout(self):
        while self.keyboard_layout.count():
            item = self.keyboard_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def build_keyboard_layout(self):
        self.clear_keyboard_layout()

        if self.keyboard_mode == "numeric":
            for col in range(5):
                self.keyboard_layout.setColumnStretch(col, 1)
            buttons = [
                ("1", 0, 1), ("2", 0, 2), ("3", 0, 3),
                ("4", 1, 1), ("5", 1, 2), ("6", 1, 3),
                ("7", 2, 1), ("8", 2, 2), ("9", 2, 3),
                ("0", 3, 2),
            ]
            for text, row, col in buttons:
                btn = self.create_number_button(text, size=(72, 54), font_size=18)
                self.keyboard_layout.addWidget(btn, row, col, alignment=Qt.AlignCenter)

            self.backspace_btn = self.create_special_button("BS", "backspace", size=(72, 54), font_size=16)
            self.backspace_btn.clicked.connect(self.on_backspace)
            self.keyboard_layout.addWidget(self.backspace_btn, 0, 4, alignment=Qt.AlignCenter)

            self.clear_btn = self.create_special_button("C", "clear", size=(72, 54), font_size=16)
            self.clear_btn.clicked.connect(self.on_clear)
            self.keyboard_layout.addWidget(self.clear_btn, 1, 4, alignment=Qt.AlignCenter)

            self.enter_btn = self.create_special_button("OK", "enter", size=(72, 54), font_size=16)
            self.enter_btn.clicked.connect(self.on_enter)
            self.keyboard_layout.addWidget(self.enter_btn, 2, 4, 2, 1, alignment=Qt.AlignCenter)

            # create_number_button 内部已连接 on_number_click，勿重复连接（否则一按出两个符号）
            self.decimal_btn = self.create_number_button(".", size=(72, 54), font_size=18)
            self.keyboard_layout.addWidget(self.decimal_btn, 3, 1, alignment=Qt.AlignCenter)

            self.minus_btn = self.create_number_button("-", size=(72, 54), font_size=18)
            self.keyboard_layout.addWidget(self.minus_btn, 3, 3, alignment=Qt.AlignCenter)

        else:
            for col in range(10):
                self.keyboard_layout.setColumnStretch(col, 1)
            rows = [
                list("QWERTYUIOP"),
                list("ASDFGHJKL"),
                list("ZXCVBNM")
            ]
            for r, row_keys in enumerate(rows):
                for c, key in enumerate(row_keys):
                    display_key = key if self.is_uppercase else key.lower()
                    btn = self.create_number_button(display_key, size=(56, 52), font_size=18)
                    self.keyboard_layout.addWidget(btn, r, c, alignment=Qt.AlignCenter)

            # Space, Backspace, Clear, Enter
            # create_number_button 内部已连接 on_number_click(" ")，勿重复连接
            self.space_btn = self.create_number_button(" ", size=(56, 52), font_size=16)
            self.space_btn.setText("Space")
            self.keyboard_layout.addWidget(self.space_btn, 3, 2, 1, 4, alignment=Qt.AlignCenter)

            self.backspace_btn = self.create_special_button("BS", "backspace", size=(56, 52), font_size=16)
            self.backspace_btn.clicked.connect(self.on_backspace)
            self.keyboard_layout.addWidget(self.backspace_btn, 3, 0, 1, 2, alignment=Qt.AlignCenter)

            self.clear_btn = self.create_special_button("C", "clear", size=(56, 52), font_size=16)
            self.clear_btn.clicked.connect(self.on_clear)
            self.keyboard_layout.addWidget(self.clear_btn, 3, 6, 1, 2, alignment=Qt.AlignCenter)

            self.enter_btn = self.create_special_button("OK", "enter", size=(56, 52), font_size=16)
            self.enter_btn.clicked.connect(self.on_enter)
            self.keyboard_layout.addWidget(self.enter_btn, 3, 8, 1, 2, alignment=Qt.AlignCenter)

    def toggle_mode(self):
        if self.keyboard_mode == "numeric":
            self.keyboard_mode = "alpha"
            self.toggle_btn.setText("123")
        else:
            self.keyboard_mode = "numeric"
            self.toggle_btn.setText("ABC")
        self.adjust_size_for_mode()
        self.build_keyboard_layout()

    def toggle_case(self):
        self.is_uppercase = not self.is_uppercase
        if self.keyboard_mode == "alpha":
            self.build_keyboard_layout()
    
    def create_number_button(self, text, size=(70, 50), font_size=16):
        """创建数字按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(size[0], size[1])
        btn.setFont(QFont("Arial", font_size, QFont.Bold))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                color: white;
                border: 2px solid #666666;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border-color: #777777;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
        """)
        btn.clicked.connect(lambda: self.on_number_click(text))
        return btn
    
    def create_special_button(self, text, button_type, size=(70, 50), font_size=16):
        """创建特殊功能按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(size[0], size[1])
        btn.setFont(QFont("Arial", font_size, QFont.Bold))
        
        # 根据按钮类型设置不同颜色
        if button_type == "backspace":
            color = "#ff9800"  # 橙色
        elif button_type == "clear":
            color = "#f44336"  # 红色
        elif button_type == "enter":
            color = "#4caf50"  # 绿色
        else:
            color = "#2196f3"  # 蓝色
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: 2px solid {color};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color(color, 20)};
                border-color: {self.adjust_color(color, 30)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color(color, -20)};
            }}
        """)
        
        return btn
    
    def adjust_color(self, color, amount):
        """调整颜色亮度"""
        # 简单实现：在实际应用中可能需要更复杂的颜色调整
        return color
    
    def on_number_click(self, text):
        """数字按钮点击事件"""
        replace_now = self.replace_on_first_input and isinstance(self.target_input, (QSpinBox, QDoubleSpinBox))
        if replace_now:
            self.display_text = text
        else:
            self.display_text += text
        self.update_display()
        
        # 如果有关联的输入框，直接更新输入框
        if self.target_input:
            if isinstance(self.target_input, (QSpinBox, QDoubleSpinBox)):
                self._set_target_text(self.display_text)
                self.replace_on_first_input = False
            else:
                if replace_now:
                    self._set_target_text(text)
                    self.replace_on_first_input = False
                else:
                    current_text = self._get_target_text()
                    self._set_target_text(current_text + text)
            # 直接更新后返回，避免信号触发重复操作
            return
        
        # 没有关联输入框时才发出信号
        self.key_pressed.emit(text)
    
    def on_backspace(self):
        """退格键事件"""
        if self.display_text:
            self.display_text = self.display_text[:-1]
            self.update_display()
            
            # 如果有关联的输入框，直接更新输入框
            if self.target_input:
                if isinstance(self.target_input, (QSpinBox, QDoubleSpinBox)):
                    self._set_target_text(self.display_text)
                else:
                    current_text = self._get_target_text()
                    if current_text:
                        self._set_target_text(current_text[:-1])
                # 直接更新后返回，避免信号触发重复操作
                return
            
            # 没有关联输入框时才发出信号
            self.backspace_pressed.emit()
    
    def on_clear(self):
        """清除键事件"""
        self.display_text = ""
        self.update_display()
        self.replace_on_first_input = True
        
        # 如果有关联的输入框，直接清空输入框
        if self.target_input:
            self._set_target_text("")
    
    def on_enter(self):
        """回车键事件"""
        self.enter_pressed.emit()
        
        # 如果有关联的输入框，模拟回车事件
        if self.target_input:
            try:
                if hasattr(self.target_input, 'interpretText'):
                    self.target_input.interpretText()
                elif hasattr(self.target_input, 'valueFromText') and hasattr(self.target_input, 'setValue'):
                    text = self.target_input.text()
                    self.target_input.setValue(self.target_input.valueFromText(text))
            except Exception:
                pass
        
        # 关闭键盘
        self.close_keyboard()
    
    def update_display(self):
        """更新显示"""
        if not self.display_text:
            self.display_label.setText("点击数字按钮输入...")
        else:
            self.display_label.setText(self.display_text)

    def _get_target_text(self):
        if hasattr(self.target_input, 'lineEdit') and self.target_input.lineEdit():
            return self.target_input.lineEdit().text()
        if hasattr(self.target_input, 'text'):
            return self.target_input.text()
        return ""

    def _set_target_text(self, text):
        try:
            if hasattr(self.target_input, 'lineEdit') and self.target_input.lineEdit():
                self.target_input.lineEdit().setText(text)
                if isinstance(self.target_input, (QSpinBox, QDoubleSpinBox)):
                    try:
                        if text.strip() == "":
                            return
                        if isinstance(self.target_input, QDoubleSpinBox):
                            value = float(text)
                        else:
                            value = int(float(text))
                        self.target_input.setValue(value)
                    except Exception:
                        pass
                if hasattr(self.target_input, 'interpretText'):
                    self.target_input.interpretText()
                elif hasattr(self.target_input, 'valueFromText') and hasattr(self.target_input, 'setValue'):
                    self.target_input.setValue(self.target_input.valueFromText(text))
            elif hasattr(self.target_input, 'setText'):
                self.target_input.setText(text)
        except Exception:
            pass
    
    def set_target_input(self, input_widget):
        """设置目标输入框"""
        self.target_input = input_widget
        
        # 如果输入框有当前文本，显示在键盘上
        if input_widget:
            current_text = self._get_target_text()
            if current_text:
                self.display_text = current_text
                self.update_display()
    
    def show_for_input(self, input_widget, position=None):
        """为指定的输入框显示键盘"""
        self.set_target_input(input_widget)
        # 默认使用数字键盘，字母需要手动切换
        try:
            self.keyboard_mode = "numeric"
            self.toggle_btn.setText("ABC")
            self.replace_on_first_input = isinstance(input_widget, (QSpinBox, QDoubleSpinBox))
            self.adjust_size_for_mode()
            self.build_keyboard_layout()
        except Exception:
            pass
        
        # 设置键盘位置（带边界裁剪，防止被屏幕裁切）
        screen_geometry = QApplication.desktop().screenGeometry()
        if position:
            x = position.x()
            y = position.y()
        else:
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
        x = max(screen_geometry.left(), min(x, screen_geometry.right() - self.width()))
        y = max(screen_geometry.top(), min(y, screen_geometry.bottom() - self.height()))
        self.move(x, y)
        
        self.show()
        self.raise_()
        self.activateWindow()
    
    def close_keyboard(self):
        """关闭键盘"""
        self.commit_target_input()
        self.keyboard_closed.emit()
        self.close()

    def commit_target_input(self):
        if not self.target_input:
            return
        try:
            if hasattr(self.target_input, 'interpretText'):
                self.target_input.interpretText()
            elif hasattr(self.target_input, 'valueFromText') and hasattr(self.target_input, 'setValue'):
                text = self.target_input.text()
                self.target_input.setValue(self.target_input.valueFromText(text))
        except Exception:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging and self.drag_offset is not None:
            self.move(event.globalPos() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.drag_offset = None
        event.accept()
    
    def keyPressEvent(self, event):
        """键盘按键事件"""
        key = event.key()
        
        # 处理数字键
        if Qt.Key_0 <= key <= Qt.Key_9:
            digit = str(key - Qt.Key_0)
            self.on_number_click(digit)
        elif key == Qt.Key_Period or key == Qt.Key_Comma:
            self.on_number_click(".")
        elif key == Qt.Key_Minus:
            self.on_number_click("-")
        elif key == Qt.Key_Backspace:
            self.on_backspace()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self.on_enter()
        elif key == Qt.Key_Escape:
            self.close_keyboard()
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """关闭事件"""
        self.keyboard_closed.emit()
        super().closeEvent(event)


class SoftwareKeyboardManager:
    """软件键盘管理器"""
    
    def __init__(self):
        self.keyboard_window = None
        self.current_input = None
        self.last_closed_time = 0
    
    def show_keyboard_for_input(self, input_widget, parent=None):
        """为输入框显示软件键盘"""
        # 关闭现有的键盘
        if self.keyboard_window:
            self.keyboard_window.close()
        
        # 创建新的键盘
        self.keyboard_window = SoftwareKeyboard(parent)
        self.current_input = input_widget
        
        # 连接信号
        self.keyboard_window.key_pressed.connect(self.on_key_pressed)
        self.keyboard_window.backspace_pressed.connect(self.on_backspace_pressed)
        self.keyboard_window.enter_pressed.connect(self.on_enter_pressed)
        self.keyboard_window.keyboard_closed.connect(self.on_keyboard_closed)
        
        # 获取输入框的全局位置
        global_pos = input_widget.mapToGlobal(input_widget.rect().bottomLeft())
        
        # 显示键盘
        self.keyboard_window.show_for_input(input_widget, global_pos)
        
        return True
    
    def on_key_pressed(self, key):
        """按键按下事件"""
        # 由 SoftwareKeyboard 直接更新输入框，避免重复写入
        if self.keyboard_window and self.keyboard_window.target_input is not None:
            return
        if self.current_input:
            current_text = self.current_input.text()
            self.current_input.setText(current_text + key)
    
    def on_backspace_pressed(self):
        """退格键事件"""
        # 由 SoftwareKeyboard 直接更新输入框，避免重复写入
        if self.keyboard_window and self.keyboard_window.target_input is not None:
            return
        if self.current_input:
            current_text = self.current_input.text()
            if current_text:
                self.current_input.setText(current_text[:-1])
    
    def on_enter_pressed(self):
        """回车键事件"""
        if self.current_input:
            # 模拟回车键按下
            from PyQt5.QtGui import QKeyEvent
            from PyQt5.QtCore import Qt
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
            QApplication.sendEvent(self.current_input, event)
    
    def on_keyboard_closed(self):
        """键盘关闭事件"""
        self.current_input = None
        self.keyboard_window = None
        try:
            import time
            self.last_closed_time = time.time()
        except Exception:
            pass
    
    def is_visible(self):
        """检查键盘是否可见"""
        return self.keyboard_window and self.keyboard_window.isVisible()
    
    def hide_keyboard(self):
        """隐藏键盘"""
        if self.keyboard_window:
            self.keyboard_window.close()


# 全局键盘管理器实例
_keyboard_manager = None

def get_keyboard_manager():
    """获取全局键盘管理器实例"""
    global _keyboard_manager
    if _keyboard_manager is None:
        _keyboard_manager = SoftwareKeyboardManager()
    return _keyboard_manager


if __name__ == "__main__":
    # 测试软件键盘
    app = QApplication(sys.argv)
    
    # 创建测试窗口
    test_window = QWidget()
    test_window.setWindowTitle("软件键盘测试")
    test_window.setGeometry(100, 100, 400, 200)
    
    layout = QVBoxLayout()
    
    # 测试输入框
    input1 = QLineEdit()
    input1.setPlaceholderText("点击这里显示软件键盘")
    layout.addWidget(input1)
    
    input2 = QLineEdit()
    input2.setPlaceholderText("另一个输入框")
    layout.addWidget(input2)
    
    # 显示键盘按钮（用于手动测试）
    show_btn = QPushButton("显示软件键盘(输入框1)")
    show_btn.clicked.connect(lambda: get_keyboard_manager().show_keyboard_for_input(input1, test_window))
    layout.addWidget(show_btn)
    
    show_btn2 = QPushButton("显示软件键盘(输入框2)")
    show_btn2.clicked.connect(lambda: get_keyboard_manager().show_keyboard_for_input(input2, test_window))
    layout.addWidget(show_btn2)
    
    test_window.setLayout(layout)
    test_window.show()
    
    sys.exit(app.exec_())