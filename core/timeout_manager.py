# -*- coding: utf-8 -*-
"""
Timeout Manager
Manages admin mode timeout and auto-logout functionality
Reference: Gamma Data Acquisition Dashboard (Python + Tkinter implementation)
"""
import time
import pickle
from datetime import datetime
from pathlib import Path
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from core.user_manager import UserRole, get_user_manager


class TimeoutManager(QObject):
    """Timeout management: Qt timer only (avoid dual-channel double logout)."""

    timeout_occurred = pyqtSignal()
    timer_updated = pyqtSignal(int)  # remaining seconds

    def __init__(self):
        super().__init__()
        self.user_manager = get_user_manager()
        self.timeout_seconds = 180  # default 3 minutes
        self.remaining_seconds = self.timeout_seconds
        self._timeout_emitted = False
        self.state_file = str(self._default_state_path())

        self.last_operate_time = 0
        self._last_state_save_at = 0.0
        # 触摸频繁时节流写盘，减轻 SD 卡磨损与卡顿
        self._state_save_min_interval_s = 30.0
        self.load_state()

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui_timer)
        self.ui_timer.start(1000)

        if self.is_admin_mode_active() and not self.is_timed_out():
            self.start_timer()

    def _default_state_path(self) -> Path:
        # 与用户配置同目录，避免 CWD 变化导致状态丢失/错乱
        try:
            base = Path.home() / "Raysen"
            base.mkdir(parents=True, exist_ok=True)
            return base / "admin_mode_state.pkl"
        except Exception:
            return Path("admin_mode_state.pkl")

    def is_admin_mode_active(self):
        current_user = self.user_manager.get_current_user()
        return current_user and current_user.role in (UserRole.ADMIN, UserRole.MAINTAINER)

    def is_timed_out(self):
        if not hasattr(self, 'last_operate_time') or self.last_operate_time == 0:
            return True
        elapsed = time.time() - self.last_operate_time
        return elapsed > self.timeout_seconds

    def start_timer(self):
        self.stop_timer()
        self._timeout_emitted = False
        self.remaining_seconds = self.timeout_seconds
        self.last_operate_time = time.time()
        self.save_state()
        print(f"Admin mode timer started, will auto-logout after {self.timeout_seconds} seconds of inactivity")

    def reset_timer(self):
        if self.is_admin_mode_active():
            self.start_timer()

    def stop_timer(self):
        # 仅清状态；UI QTimer 常驻，靠 remaining/admin 判断是否计时
        self._timeout_emitted = False

    def update_operate_time(self):
        if self.is_admin_mode_active():
            self.last_operate_time = time.time()
            self._timeout_emitted = False
            self.save_state(force=False)
            self.remaining_seconds = self.timeout_seconds

    def _emit_timeout_once(self):
        if self._timeout_emitted:
            return
        self._timeout_emitted = True
        self.switch_to_normal_mode()
        self.timeout_occurred.emit()

    def update_ui_timer(self):
        if self.is_admin_mode_active() and hasattr(self, 'last_operate_time') and self.last_operate_time:
            elapsed = time.time() - self.last_operate_time
            self.remaining_seconds = max(0, self.timeout_seconds - int(elapsed))
            self.timer_updated.emit(self.remaining_seconds)
            if self.remaining_seconds == 0 and self.is_admin_mode_active():
                self._emit_timeout_once()
        else:
            self.remaining_seconds = 0

    def get_remaining_time_str(self):
        if not self.is_admin_mode_active():
            return ""
        minutes = self.remaining_seconds // 60
        seconds = self.remaining_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def save_state(self, force: bool = True):
        now = time.time()
        if not force and (now - getattr(self, "_last_state_save_at", 0.0)) < self._state_save_min_interval_s:
            return
        state = {
            "last_operate_time": self.last_operate_time if hasattr(self, 'last_operate_time') else 0,
            "timeout_seconds": self.timeout_seconds,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(self.state_file, "wb") as f:
                pickle.dump(state, f)
            self._last_state_save_at = now
        except Exception as e:
            print(f"State save failed: {e}")

    def load_state(self):
        try:
            with open(self.state_file, "rb") as f:
                state = pickle.load(f)
            self.last_operate_time = state.get("last_operate_time", 0)
            self.timeout_seconds = state.get("timeout_seconds", 180)
            if self.is_timed_out():
                self.last_operate_time = 0
                print("Loaded state has timed out, reset to normal mode")
        except FileNotFoundError:
            self.last_operate_time = 0
            self.timeout_seconds = 180
            print("State file doesn't exist, using default config")
        except Exception as e:
            print(f"State load failed, using default config: {e}")
            self.last_operate_time = 0
            self.timeout_seconds = 180

    def set_timeout_seconds(self, seconds):
        self.timeout_seconds = seconds
        self.save_state()
        if self.is_admin_mode_active():
            self.reset_timer()

    def switch_to_normal_mode(self):
        if self.is_admin_mode_active():
            current_user = self.user_manager.get_current_user()
            if current_user:
                print(f"Switching user {current_user.username} from admin to normal mode")
            print("Admin mode timeout: User switched to normal view mode")


_timeout_manager_instance = None

def get_timeout_manager() -> TimeoutManager:
    global _timeout_manager_instance
    if _timeout_manager_instance is None:
        _timeout_manager_instance = TimeoutManager()
    return _timeout_manager_instance
