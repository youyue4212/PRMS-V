"""
Login Dialog
Provides user login interface
"""
import json
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QCheckBox, QApplication
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
        # 7 寸屏自适应；无边框，贴近工控确认框风格
        from core.industrial_dialogs import fit_dialog_to_screen, _screen_geo
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        sw, sh = _screen_geo(self)
        compact = sh <= 600 or sw <= 1024
        
        # Set dialog style — 固定输入高度，避免 min-height+padding 把布局撑爆再被压叠
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border: 2px solid #2196F3;
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                font-family: 'Microsoft YaHei', sans-serif;
                font-weight: bold;
                background-color: transparent;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 2px solid #444444;
                border-radius: 8px;
                padding: 4px 10px;
                font-family: 'Microsoft YaHei', sans-serif;
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
                padding: 6px 20px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', sans-serif;
                min-width: 100px;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton#cancel_btn {
                background-color: #455a64;
            }
            QPushButton#cancel_btn:pressed {
                background-color: #37474f;
            }
            QCheckBox {
                font-family: 'Microsoft YaHei', sans-serif;
                font-weight: bold;
                background-color: transparent;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 26px;
                height: 26px;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border: 2px solid #2196F3;
            }
            QCheckBox::indicator:unchecked {
                background-color: #2a2a2a;
                border: 2px solid #666666;
            }
        """)
        
        # Main layout — 紧凑竖排，禁止 stretch 挤扁输入框
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(6)
        
        # Title
        title_label = QLabel(_t("login_title"))
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont(FONTS["title"][0], FONTS["title"][1] - 2)
        if len(FONTS["title"]) > 2 and "bold" in FONTS["title"][2]:
            title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #e0e0e0; font-weight: bold;")
        main_layout.addWidget(title_label)

        # 矮屏省高度：不显示副标题
        if not compact:
            subtitle_label = QLabel(_t("login_subtitle"))
            subtitle_label.setAlignment(Qt.AlignCenter)
            subtitle_font = QFont(FONTS["subtitle"][0], FONTS["subtitle"][1] - 2)
            if len(FONTS["subtitle"]) > 2 and "bold" in FONTS["subtitle"][2]:
                subtitle_font.setBold(True)
            subtitle_label.setFont(subtitle_font)
            subtitle_label.setStyleSheet("color: #aaaaaa;")
            main_layout.addWidget(subtitle_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("background-color: #444444;")
        separator.setFixedHeight(1)
        main_layout.addWidget(separator)
        
        field_h = 40 if compact else 44
        btn_h = 40 if compact else 44

        # Username
        username_label = QLabel(_t("login_username"))
        username_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        username_label.setFont(username_font)
        username_label.setStyleSheet("color: #e0e0e0; font-weight: bold;")
        main_layout.addWidget(username_label)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText(_t("login_username_placeholder"))
        self.username_input.setText("")
        self.username_input.setFixedHeight(field_h)
        username_input_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1])
        if len(FONTS["data_value"]) > 2 and "bold" in FONTS["data_value"][2]:
            username_input_font.setBold(True)
        self.username_input.setFont(username_input_font)
        main_layout.addWidget(self.username_input)
        
        # Password
        password_label = QLabel(_t("login_password"))
        password_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        password_label.setFont(password_font)
        password_label.setStyleSheet("color: #e0e0e0; font-weight: bold;")
        main_layout.addWidget(password_label)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText(_t("login_password_placeholder"))
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setText("")
        self.password_input.setFixedHeight(field_h)
        password_input_font = QFont(FONTS["data_value"][0], FONTS["data_value"][1])
        if len(FONTS["data_value"]) > 2 and "bold" in FONTS["data_value"][2]:
            password_input_font.setBold(True)
        self.password_input.setFont(password_input_font)
        main_layout.addWidget(self.password_input)
        
        # Remember password
        self.remember_checkbox = QCheckBox(_t("login_remember"))
        self.remember_checkbox.setChecked(False)
        self.remember_checkbox.setFixedHeight(32)
        checkbox_font = QFont(FONTS["data_key"][0], FONTS["data_key"][1])
        if len(FONTS["data_key"]) > 2 and "bold" in FONTS["data_key"][2]:
            checkbox_font.setBold(True)
        self.remember_checkbox.setFont(checkbox_font)
        self.remember_checkbox.setStyleSheet("color: #e0e0e0;")
        main_layout.addWidget(self.remember_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.setContentsMargins(0, 4, 0, 0)
        
        self.cancel_btn = QPushButton(_t("btn_cancel"))
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setFixedHeight(btn_h)
        self.cancel_btn.clicked.connect(self.reject)
        cancel_btn_font = QFont(FONTS["btn"][0], FONTS["btn"][1])
        self.cancel_btn.setFont(cancel_btn_font)
        button_layout.addWidget(self.cancel_btn, 1)
        
        self.login_btn = QPushButton(_t("btn_login"))
        self.login_btn.setFixedHeight(btn_h)
        self.login_btn.clicked.connect(self.on_login_clicked)
        login_btn_font = QFont(FONTS["btn"][0], FONTS["btn"][1])
        self.login_btn.setFont(login_btn_font)
        button_layout.addWidget(self.login_btn, 1)
        
        main_layout.addLayout(button_layout)
        
        # Default button
        self.login_btn.setDefault(True)
        
        # Set layout
        self.setLayout(main_layout)

        # 按内容估高，再适配屏幕（登录框允许更高，避免输入框重叠）
        self.adjustSize()
        need_h = max(self.sizeHint().height() + 8, 340 if compact else 380)
        fit_dialog_to_screen(
            self, 420, need_h,
            compact_max_w=440, compact_max_h=420,
            max_h_ratio=0.92,
        )
        
        # Enter key
        self.username_input.returnPressed.connect(self.password_input.setFocus)
        self.password_input.returnPressed.connect(self.on_login_clicked)

    def _hide_login_keyboard(self):
        """登录流程中必须收起置顶软键盘，否则会挡住登录框/成功提示。"""
        try:
            from core.software_keyboard import get_keyboard_manager
            get_keyboard_manager().hide_keyboard()
        except Exception:
            pass

    def _cleanup_login_keyboard_filter(self):
        try:
            if hasattr(self, "_login_focus_filter") and self._login_focus_filter is not None:
                QApplication.instance().removeEventFilter(self._login_focus_filter)
                self._login_focus_filter = None
        except Exception:
            pass

    def enable_login_virtual_keyboard(self):
        """工控触摸屏：登录输入自动弹软键盘；普通电脑不弹。"""
        enable_env = os.environ.get("ENABLE_LOGIN_KEYBOARD", "").strip()
        if enable_env == "0":
            return
        try:
            from core.software_keyboard import should_use_software_keyboard
            need_kb = (enable_env == "1") or should_use_software_keyboard()
        except Exception:
            need_kb = enable_env == "1"
        if not need_kb:
            return
        # 每次登录都装专用过滤器（强制开启），避免「第二次交给主窗却不弹」
        try:
            from core.ui_base import FocusEventFilter
            self._login_focus_filter = FocusEventFilter()
            self._login_focus_filter.keyboard_enabled = True
            QApplication.instance().installEventFilter(self._login_focus_filter)
        except Exception as e:
            print(f"Login keyboard enable failed: {e}")

    def accept(self):
        self._hide_login_keyboard()
        self._cleanup_login_keyboard_filter()
        super().accept()

    def reject(self):
        self._hide_login_keyboard()
        self._cleanup_login_keyboard_filter()
        super().reject()

    def closeEvent(self, event):
        """关闭登录框时收起键盘并移除过滤器。"""
        self._hide_login_keyboard()
        self._cleanup_login_keyboard_filter()
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
        # 先收起置顶键盘，避免挡住校验提示或登录成功后的确认框
        self._hide_login_keyboard()

        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        if not username:
            from core.industrial_dialogs import show_warn
            show_warn(self, _t("msg_input_error"), _t("msg_enter_username"))
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
                
                # Close dialog（accept 内会再次确保键盘已隐藏）
                self.accept()
            else:
                from core.industrial_dialogs import show_error
                show_error(self, _t("msg_login_failed"), _t("msg_get_user_failed"))
        else:
            from core.industrial_dialogs import show_warn
            show_warn(self, _t("msg_login_failed"), message)
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
