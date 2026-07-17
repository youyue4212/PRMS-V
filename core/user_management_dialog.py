"""
用户管理对话框
提供用户管理界面，包括添加、编辑、删除用户等功能
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox, QHeaderView,
    QGroupBox, QFormLayout, QWidget, QTabWidget, QFrame, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

from core.user_manager import get_user_manager, UserRole
from core.translation import _t


class UserManagementDialog(QDialog):
    """用户管理对话框"""
    
    # 用户数据更新信号
    users_updated = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_manager = get_user_manager()
        self.setup_ui()
        self.load_users()
        
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle(_t("user_mgmt_title"))
        # 英文表头较长，固定过小会导致显示不全；允许放大
        self.setMinimumSize(920, 640)
        self.resize(960, 680)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        self.title_label = QLabel(_t("user_mgmt_sys_title"))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        main_layout.addWidget(self.title_label)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        self.tab_widget.tabBar().setElideMode(Qt.ElideNone)
        self.tab_widget.tabBar().setExpanding(False)
        
        # 设置选项卡样式 - 使用Arial字体，保持原有字体大小 and 正常粗细
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444444;
                border-radius: 4px;
                background-color: #222222;
            }
            QTabBar::tab {
                background-color: #333333;
                color: #ffffff;
                padding: 8px 18px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-family: "Arial", sans-serif;
                font-size: 14px;
                font-weight: normal;
                min-width: 90px;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
                font-weight: normal;
                border-bottom: 2px solid #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #444444;
                color: #f0f0f0;
            }
        """)
        
        # 用户列表选项卡
        user_list_tab = QWidget()
        self.setup_user_list_tab(user_list_tab)
        self.tab_widget.addTab(user_list_tab, _t("tab_user_list"))
        
        # 添加用户选项卡
        add_user_tab = QWidget()
        self.setup_add_user_tab(add_user_tab)
        self.tab_widget.addTab(add_user_tab, _t("tab_add_user"))
        
        # 修改密码选项卡
        change_password_tab = QWidget()
        self.setup_change_password_tab(change_password_tab)
        self.tab_widget.addTab(change_password_tab, _t("tab_change_pwd"))
        
        main_layout.addWidget(self.tab_widget)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # 刷新按钮
        refresh_btn = QPushButton(_t("btn_refresh_list"))
        refresh_btn.clicked.connect(self.load_users)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton(_t("btn_close"))
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
    
    def setup_user_list_tab(self, tab):
        """设置用户列表选项卡"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 用户表格
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(6)
        self.user_table.setHorizontalHeaderLabels([
            _t("header_username"), _t("header_role"), _t("header_fullname"), 
            _t("header_email"), _t("header_create_time"), _t("header_last_login")
        ])
        header = self.user_table.horizontalHeader()
        header.setMinimumSectionSize(80)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 英文表头较长：前几列按内容适配，最后一列拉伸填满
        for col in range(5):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.user_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.user_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.user_table.setWordWrap(False)
        self.user_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 设置表格样式 - 确保文字清晰可见
        self.user_table.setStyleSheet("""
            QTableWidget {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                gridline-color: #444444;
                font-size: 13px;
                alternate-background-color: #2f2f2f;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #444444;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #333333;
                color: #ffffff;
                padding: 8px 10px;
                border: 1px solid #444444;
                font-weight: bold;
                font-size: 12px;
            }
            QHeaderView::section:checked {
                background-color: #2196F3;
            }
        """)
        
        layout.addWidget(self.user_table)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        # 编辑按钮
        self.edit_btn = QPushButton(_t("btn_edit_user"))
        self.edit_btn.clicked.connect(self.edit_user)
        button_layout.addWidget(self.edit_btn)
        
        # 删除按钮
        self.delete_btn = QPushButton(_t("btn_delete_user"))
        self.delete_btn.clicked.connect(self.delete_user)
        button_layout.addWidget(self.delete_btn)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        tab.setLayout(layout)
    
    def setup_add_user_tab(self, tab):
        """设置添加用户选项卡"""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 表单组
        form_group = QGroupBox(_t("group_add_user"))
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 用户名
        self.new_username_input = QLineEdit()
        self.new_username_input.setPlaceholderText(_t("login_username_placeholder"))
        form_layout.addRow(_t("label_username"), self.new_username_input)
        
        # 密码
        self.new_password_input = QLineEdit()
        self.new_password_input.setPlaceholderText(_t("placeholder_pwd_limit"))
        self.new_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow(_t("label_password"), self.new_password_input)
        
        # 确认密码
        self.new_confirm_password_input = QLineEdit()
        self.new_confirm_password_input.setPlaceholderText(_t("placeholder_confirm_pwd"))
        self.new_confirm_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow(_t("label_confirm_password"), self.new_confirm_password_input)
        
        # 角色
        self.new_role_combo = QComboBox()
        self.new_role_combo.addItem(_t("role_viewer"), UserRole.VIEWER)
        self.new_role_combo.addItem(_t("role_admin"), UserRole.ADMIN)
        form_layout.addRow(_t("label_role"), self.new_role_combo)
        
        # 姓名
        self.new_fullname_input = QLineEdit()
        self.new_fullname_input.setPlaceholderText(_t("placeholder_fullname_opt"))
        form_layout.addRow(_t("label_fullname"), self.new_fullname_input)
        
        # 邮箱
        self.new_email_input = QLineEdit()
        self.new_email_input.setPlaceholderText(_t("placeholder_email_opt"))
        form_layout.addRow(_t("label_email"), self.new_email_input)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # 添加按钮
        add_button_layout = QHBoxLayout()
        add_button_layout.addStretch()
        
        self.add_user_btn = QPushButton(_t("tab_add_user"))
        self.add_user_btn.clicked.connect(self.add_user)
        add_button_layout.addWidget(self.add_user_btn)
        
        layout.addLayout(add_button_layout)
        layout.addStretch()
        
        tab.setLayout(layout)
    
    def setup_change_password_tab(self, tab):
        """设置修改密码选项卡"""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 当前用户信息
        current_user = self.user_manager.get_current_user()
        self.user_info_label = QLabel()
        if current_user:
            role_display = _t("role_admin") if current_user.role == UserRole.ADMIN else _t("role_viewer")
            self.user_info_label.setText(_t("label_current_user", user=current_user.username, role=role_display))
        layout.addWidget(self.user_info_label)
        
        # 表单组
        form_group = QGroupBox(_t("group_change_pwd"))
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 选择用户（仅管理员）
        self.password_user_combo = QComboBox()
        self.password_user_combo.addItem(_t("label_current_user", user="", role="").replace(" ()", ""), "current")
        
        # 如果是管理员，添加所有用户
        if self.user_manager.can_manage_users():
            users = self.user_manager.get_all_users()
            for user in users:
                if user['username'] != current_user.username:
                    role_display = _t("role_admin") if user['role'] == 'admin' else _t("role_viewer")
                    display_text = f"{user['username']} ({role_display})"
                    self.password_user_combo.addItem(display_text, user['username'])
        
        form_layout.addRow(_t("label_user"), self.password_user_combo)
        
        # 旧密码（仅修改当前用户密码时需要）
        self.old_password_input = QLineEdit()
        self.old_password_input.setPlaceholderText(_t("placeholder_old_pwd"))
        self.old_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow(_t("label_old_pwd"), self.old_password_input)
        
        # 新密码
        self.new_password_input2 = QLineEdit()
        self.new_password_input2.setPlaceholderText(_t("placeholder_new_pwd_limit"))
        self.new_password_input2.setEchoMode(QLineEdit.Password)
        form_layout.addRow(_t("label_new_pwd"), self.new_password_input2)
        
        # 确认新密码
        self.new_confirm_password_input2 = QLineEdit()
        self.new_confirm_password_input2.setPlaceholderText(_t("placeholder_confirm_new_pwd"))
        self.new_confirm_password_input2.setEchoMode(QLineEdit.Password)
        form_layout.addRow(_t("label_confirm_new_pwd"), self.new_confirm_password_input2)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # 更新用户选择变化
        self.password_user_combo.currentIndexChanged.connect(self.on_password_user_changed)
        self.on_password_user_changed(0)  # 初始更新
        
        # 修改按钮
        change_button_layout = QHBoxLayout()
        change_button_layout.addStretch()
        
        self.change_password_btn = QPushButton(_t("tab_change_pwd"))
        self.change_password_btn.clicked.connect(self.change_password)
        change_button_layout.addWidget(self.change_password_btn)
        
        layout.addLayout(change_button_layout)
        layout.addStretch()
        
        tab.setLayout(layout)
    
    def on_password_user_changed(self, index):
        """密码用户选择变化"""
        user_data = self.password_user_combo.itemData(index)
        if user_data == "current":
            # 修改当前用户密码，需要旧密码
            self.old_password_input.setEnabled(True)
            self.old_password_input.setPlaceholderText("请输入旧密码")
        else:
            # 管理员修改其他用户密码，不需要旧密码
            self.old_password_input.setEnabled(False)
            self.old_password_input.setPlaceholderText("管理员修改其他用户密码无需旧密码")
            self.old_password_input.clear()
    
    def load_users(self):
        """加载用户列表"""
        if not self.user_manager.can_manage_users():
            QMessageBox.warning(self, _t("msg_no_permission"), _t("msg_no_mgmt_permission"))
            return
        
        users = self.user_manager.get_all_users()
        
        self.user_table.setRowCount(len(users))
        
        for row, user in enumerate(users):
            # 用户名
            username_item = QTableWidgetItem(user['username'])
            self.user_table.setItem(row, 0, username_item)
            
            # 角色
            role_display = _t("role_admin") if user['role'] == 'admin' else _t("role_viewer")
            role_item = QTableWidgetItem(role_display)
            self.user_table.setItem(row, 1, role_item)
            
            # 姓名
            fullname_item = QTableWidgetItem(user['full_name'] or "")
            self.user_table.setItem(row, 2, fullname_item)
            
            # 邮箱
            email_item = QTableWidgetItem(user['email'] or "")
            self.user_table.setItem(row, 3, email_item)
            
            # 创建时间
            created_item = QTableWidgetItem(user['created_at'] or "")
            self.user_table.setItem(row, 4, created_item)
            
            # 最后登录
            last_login_item = QTableWidgetItem(user['last_login'] or "")
            self.user_table.setItem(row, 5, last_login_item)
    
    def add_user(self):
        """添加新用户"""
        if not self.user_manager.can_manage_users():
            QMessageBox.warning(self, _t("msg_no_permission"), _t("msg_no_add_permission"))
            return
        
        username = self.new_username_input.text().strip()
        password = self.new_password_input.text().strip()
        confirm_password = self.new_confirm_password_input.text().strip()
        role = self.new_role_combo.currentData()
        full_name = self.new_fullname_input.text().strip()
        email = self.new_email_input.text().strip()
        
        # 验证输入
        if not username:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_enter_username"))
            self.new_username_input.setFocus()
            return
        
        if not password:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_enter_password"))
            self.new_password_input.setFocus()
            return
        
        if password != confirm_password:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_pwd_mismatch"))
            self.new_confirm_password_input.setFocus()
            return
        
        if len(password) < 6:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_pwd_too_short"))
            self.new_password_input.setFocus()
            return
        
        # 添加用户
        success, message = self.user_manager.add_user(
            username, password, role, full_name, email
        )
        
        if success:
            QMessageBox.information(self, _t("msg_add_success"), _t("msg_add_user_success", user=username))
            # 清空表单
            self.new_username_input.clear()
            self.new_password_input.clear()
            self.new_confirm_password_input.clear()
            self.new_fullname_input.clear()
            self.new_email_input.clear()
            # 刷新用户列表
            self.load_users()
            # 发出更新信号
            self.users_updated.emit()
        else:
            QMessageBox.warning(self, _t("msg_add_failed"), message)
    
    def edit_user(self):
        """编辑用户"""
        if not self.user_manager.can_manage_users():
            QMessageBox.warning(self, _t("msg_no_permission"), _t("msg_no_mgmt_permission"))
            return
        
        selected_rows = self.user_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_select_user_to_edit"))
            return
        
        row = selected_rows[0].row()
        username = self.user_table.item(row, 0).text()
        
        # 打开编辑对话框
        dialog = EditUserDialog(username, self)
        if dialog.exec_() == QDialog.Accepted:
            self.load_users()
            self.users_updated.emit()
    
    def delete_user(self):
        """删除用户"""
        if not self.user_manager.can_manage_users():
            QMessageBox.warning(self, _t("msg_no_permission"), _t("msg_no_mgmt_permission"))
            return
        
        selected_rows = self.user_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_select_user_to_delete"))
            return
        
        row = selected_rows[0].row()
        username = self.user_table.item(row, 0).text()
        
        # 确认删除
        reply = QMessageBox.question(
            self, _t("msg_delete_confirm_title"),
            _t("msg_delete_confirm_msg", user=username),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.user_manager.delete_user(username)
            
            if success:
                QMessageBox.information(self, _t("msg_delete_success"), message)
                self.load_users()
                self.users_updated.emit()
            else:
                QMessageBox.warning(self, _t("msg_delete_failed"), message)
    
    def change_password(self):
        """修改密码"""
        user_data = self.password_user_combo.currentData()
        
        if user_data == "current":
            # 修改当前用户密码
            username = self.user_manager.get_current_user().username
            old_password = self.old_password_input.text().strip()
        else:
            # 管理员修改其他用户密码
            username = user_data
            old_password = ""  # 管理员修改其他用户密码不需要旧密码
        
        new_password = self.new_password_input2.text().strip()
        confirm_password = self.new_confirm_password_input2.text().strip()
        
        # 验证输入
        if not new_password:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_enter_new_pwd"))
            self.new_password_input2.setFocus()
            return
        
        if new_password != confirm_password:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_pwd_mismatch"))
            self.new_confirm_password_input2.setFocus()
            return
        
        if len(new_password) < 6:
            QMessageBox.warning(self, _t("msg_input_error"), _t("msg_pwd_too_short"))
            self.new_password_input2.setFocus()
            return
        
        # 修改密码
        success, message = self.user_manager.change_password(
            username, old_password, new_password
        )
        
        if success:
            QMessageBox.information(self, _t("msg_change_pwd_success"), _t("msg_change_pwd_success_msg"))
            # 清空表单
            self.old_password_input.clear()
            self.new_password_input2.clear()
            self.new_confirm_password_input2.clear()
        else:
            QMessageBox.warning(self, _t("msg_change_pwd_failed"), message)


class EditUserDialog(QDialog):
    """编辑用户对话框"""
    
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.username = username
        self.user_manager = get_user_manager()
        self.setup_ui()
        self.load_user_data()
        
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle(_t("msg_edit_user_title", user=self.username))
        self.setFixedSize(400, 300)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 用户名（只读）
        username_label = QLabel(self.username)
        form_layout.addRow(_t("label_username"), username_label)
        
        # 角色
        self.role_combo = QComboBox()
        self.role_combo.addItem(_t("role_viewer"), UserRole.VIEWER)
        self.role_combo.addItem(_t("role_admin"), UserRole.ADMIN)
        form_layout.addRow(_t("label_role"), self.role_combo)
        
        # 姓名
        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText(_t("placeholder_fullname_opt"))
        form_layout.addRow(_t("label_fullname"), self.fullname_input)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText(_t("placeholder_email_opt"))
        form_layout.addRow(_t("label_email"), self.email_input)
        
        form_group = QGroupBox(_t("group_add_user"))
        form_group.setLayout(form_layout)
        main_layout.addWidget(form_group)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 保存按钮
        save_btn = QPushButton(_t("btn_save"))
        save_btn.clicked.connect(self.save_user)
        button_layout.addWidget(save_btn)
        
        # 取消按钮
        cancel_btn = QPushButton(_t("btn_cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
    
    def load_user_data(self):
        """加载用户数据"""
        user = self.user_manager.get_user(self.username)
        if user:
            # 设置角色
            if user['role'] == 'admin':
                self.role_combo.setCurrentIndex(1)
            else:
                self.role_combo.setCurrentIndex(0)
            
            # 设置姓名
            if user['full_name']:
                self.fullname_input.setText(user['full_name'])
            
            # 设置邮箱
            if user['email']:
                self.email_input.setText(user['email'])
    
    def save_user(self):
        """保存用户信息"""
        role = self.role_combo.currentData()
        full_name = self.fullname_input.text().strip()
        email = self.email_input.text().strip()
        
        # 更新用户信息 - 使用关键字参数
        success, message = self.user_manager.update_user(
            self.username, role=role, full_name=full_name, email=email
        )
        
        if success:
            QMessageBox.information(self, _t("msg_change_pwd_success"), message)
            self.accept()
        else:
            QMessageBox.warning(self, _t("msg_change_pwd_failed"), message)
