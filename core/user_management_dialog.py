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
        self.setWindowTitle("用户管理")
        self.setFixedSize(800, 600)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("用户管理系统")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        main_layout.addWidget(title_label)
        
        # 创建选项卡
        tab_widget = QTabWidget()
        
        # 设置选项卡样式 - 使用Arial字体，保持原有字体大小和正常粗细
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444444;
                border-radius: 4px;
                background-color: #222222;
            }
            QTabBar::tab {
                background-color: #333333;
                color: #ffffff;  /* 白色字体 */
                padding: 8px 16px;  /* 原有内边距 */
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-family: "Arial", sans-serif;  /* 使用Arial字体 */
                font-size: 14px;  /* 保持原有字体大小 */
                font-weight: normal;  /* 正常粗细，不加粗 */
                letter-spacing: 0.5px;  /* 字间距 */
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
                font-weight: normal;  /* 选中时也不加粗 */
                border-bottom: 2px solid #ffffff;  /* 底部边框 */
            }
            QTabBar::tab:hover {
                background-color: #444444;
                color: #f0f0f0;  /* 悬停时稍亮的白色 */
            }
        """)
        
        # 用户列表选项卡
        user_list_tab = QWidget()
        self.setup_user_list_tab(user_list_tab)
        tab_widget.addTab(user_list_tab, "用户列表")
        
        # 添加用户选项卡
        add_user_tab = QWidget()
        self.setup_add_user_tab(add_user_tab)
        tab_widget.addTab(add_user_tab, "添加用户")
        
        # 修改密码选项卡
        change_password_tab = QWidget()
        self.setup_change_password_tab(change_password_tab)
        tab_widget.addTab(change_password_tab, "修改密码")
        
        main_layout.addWidget(tab_widget)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # 刷新按钮
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self.load_users)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
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
            "用户名", "角色", "姓名", "邮箱", "创建时间", "最后登录"
        ])
        self.user_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.user_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.user_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
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
                padding: 8px;
                border: 1px solid #444444;
                font-weight: bold;
                font-size: 13px;
            }
            QHeaderView::section:checked {
                background-color: #2196F3;
            }
        """)
        
        layout.addWidget(self.user_table)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        # 编辑按钮
        self.edit_btn = QPushButton("编辑用户")
        self.edit_btn.clicked.connect(self.edit_user)
        button_layout.addWidget(self.edit_btn)
        
        # 删除按钮
        self.delete_btn = QPushButton("删除用户")
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
        form_group = QGroupBox("添加新用户")
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 用户名
        self.new_username_input = QLineEdit()
        self.new_username_input.setPlaceholderText("请输入用户名")
        form_layout.addRow("用户名:", self.new_username_input)
        
        # 密码
        self.new_password_input = QLineEdit()
        self.new_password_input.setPlaceholderText("请输入密码（至少6位）")
        self.new_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("密码:", self.new_password_input)
        
        # 确认密码
        self.new_confirm_password_input = QLineEdit()
        self.new_confirm_password_input.setPlaceholderText("请确认密码")
        self.new_confirm_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("确认密码:", self.new_confirm_password_input)
        
        # 角色
        self.new_role_combo = QComboBox()
        self.new_role_combo.addItem("普通用户", UserRole.VIEWER)
        self.new_role_combo.addItem("管理员", UserRole.ADMIN)
        form_layout.addRow("角色:", self.new_role_combo)
        
        # 姓名
        self.new_fullname_input = QLineEdit()
        self.new_fullname_input.setPlaceholderText("请输入姓名（可选）")
        form_layout.addRow("姓名:", self.new_fullname_input)
        
        # 邮箱
        self.new_email_input = QLineEdit()
        self.new_email_input.setPlaceholderText("请输入邮箱（可选）")
        form_layout.addRow("邮箱:", self.new_email_input)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # 添加按钮
        add_button_layout = QHBoxLayout()
        add_button_layout.addStretch()
        
        self.add_user_btn = QPushButton("添加用户")
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
        if current_user:
            user_info_label = QLabel(f"当前用户: {current_user.username} ({current_user.role.value})")
            layout.addWidget(user_info_label)
        
        # 表单组
        form_group = QGroupBox("修改密码")
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 选择用户（仅管理员）
        self.password_user_combo = QComboBox()
        self.password_user_combo.addItem("当前用户", "current")
        
        # 如果是管理员，添加所有用户
        if self.user_manager.can_manage_users():
            users = self.user_manager.get_all_users()
            for user in users:
                if user['username'] != current_user.username:
                    display_text = f"{user['username']} ({user['role']})"
                    self.password_user_combo.addItem(display_text, user['username'])
        
        form_layout.addRow("用户:", self.password_user_combo)
        
        # 旧密码（仅修改当前用户密码时需要）
        self.old_password_input = QLineEdit()
        self.old_password_input.setPlaceholderText("请输入旧密码")
        self.old_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("旧密码:", self.old_password_input)
        
        # 新密码
        self.new_password_input2 = QLineEdit()
        self.new_password_input2.setPlaceholderText("请输入新密码（至少6位）")
        self.new_password_input2.setEchoMode(QLineEdit.Password)
        form_layout.addRow("新密码:", self.new_password_input2)
        
        # 确认新密码
        self.new_confirm_password_input2 = QLineEdit()
        self.new_confirm_password_input2.setPlaceholderText("请确认新密码")
        self.new_confirm_password_input2.setEchoMode(QLineEdit.Password)
        form_layout.addRow("确认新密码:", self.new_confirm_password_input2)
        
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # 更新用户选择变化
        self.password_user_combo.currentIndexChanged.connect(self.on_password_user_changed)
        self.on_password_user_changed(0)  # 初始更新
        
        # 修改按钮
        change_button_layout = QHBoxLayout()
        change_button_layout.addStretch()
        
        self.change_password_btn = QPushButton("修改密码")
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
            QMessageBox.warning(self, "权限不足", "您没有用户管理权限")
            return
        
        users = self.user_manager.get_all_users()
        
        self.user_table.setRowCount(len(users))
        
        for row, user in enumerate(users):
            # 用户名
            username_item = QTableWidgetItem(user['username'])
            self.user_table.setItem(row, 0, username_item)
            
            # 角色
            role_display = "管理员" if user['role'] == 'admin' else "普通用户"
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
            QMessageBox.warning(self, "权限不足", "您没有添加用户的权限")
            return
        
        username = self.new_username_input.text().strip()
        password = self.new_password_input.text().strip()
        confirm_password = self.new_confirm_password_input.text().strip()
        role = self.new_role_combo.currentData()
        full_name = self.new_fullname_input.text().strip()
        email = self.new_email_input.text().strip()
        
        # 验证输入
        if not username:
            QMessageBox.warning(self, "输入错误", "请输入用户名")
            self.new_username_input.setFocus()
            return
        
        if not password:
            QMessageBox.warning(self, "输入错误", "请输入密码")
            self.new_password_input.setFocus()
            return
        
        if password != confirm_password:
            QMessageBox.warning(self, "输入错误", "两次输入的密码不一致")
            self.new_confirm_password_input.setFocus()
            return
        
        if len(password) < 6:
            QMessageBox.warning(self, "输入错误", "密码长度至少6位")
            self.new_password_input.setFocus()
            return
        
        # 添加用户
        success, message = self.user_manager.add_user(
            username, password, role, full_name, email
        )
        
        if success:
            QMessageBox.information(self, "成功", message)
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
            QMessageBox.warning(self, "失败", message)
    
    def edit_user(self):
        """编辑用户"""
        if not self.user_manager.can_manage_users():
            QMessageBox.warning(self, "权限不足", "您没有编辑用户的权限")
            return
        
        selected_rows = self.user_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "选择错误", "请选择要编辑的用户")
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
            QMessageBox.warning(self, "权限不足", "您没有删除用户的权限")
            return
        
        selected_rows = self.user_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "选择错误", "请选择要删除的用户")
            return
        
        row = selected_rows[0].row()
        username = self.user_table.item(row, 0).text()
        
        # 确认删除
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除用户 '{username}' 吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.user_manager.delete_user(username)
            
            if success:
                QMessageBox.information(self, "成功", message)
                self.load_users()
                self.users_updated.emit()
            else:
                QMessageBox.warning(self, "失败", message)
    
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
            QMessageBox.warning(self, "输入错误", "请输入新密码")
            self.new_password_input2.setFocus()
            return
        
        if new_password != confirm_password:
            QMessageBox.warning(self, "输入错误", "两次输入的新密码不一致")
            self.new_confirm_password_input2.setFocus()
            return
        
        if len(new_password) < 6:
            QMessageBox.warning(self, "输入错误", "新密码长度至少6位")
            self.new_password_input2.setFocus()
            return
        
        # 修改密码
        success, message = self.user_manager.change_password(
            username, old_password, new_password
        )
        
        if success:
            QMessageBox.information(self, "成功", message)
            # 清空表单
            self.old_password_input.clear()
            self.new_password_input2.clear()
            self.new_confirm_password_input2.clear()
        else:
            QMessageBox.warning(self, "失败", message)


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
        self.setWindowTitle(f"编辑用户 - {self.username}")
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
        form_layout.addRow("用户名:", username_label)
        
        # 角色
        self.role_combo = QComboBox()
        self.role_combo.addItem("普通用户", UserRole.VIEWER)
        self.role_combo.addItem("管理员", UserRole.ADMIN)
        form_layout.addRow("角色:", self.role_combo)
        
        # 姓名
        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText("请输入姓名")
        form_layout.addRow("姓名:", self.fullname_input)
        
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("请输入邮箱")
        form_layout.addRow("邮箱:", self.email_input)
        
        form_group = QGroupBox("用户信息")
        form_group.setLayout(form_layout)
        main_layout.addWidget(form_group)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 保存按钮
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_user)
        button_layout.addWidget(save_btn)
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
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
            QMessageBox.information(self, "成功", message)
            self.accept()
        else:
            QMessageBox.warning(self, "失败", message)
