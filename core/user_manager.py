"""
用户管理模块
提供用户认证、角色管理和权限检查功能
"""
import json
import os
import sys
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from PyQt5.QtCore import QSettings, QObject, pyqtSignal


def _app_data_dir() -> str:
    """程序数据目录（users.json 等），避免自启动时工作目录不一致。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UserRole(Enum):
    """用户角色枚举"""
    ADMIN = "admin"      # 管理员：可以查看数据、设置参数、操作控制
    VIEWER = "viewer"    # 普通用户：只能查看数据


@dataclass
class User:
    """用户数据类"""
    username: str
    password_hash: str  # 存储密码哈希，实际应用中应该使用加盐哈希
    role: UserRole
    full_name: str = ""
    email: str = ""
    created_at: str = ""
    last_login: str = ""


class Permission:
    """权限定义类"""
    
    # 查看权限
    VIEW_OVERVIEW = "view_overview"
    VIEW_SPECTRUM = "view_spectrum"
    VIEW_CLIENTS = "view_clients"
    VIEW_ALARM_LOG = "view_alarm_log"
    VIEW_SETTINGS = "view_settings"
    
    # 操作权限
    START_STOP_ACQUISITION = "start_stop_acquisition"
    CLEAR_DATA = "clear_data"
    SAVE_DATA = "save_data"
    
    # 设置权限
    MODIFY_COMM_SETTINGS = "modify_comm_settings"
    MODIFY_DETECTOR_SETTINGS = "modify_detector_settings"
    MODIFY_CONTROL_SETTINGS = "modify_control_settings"
    MODIFY_DEVICE_CONTROL = "modify_device_control"
    MODIFY_LOG_SETTINGS = "modify_log_settings"
    
    # 用户管理权限
    MANAGE_USERS = "manage_users"
    
    # 角色权限映射
    ROLE_PERMISSIONS = {
        UserRole.ADMIN: [
            VIEW_OVERVIEW, VIEW_SPECTRUM, VIEW_CLIENTS, VIEW_ALARM_LOG, VIEW_SETTINGS,
            START_STOP_ACQUISITION, CLEAR_DATA, SAVE_DATA,
            MODIFY_COMM_SETTINGS, MODIFY_DETECTOR_SETTINGS, MODIFY_CONTROL_SETTINGS,
            MODIFY_DEVICE_CONTROL, MODIFY_LOG_SETTINGS,
            MANAGE_USERS
        ],
        UserRole.VIEWER: [
            VIEW_OVERVIEW, VIEW_SPECTRUM, VIEW_CLIENTS, VIEW_ALARM_LOG, VIEW_SETTINGS
            # 查看器只能查看数据，不能进行任何操作
        ]
    }
    
    @classmethod
    def get_permissions_for_role(cls, role: UserRole) -> List[str]:
        """获取指定角色的权限列表"""
        return cls.ROLE_PERMISSIONS.get(role, [])


class UserManager(QObject):
    """用户管理器"""
    
    # 信号
    user_logged_in = pyqtSignal(str, UserRole)  # 用户名, 角色
    user_logged_out = pyqtSignal()
    user_updated = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Raysen", "Spectrometer")
        self.users_file = os.path.join(_app_data_dir(), "users.json")
        self.current_user: Optional[User] = None
        self.users: Dict[str, User] = {}
        
        # 加载用户数据
        self.load_users()
        
        # 如果没有用户，创建默认管理员
        if not self.users:
            self.create_default_admin()
    
    def load_users(self):
        """从文件加载用户数据"""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for username, user_data in data.items():
                        role = UserRole(user_data['role'])
                        self.users[username] = User(
                            username=username,
                            password_hash=user_data['password_hash'],
                            role=role,
                            full_name=user_data.get('full_name', ''),
                            email=user_data.get('email', ''),
                            created_at=user_data.get('created_at', ''),
                            last_login=user_data.get('last_login', '')
                        )
        except Exception as e:
            print(f"加载用户数据失败: {e}")
            self.users = {}
    
    def save_users(self):
        """保存用户数据到文件"""
        try:
            data = {}
            for username, user in self.users.items():
                user_dict = asdict(user)
                user_dict['role'] = user.role.value
                data[username] = user_dict
            
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存用户数据失败: {e}")
    
    def create_default_admin(self):
        """创建默认管理员账户"""
        default_admin = User(
            username="admin",
            password_hash=self._hash_password("admin123"),  # 默认密码
            role=UserRole.ADMIN,
            full_name="系统管理员",
            email="admin@example.com",
            created_at="2025-01-01",
            last_login=""
        )
        self.users["admin"] = default_admin
        self.save_users()
    
    def _hash_password(self, password: str) -> str:
        """密码哈希函数（简化版，实际应用中应使用加盐哈希）"""
        # 这里使用简单的哈希，实际应用中应该使用bcrypt或类似的安全哈希
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

    def ensure_viewer_user(self) -> str:
        """确保存在可用于免密自动登录的 viewer 账户，返回用户名。"""
        for username, user in self.users.items():
            if user.role == UserRole.VIEWER:
                return username

        from datetime import datetime
        username = "user"
        if username in self.users:
            username = "viewer"

        self.users[username] = User(
            username=username,
            password_hash=self._hash_password(""),
            role=UserRole.VIEWER,
            full_name="普通用户",
            email="",
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_login=""
        )
        self.save_users()
        return username

    def authenticate_viewer_auto(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """Kiosk 模式：用 viewer 空密码自动登录，不弹登录框。"""
        viewer_username = self.ensure_viewer_user()
        success, message = self.authenticate(viewer_username, "")
        if success:
            return True, viewer_username, message

        # 兜底：直接设为当前 viewer（例如 users.json 只读导致 authenticate 写回失败）
        user = self.users.get(viewer_username)
        if user and user.role == UserRole.VIEWER:
            self.current_user = user
            self.user_logged_in.emit(viewer_username, user.role)
            return True, viewer_username, "viewer 自动登录（兜底）"
        return False, None, message
    
    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[str]]:
        """用户认证"""
        if username not in self.users:
            return False, "用户不存在"
        
        user = self.users[username]
        password_hash = self._hash_password(password)
        
        if user.password_hash != password_hash:
            return False, "密码错误"
        
        # 更新最后登录时间
        from datetime import datetime
        user.last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_users()
        
        # 设置当前用户
        self.current_user = user
        
        # 发出登录信号
        self.user_logged_in.emit(username, user.role)
        
        return True, "登录成功"
    
    def logout(self):
        """用户登出"""
        self.current_user = None
        self.user_logged_out.emit()
    
    def get_current_user(self) -> Optional[User]:
        """获取当前用户"""
        return self.current_user
    
    def get_current_role(self) -> Optional[UserRole]:
        """获取当前用户角色"""
        if self.current_user:
            return self.current_user.role
        return None
    
    def has_permission(self, permission: str) -> bool:
        """检查当前用户是否有指定权限"""
        if not self.current_user:
            return False
        
        role_permissions = Permission.get_permissions_for_role(self.current_user.role)
        return permission in role_permissions
    
    def can_view_page(self, page_name: str) -> bool:
        """检查当前用户是否可以查看指定页面"""
        page_permission_map = {
            "overview": Permission.VIEW_OVERVIEW,
            "spectrum": Permission.VIEW_SPECTRUM,
            "clients": Permission.VIEW_CLIENTS,
            "alarm_log": Permission.VIEW_ALARM_LOG,
            "settings": Permission.VIEW_SETTINGS
        }
        
        if page_name not in page_permission_map:
            return True  # 默认允许访问未知页面
        
        return self.has_permission(page_permission_map[page_name])
    
    def can_modify_settings(self) -> bool:
        """检查当前用户是否可以修改设置"""
        return self.has_permission(Permission.MODIFY_COMM_SETTINGS) or \
               self.has_permission(Permission.MODIFY_DETECTOR_SETTINGS) or \
               self.has_permission(Permission.MODIFY_CONTROL_SETTINGS) or \
               self.has_permission(Permission.MODIFY_DEVICE_CONTROL) or \
               self.has_permission(Permission.MODIFY_LOG_SETTINGS)
    
    def can_manage_users(self) -> bool:
        """检查当前用户是否可以管理用户"""
        return self.has_permission(Permission.MANAGE_USERS)
    
    def add_user(self, username: str, password: str, role: UserRole, 
                 full_name: str = "", email: str = "") -> Tuple[bool, str]:
        """添加新用户"""
        if not self.can_manage_users():
            return False, "没有用户管理权限"
        
        if username in self.users:
            return False, "用户名已存在"
        
        if len(password) < 6:
            return False, "密码长度至少6位"
        
        from datetime import datetime
        new_user = User(
            username=username,
            password_hash=self._hash_password(password),
            role=role,
            full_name=full_name,
            email=email,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_login=""
        )
        
        self.users[username] = new_user
        self.save_users()
        self.user_updated.emit()
        
        return True, "用户添加成功"
    
    def update_user(self, username: str, **kwargs) -> Tuple[bool, str]:
        """更新用户信息"""
        if not self.can_manage_users():
            return False, "没有用户管理权限"
        
        if username not in self.users:
            return False, "用户不存在"
        
        user = self.users[username]
        
        # 更新允许的字段
        if 'full_name' in kwargs:
            user.full_name = kwargs['full_name']
        if 'email' in kwargs:
            user.email = kwargs['email']
        if 'role' in kwargs:
            user.role = kwargs['role']
        
        self.save_users()
        self.user_updated.emit()
        
        return True, "用户更新成功"
    
    def delete_user(self, username: str) -> Tuple[bool, str]:
        """删除用户"""
        if not self.can_manage_users():
            return False, "没有用户管理权限"
        
        if username not in self.users:
            return False, "用户不存在"
        
        if username == self.current_user.username:
            return False, "不能删除当前登录用户"
        
        del self.users[username]
        self.save_users()
        self.user_updated.emit()
        
        return True, "用户删除成功"
    
    def change_password(self, username: str, old_password: str, 
                       new_password: str) -> Tuple[bool, str]:
        """修改密码"""
        # 用户只能修改自己的密码，管理员可以修改任何用户的密码
        if username != self.current_user.username and not self.can_manage_users():
            return False, "No permission to modify other users' passwords"
        
        if username not in self.users:
            return False, "用户不存在"
        
        user = self.users[username]
        
        # 验证旧密码（如果是用户自己修改）
        if username == self.current_user.username:
            old_password_hash = self._hash_password(old_password)
            if user.password_hash != old_password_hash:
                return False, "旧密码错误"
        
        if len(new_password) < 6:
            return False, "新密码长度至少6位"
        
        user.password_hash = self._hash_password(new_password)
        self.save_users()
        
        return True, "密码修改成功"
    
    def get_user(self, username: str) -> Optional[Dict]:
        """获取指定用户信息（不包含密码哈希）"""
        if not self.can_manage_users():
            return None
        
        if username not in self.users:
            return None
        
        user = self.users[username]
        return {
            'username': user.username,
            'role': user.role.value,
            'full_name': user.full_name,
            'email': user.email,
            'created_at': user.created_at,
            'last_login': user.last_login
        }
    
    def get_all_users(self) -> List[Dict]:
        """获取所有用户信息（不包含密码哈希）"""
        if not self.can_manage_users():
            return []
        
        users_list = []
        for username, user in self.users.items():
            user_dict = {
                'username': user.username,
                'role': user.role.value,
                'full_name': user.full_name,
                'email': user.email,
                'created_at': user.created_at,
                'last_login': user.last_login
            }
            users_list.append(user_dict)
        
        return users_list


# 全局用户管理器实例
_user_manager_instance = None

def get_user_manager() -> UserManager:
    """获取用户管理器单例实例"""
    global _user_manager_instance
    if _user_manager_instance is None:
        _user_manager_instance = UserManager()
    return _user_manager_instance
