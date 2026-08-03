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
        """初始化UI：工业风数字盘为主，字母为辅。"""
        self.setWindowTitle("输入键盘")
        self.setFixedSize(360, 420)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        
        title_layout = QHBoxLayout()
        self.title_label = QLabel("输入键盘")
        self.title_label.setFont(QFont("Arial", 13, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        title_layout.addWidget(self.title_label, 1)
        
        self.toggle_btn = QPushButton("ABC")
        self.toggle_btn.setFixedSize(56, 32)
        self.toggle_btn.setToolTip("切换数字/字母")
        self.toggle_btn.clicked.connect(self.toggle_mode)
        title_layout.addWidget(self.toggle_btn)

        self.case_btn = QPushButton("⇧")
        self.case_btn.setFixedSize(40, 32)
        self.case_btn.setToolTip("大小写")
        self.case_btn.clicked.connect(self.toggle_case)
        self.case_btn.setVisible(False)
        title_layout.addWidget(self.case_btn)

        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(36, 32)
        self.close_btn.setToolTip("关闭")
        self.close_btn.clicked.connect(self.close_keyboard)
        title_layout.addWidget(self.close_btn)
        
        main_layout.addLayout(title_layout)
        
        self.display_label = QLabel("")
        self.display_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 20px;
                font-weight: bold;
                color: #f5f5f5;
                min-height: 32px;
                max-height: 40px;
            }
        """)
        self.display_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        main_layout.addWidget(self.display_label)
        
        self.keyboard_layout = QGridLayout()
        self.keyboard_layout.setSpacing(8)
        self.keyboard_layout.setContentsMargins(0, 4, 0, 0)
        self.keyboard_layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.keyboard_mode = "numeric"
        self.adjust_size_for_mode()
        self.build_keyboard_layout()

        main_layout.addLayout(self.keyboard_layout)
        self.setLayout(main_layout)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #2d2d2d;
                border: 2px solid #555555;
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
        
        self.display_text = ""
        self.update_display()

    def adjust_size_for_mode(self):
        """根据键盘模式调整对话框尺寸。"""
        screen_geometry = QApplication.desktop().screenGeometry()
        if self.keyboard_mode == "alpha":
            width = min(760, max(640, int(screen_geometry.width() * 0.55)))
            height = min(360, max(300, int(screen_geometry.height() * 0.38)))
            self.setFixedSize(width, height)
        else:
            # 竖向计算器盘：键大、误触少
            width = min(400, max(340, int(screen_geometry.width() * 0.32)))
            height = min(460, max(400, int(screen_geometry.height() * 0.48)))
            self.setFixedSize(width, height)

    def clear_keyboard_layout(self):
        while self.keyboard_layout.count():
            item = self.keyboard_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _key_size(self, cols, rows_hint=4):
        """按当前对话框尺寸估算键帽大小，保证铺满且留边距。"""
        avail_w = max(200, self.width() - 28)
        avail_h = max(160, self.height() - 120)
        bw = max(48, int((avail_w - 8 * (cols - 1)) / cols))
        bh = max(44, int((avail_h - 8 * (rows_hint - 1)) / rows_hint))
        return (bw, bh)

    def build_keyboard_layout(self):
        self.clear_keyboard_layout()
        if hasattr(self, "case_btn"):
            self.case_btn.setVisible(self.keyboard_mode == "alpha")

        if self.keyboard_mode == "numeric":
            # 工业计算器盘：789 在上，右侧功能键，底栏 . 0 -
            cols = 4
            for col in range(cols):
                self.keyboard_layout.setColumnStretch(col, 1)
            for row in range(4):
                self.keyboard_layout.setRowStretch(row, 1)

            bw, bh = self._key_size(cols, 4)
            font_size = 20 if bw >= 64 else 18

            num_keys = [
                ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
                ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
                ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
                (".", 3, 0), ("0", 3, 1), ("-", 3, 2),
            ]
            for text, row, col in num_keys:
                btn = self.create_number_button(text, size=(bw, bh), font_size=font_size)
                self.keyboard_layout.addWidget(btn, row, col)

            self.backspace_btn = self.create_special_button("⌫", "backspace", size=(bw, bh), font_size=18)
            self.backspace_btn.clicked.connect(self.on_backspace)
            self.keyboard_layout.addWidget(self.backspace_btn, 0, 3)

            self.clear_btn = self.create_special_button("清除", "clear", size=(bw, bh), font_size=14)
            self.clear_btn.clicked.connect(self.on_clear)
            self.keyboard_layout.addWidget(self.clear_btn, 1, 3)

            self.enter_btn = self.create_special_button("确定", "enter", size=(bw, bh * 2 + 8), font_size=16)
            self.enter_btn.clicked.connect(self.on_enter)
            self.keyboard_layout.addWidget(self.enter_btn, 2, 3, 2, 1)

        else:
            # QWERTY：三行字母 + 底栏功能键
            cols = 10
            for col in range(cols):
                self.keyboard_layout.setColumnStretch(col, 1)
            for row in range(4):
                self.keyboard_layout.setRowStretch(row, 1)

            bw, bh = self._key_size(cols, 4)
            # 字母键略窄于估算，避免挤出屏幕
            bw = min(bw, 62)
            bh = min(bh, 52)
            font_size = 16 if bw >= 50 else 14

            rows = [
                list("QWERTYUIOP"),
                list("ASDFGHJKL"),
                list("ZXCVBNM"),
            ]
            # 中间两行左右留空，更接近实体键盘视觉对齐
            row_offsets = [0, 0, 1]
            for r, row_keys in enumerate(rows):
                offset = row_offsets[r]
                for c, key in enumerate(row_keys):
                    display_key = key if self.is_uppercase else key.lower()
                    btn = self.create_number_button(display_key, size=(bw, bh), font_size=font_size)
                    self.keyboard_layout.addWidget(btn, r, c + offset)

            # 底栏：123 | 空格 | ⌫ | 清除 | 确定
            mode_btn = self.create_special_button("123", "mode", size=(bw * 2 + 8, bh), font_size=14)
            mode_btn.clicked.connect(self.toggle_mode)
            self.keyboard_layout.addWidget(mode_btn, 3, 0, 1, 2)

            self.space_btn = self.create_number_button(" ", size=(bw, bh), font_size=14)
            self.space_btn.setText("空格")
            self.keyboard_layout.addWidget(self.space_btn, 3, 2, 1, 4)

            self.backspace_btn = self.create_special_button("⌫", "backspace", size=(bw, bh), font_size=14)
            self.backspace_btn.clicked.connect(self.on_backspace)
            self.keyboard_layout.addWidget(self.backspace_btn, 3, 6)

            self.clear_btn = self.create_special_button("清除", "clear", size=(bw, bh), font_size=12)
            self.clear_btn.clicked.connect(self.on_clear)
            self.keyboard_layout.addWidget(self.clear_btn, 3, 7)

            self.enter_btn = self.create_special_button("确定", "enter", size=(bw, bh), font_size=12)
            self.enter_btn.clicked.connect(self.on_enter)
            self.keyboard_layout.addWidget(self.enter_btn, 3, 8, 1, 2)

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
        if hasattr(self, "case_btn"):
            self.case_btn.setStyleSheet(
                "QPushButton { background-color: #4caf50; border-radius: 4px; }"
                if self.is_uppercase else
                "QPushButton { background-color: #555555; border-radius: 4px; }"
            )
        if self.keyboard_mode == "alpha":
            self.build_keyboard_layout()
    
    def create_number_button(self, text, size=(70, 50), font_size=16):
        """创建数字/字母按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(size[0], size[1])
        btn.setFont(QFont("Arial", font_size, QFont.Bold))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #454545;
                color: white;
                border: 1px solid #666666;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #565656;
                border-color: #888888;
            }
            QPushButton:pressed {
                background-color: #2f2f2f;
            }
        """)
        btn.clicked.connect(lambda checked=False, t=text: self.on_number_click(t))
        return btn
    
    def create_special_button(self, text, button_type, size=(70, 50), font_size=16):
        """创建特殊功能按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(size[0], size[1])
        btn.setMinimumSize(size[0], size[1])
        btn.setFont(QFont("Arial", font_size, QFont.Bold))
        
        if button_type == "backspace":
            color = "#e69138"
        elif button_type == "clear":
            color = "#d9534f"
        elif button_type == "enter":
            color = "#5cb85c"
        elif button_type == "mode":
            color = "#5bc0de"
        else:
            color = "#5bc0de"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: 1px solid {color};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color(color, 18)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color(color, -22)};
            }}
        """)
        
        return btn
    
    def adjust_color(self, color, amount):
        """调整 #RRGGBB 亮度。"""
        try:
            c = color.lstrip("#")
            if len(c) != 6:
                return color
            r = max(0, min(255, int(c[0:2], 16) + amount))
            g = max(0, min(255, int(c[2:4], 16) + amount))
            b = max(0, min(255, int(c[4:6], 16) + amount))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color
    
    def _notify_activity(self):
        """把键盘上的操作计入“用户活动”，重置管理员无操作超时。

        键盘是独立窗口，其事件不经过主窗口的事件过滤器，若不主动通知，
        使用键盘期间管理员会被判为发呆，约3分钟后触发超时。
        """
        try:
            from core.timeout_manager import get_timeout_manager
            get_timeout_manager().update_operate_time()
        except Exception:
            pass

    def on_number_click(self, text):
        """数字按钮点击事件"""
        self._notify_activity()
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
        self._notify_activity()
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
        self._notify_activity()
        self.display_text = ""
        self.update_display()
        self.replace_on_first_input = True
        
        # 如果有关联的输入框，直接清空输入框
        if self.target_input:
            self._set_target_text("")
    
    def on_enter(self):
        """回车键事件"""
        self._notify_activity()
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
            self.display_label.setText("")
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
        """为指定的输入框显示键盘。

        普通文本框（登录用户名/密码等）默认字母盘；SpinBox 默认数字盘。
        不在每次 show 时 rebuild，仅模式切换时重建。
        """
        self.set_target_input(input_widget)
        self.replace_on_first_input = isinstance(input_widget, (QSpinBox, QDoubleSpinBox))
        want_numeric = isinstance(input_widget, (QSpinBox, QDoubleSpinBox))
        try:
            self.title_label.setText("输入键盘")
            target_mode = "numeric" if want_numeric else "alpha"
            if self.keyboard_mode != target_mode:
                self.keyboard_mode = target_mode
                self.toggle_btn.setText("ABC" if target_mode == "numeric" else "123")
                self.adjust_size_for_mode()
                self.build_keyboard_layout()
            else:
                self.toggle_btn.setText("ABC" if target_mode == "numeric" else "123")
        except Exception:
            pass

        self._place_near_input(input_widget, position)
        self.show()
        self.raise_()
        self.activateWindow()

    def _place_near_input(self, input_widget, position=None):
        """尽量贴近输入框，并优先对齐所属窗口中心，避免掉到屏幕最底部挡住登录按钮。"""
        screen = QApplication.desktop().screenGeometry()
        kb_w, kb_h = self.width(), self.height()
        margin = 8

        # 水平：相对所属顶层窗口居中（登录框场景更自然）
        try:
            host = input_widget.window()
            if host is not None:
                hg = host.frameGeometry()
                x = hg.center().x() - kb_w // 2
            else:
                x = (screen.width() - kb_w) // 2
        except Exception:
            x = (screen.width() - kb_w) // 2

        # 垂直：优先放在输入框下方；放不下则放到上方；仍不够则屏幕垂直居中
        try:
            input_top = input_widget.mapToGlobal(input_widget.rect().topLeft()).y()
            input_bottom = input_widget.mapToGlobal(input_widget.rect().bottomLeft()).y()
        except Exception:
            input_top = screen.center().y()
            input_bottom = input_top

        if position is not None:
            y_below = position.y() + margin
        else:
            y_below = input_bottom + margin

        if y_below + kb_h <= screen.bottom() - margin:
            y = y_below
        else:
            y_above = input_top - kb_h - margin
            if y_above >= screen.top() + margin:
                y = y_above
            else:
                y = screen.top() + max(margin, (screen.height() - kb_h) // 2)

        x = max(screen.left() + margin, min(x, screen.right() - kb_w - margin))
        y = max(screen.top() + margin, min(y, screen.bottom() - kb_h - margin))
        self.move(x, y)
    
    def close_keyboard(self):
        """隐藏键盘（不销毁窗口）。改样式前长时间稳定的关键做法是 hide，不是 close+DeleteOnClose。"""
        self.commit_target_input()
        self.hide()
        self.keyboard_closed.emit()

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
        self._notify_activity()
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
        """系统 close 时也按“隐藏”处理，避免误销毁单例键盘。"""
        self.hide()
        self.keyboard_closed.emit()
        event.ignore()


class SoftwareKeyboardManager:
    """软件键盘管理器：单例窗口 + hide/show（对齐改样式前长时间可稳定弹出的生命周期）。"""
    
    def __init__(self):
        self.keyboard_window = None
        self.current_input = None
        self.last_closed_time = 0

    @staticmethod
    def _widget_alive(widget):
        if widget is None:
            return False
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False

    def _ensure_keyboard(self):
        """复用同一键盘窗口；仅在不存在/已销毁时新建。禁止 WA_DeleteOnClose。"""
        if self._widget_alive(self.keyboard_window):
            return self.keyboard_window
        self.keyboard_window = SoftwareKeyboard(None)
        self.keyboard_window.setAttribute(Qt.WA_DeleteOnClose, False)
        self.keyboard_window.key_pressed.connect(self.on_key_pressed)
        self.keyboard_window.backspace_pressed.connect(self.on_backspace_pressed)
        self.keyboard_window.enter_pressed.connect(self.on_enter_pressed)
        self.keyboard_window.keyboard_closed.connect(self.on_keyboard_closed)
        return self.keyboard_window
    
    def show_keyboard_for_input(self, input_widget, parent=None):
        """为输入框显示软件键盘（复用同一窗口）。"""
        win = self._ensure_keyboard()
        self.current_input = input_widget
        try:
            global_pos = input_widget.mapToGlobal(input_widget.rect().bottomLeft())
        except Exception:
            global_pos = None
        win.show_for_input(input_widget, global_pos)
        return True
    
    def on_key_pressed(self, key):
        if self._widget_alive(self.keyboard_window) and self.keyboard_window.target_input is not None:
            return
        if self.current_input:
            current_text = self.current_input.text()
            self.current_input.setText(current_text + key)
    
    def on_backspace_pressed(self):
        if self._widget_alive(self.keyboard_window) and self.keyboard_window.target_input is not None:
            return
        if self.current_input:
            current_text = self.current_input.text()
            if current_text:
                self.current_input.setText(current_text[:-1])
    
    def on_enter_pressed(self):
        if self.current_input:
            from PyQt5.QtGui import QKeyEvent
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
            QApplication.sendEvent(self.current_input, event)
    
    def on_keyboard_closed(self):
        """关闭回调：只清业务引用。不 clearFocus（改样式时加的，触摸屏上容易导致再也 FocusIn 不了）。"""
        self.current_input = None
        # 保持 keyboard_window 实例，供下次 show
        try:
            import time
            self.last_closed_time = time.time()
        except Exception:
            pass
    
    def is_visible(self):
        w = self.keyboard_window
        if not self._widget_alive(w):
            self.keyboard_window = None
            return False
        try:
            return w.isVisible()
        except RuntimeError:
            self.keyboard_window = None
            return False
    
    def hide_keyboard(self):
        """隐藏键盘（管理员超时等场景）。"""
        if self._widget_alive(self.keyboard_window):
            try:
                self.keyboard_window.hide()
            except RuntimeError:
                self.keyboard_window = None
        self.current_input = None
        try:
            import time
            self.last_closed_time = time.time()
        except Exception:
            pass


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