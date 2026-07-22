"""
Login Dialog
Provides user login interface
"""
import json
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QCheckBox, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtGui import QFont, QIcon

from core.user_manager import get_user_manager, UserRole
from core.translation import _t

# 字体配置
FONTS = {
    "title": ("微软雅黑", 16, "bold"),        # 主标题
    "subtitle": ("微软雅黑", 14, "bold"),     # 子标题（卡片标题）
    "mode": ("微软雅黑", 12, "bold"),         # 模式标识
    "data_key": ("微软雅黑", 12),             # 数据项键名
    "data_value": ("微软雅黑", 12, "bold"),   # 数据项值
    "btn": ("微软雅黑", 11),                  # 按钮字体
    "tip": ("微软雅黑", 10)                   # 提示文本
}

# 间距配置
PADDING = {
    "window": (20, 15),         # 窗口内边距
    "card": (25, 20),           # 卡片内边距
    "mode_frame": (15, 10),     # 模式区边距
    "operate_frame": (15, 10),  # 操作区边距
    "data_item": (12, 10),      # 数据项间距
    "btn": (8, 15)              # 按钮内边距
}


class LoginDialog(QDialog):
    """Login Dialog"""
    
    # 登录成功信号
    login_successful = pyqtSignal(str, UserRole)  # 用户名, 角色
    
    def __init__(self, parent=None, prefer_viewer_autofill=False):
        super().__init__(parent)
        self.user_manager = get_user_manager()
        self.settings = QSettings("Raysen", "Spectrometer")
        self.prefer_viewer_autofill = prefer_viewer_autofill
        self.setup_ui()
        self.load_saved_credentials()
        self.enable_login_virtual_keyboard()
        
    def setup_ui(self):
        """Setup UI - Clean and direct layout"""
        self.setWindowTitle(_t("login_title"))
        self.setFixedSize(500, 450)
        
        # Set dialog style
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border: 2px solid #444444;
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                font-family: 'Microsoft YaHei', sans-serif;
                font-weight: bold;
                background-color: #1a1a1a;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 2px solid #444444;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Microsoft YaHei', sans-serif;
                min-height: 40px;
                selection-background-color: #2196F3;
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
                background-color: #2f2f2f;
            }
            QLineEdit::placeholder {
                color: #888888;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', sans-serif;
                min-height: 40px;
                min-width: 90px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton#cancel_btn {
                background-color: #666666;
            }
            QPushButton#cancel_btn:hover {
                background-color: #555555;
            }
            QCheckBox {
                font-family: 'Microsoft YaHei', sans-serif;
                font-weight: bold;
                background-color: #1a1a1a;  /* 明确设置背景色为深灰色 */
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border: 2px solid #2196F3;
            }
            QCheckBox::indicator:unchecked {
                background-color: #2a2a2a;
                border: 2px solid #444444;
            }
        """)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(30, 25, 30, 30)  # 减少顶部边距从30到25，让整体上移
        main_layout.setSpacing(10)  # 进一步减少间距从10到8
        
        # Title
        title_label = QLabel(_t("login_title"))
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont(FONTS["title"][0], FONTS["title"][1] - 2)
        if len(FONTS["title"]) > 2 and "bold" in FONTS["title"][2]:
            title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #e0e0e0; font-weight: bold;")  # 更柔和的白色
        main_layout.addWidget(title_label)
        
        subtitle_label = QLabel(_t("login_subtitle"))
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_font = QFont(FONTS["subtitle"][0], FONTS["subtitle"][1] - 2)
        if len(FONTS["subtitle"]) > 2 and "bold" in FONTS["subtitle"][2]:
            subtitle_font.setBold(True)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet("color: #aaaaaa;")  # 更深的灰色
        main_layout.addWidget(subtitle_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("background-color: #444444; margin: 5px 0;")
        separator.setFixedHeight(2)
        main_layout.addWidget(separator)
        
        # Add spacing after separator to move username label down a bit more
        main_layout.addSpacing(10)  # 增加间距从8到10，让username标签再下移一点
        
        # Username
        username_label = QLabel(_t("login_username"))
        username_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        username_label.setFont(username_font)
        username_label.setStyleSheet("color: #e0e0e0; font-weight: bold; margin-bottom: 2px;")  # 减少间距从5px到2px，让输入框上移
        main_layout.addWidget(username_label)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText(_t("login_username_placeholder"))
        self.username_input.setText("")
        username_input_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1])
        if len(FONTS["data_value"]) > 2 and "bold" in FONTS["data_value"][2]:
            username_input_font.setBold(True)
        self.username_input.setFont(username_input_font)
        main_layout.addWidget(self.username_input)
        
        # Spacing - 减少间距从8到4，让password往上移动一些
        main_layout.addSpacing(4)
        
        # Password
        password_label = QLabel(_t("login_password"))
        password_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        password_label.setFont(password_font)
        password_label.setStyleSheet("color: #e0e0e0; font-weight: bold; margin-bottom: 2px;")  # 减少间距从5px到2px，让输入框上移
        main_layout.addWidget(password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText(_t("login_password_placeholder"))
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setText("")
        password_input_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1])
        if len(FONTS["data_value"]) > 2 and "bold" in FONTS["data_value"][2]:
            password_input_font.setBold(True)
        self.password_input.setFont(password_input_font)
        main_layout.addWidget(self.password_input)
        
        # Spacing - 增加间距从5到8，让remember password往下移动一点点
        main_layout.addSpacing(8)
        
        # Remember password - use same font size as password label
        self.remember_checkbox = QCheckBox(_t("login_remember"))
        self.remember_checkbox.setChecked(False)
        # Use data_key font size (12px) instead of tip font size (10px)
        checkbox_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        if len(FONTS["data_key"]) > 2 and "bold" in FONTS["data_key"][2]:
            checkbox_font.setBold(True)
        self.remember_checkbox.setFont(checkbox_font)
        self.remember_checkbox.setStyleSheet("color: #e0e0e0;")  # 更柔和的白色
        main_layout.addWidget(self.remember_checkbox)
        
        # Stretch
        main_layout.addStretch(1)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.cancel_btn = QPushButton(_t("btn_cancel"))
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.clicked.connect(self.reject)
        cancel_btn_font = QFont(FONTS["btn"][0], FONTS["btn"][1])
        self.cancel_btn.setFont(cancel_btn_font)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch(1)
        
        self.login_btn = QPushButton(_t("btn_login"))
        self.login_btn.clicked.connect(self.on_login_clicked)
        login_btn_font = QFont(FONTS["btn"][0], FONTS["btn"][1])
        self.login_btn.setFont(login_btn_font)
        button_layout.addWidget(self.login_btn)
        
        main_layout.addLayout(button_layout)
        
        # Default button
        self.login_btn.setDefault(True)
        
        # Set layout
        self.setLayout(main_layout)
        
        # Enter key
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self.on_login_clicked)

    def enable_login_virtual_keyboard(self):
        """Enable virtual keyboard auto-trigger on login dialog."""
        enable_env = os.environ.get("ENABLE_LOGIN_KEYBOARD", "1").strip()
        if enable_env == "0":
            return
        if str(os.environ.get("USE_SOFTWARE_KEYBOARD", "")).strip() == "1":
            # 内置键盘已由全局过滤器处理，避免重复安装导致双键盘
            return
        try:
            from core.ui_base import FocusEventFilter
            self._login_focus_filter = FocusEventFilter()
            self._login_focus_filter.keyboard_enabled = True
            QApplication.instance().installEventFilter(self._login_focus_filter)
        except Exception as e:
            print(f"Login keyboard enable failed: {e}")

    def closeEvent(self, event):
        """Remove login keyboard filter on close."""
        try:
            if hasattr(self, "_login_focus_filter"):
                QApplication.instance().removeEventFilter(self._login_focus_filter)
        except Exception:
            pass
        super().closeEvent(event)
    
    def load_saved_credentials(self):
        """Load saved credentials from settings"""
        if self.prefer_viewer_autofill:
            viewer_username = self.user_manager.ensure_viewer_user()
            self.username_input.setText(viewer_username)
            self.password_input.setText("")
            self.remember_checkbox.setChecked(False)
            return

        remember = self.settings.value("login/remember_password", False, type=bool)
        if remember:
            username = self.settings.value("login/username", "", type=str)
            password = self.settings.value("login/password", "", type=str)
            
            if username:
                self.username_input.setText(username)
                self.password_input.setText(password)
                self.remember_checkbox.setChecked(True)
    
    def save_credentials(self, username, password, remember):
        """Save credentials to settings"""
        if remember:
            # Save credentials
            self.settings.setValue("login/remember_password", True)
            self.settings.setValue("login/username", username)
            self.settings.setValue("login/password", password)
        else:
            # Clear saved credentials
            self.settings.setValue("login/remember_password", False)
            self.settings.remove("login/username")
            self.settings.remove("login/password")
    
    def on_login_clicked(self):
        """Login button click event"""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        if not username:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_enter_username"))
            self.username_input.setFocus()
            return
        
        # Allow empty password for some users (like 'user')
        # Don't check if password is empty
        
        # Authenticate
        success, message = self.user_manager.authenticate(username, password)
        
        if success:
            # Get current user role
            current_user = self.user_manager.get_current_user()
            if current_user:
                # Save or clear credentials based on remember checkbox
                self.save_credentials(username, password, self.remember_checkbox.isChecked())
                
                # Emit login successful signal
                self.login_successful.emit(username, current_user.role)
                
                # Close dialog
                self.accept()
            else:
                QMessageBox.critical(self, _t("msg_login_failed"), _t("msg_get_user_failed"))
        else:
            QMessageBox.warning(self, _t("msg_login_failed"), message)
            self.password_input.clear()
            self.password_input.setFocus()
    
    def get_current_user_info(self):
        """Get current user information"""
        current_user = self.user_manager.get_current_user()
        if current_user:
            return {
                'username': current_user.username,
                'role': current_user.role,
                'full_name': current_user.full_name
            }
        return None
