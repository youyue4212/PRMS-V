# -*- coding: utf-8 -*-
"""
Timeout Manager
Manages admin mode timeout and auto-logout functionality
Reference: Gamma Data Acquisition Dashboard (Python + Tkinter implementation)
"""
import time
import pickle
import threading
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWidgets import QMessageBox

from core.user_manager import UserRole, get_user_manager


class TimeoutManager(QObject):
    """Timeout management: async timing, reset, stop, trigger auto-logout"""
    
    # Signal: emitted when timeout occurs
    timeout_occurred = pyqtSignal()
    
    # Signal: emitted when timer updates (for UI updates)
    timer_updated = pyqtSignal(int)  # remaining seconds
    
    def __init__(self):
        super().__init__()
        self.user_manager = get_user_manager()
        self.timeout_seconds = 180  # default 3 minutes
        self.timer = None
        self.remaining_seconds = self.timeout_seconds
        self.state_file = "admin_mode_state.pkl"
        
        # Load saved state
        self.load_state()
        
        # Create QTimer for UI updates
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui_timer)
        self.ui_timer.start(1000)  # update every second
        
        # If loaded state is admin mode and not timed out, start timer
        if self.is_admin_mode_active() and not self.is_timed_out():
            self.start_timer()
    
    def is_admin_mode_active(self):
        """Check if currently in admin mode"""
        current_user = self.user_manager.get_current_user()
        return current_user and current_user.role == UserRole.ADMIN
    
    def is_timed_out(self):
        """Check if admin mode has timed out"""
        if not hasattr(self, 'last_operate_time') or self.last_operate_time == 0:
            return True
        
        elapsed = time.time() - self.last_operate_time
        return elapsed > self.timeout_seconds
    
    def start_timer(self):
        """Start timeout timer"""
        self.stop_timer()
        self.remaining_seconds = self.timeout_seconds
        self.last_operate_time = time.time()
        self.save_state()
        
        # Start background thread timer
        self.timer = threading.Timer(self.timeout_seconds, self._timeout_callback)
        self.timer.daemon = True
        self.timer.start()
        
        print(f"Admin mode timer started, will auto-logout after {self.timeout_seconds} seconds of inactivity")
    
    def reset_timer(self):
        """Reset timer (triggered by user operations)"""
        if self.is_admin_mode_active():
            self.start_timer()
    
    def stop_timer(self):
        """Stop timer"""
        if self.timer and self.timer.is_alive():
            self.timer.cancel()
            self.timer = None
    
    def update_operate_time(self):
        """Update last operation time (triggered by all operations)"""
        if self.is_admin_mode_active():
            self.last_operate_time = time.time()
            self.save_state()
            self.reset_timer()
    
    def _timeout_callback(self):
        """Timeout callback: emit timeout signal and switch to normal mode"""
        if self.is_admin_mode_active() and self.is_timed_out():
            # Switch to normal mode
            self.switch_to_normal_mode()
            self.timeout_occurred.emit()
        self.stop_timer()
    
    def update_ui_timer(self):
        """Update UI timer display"""
        if self.is_admin_mode_active() and hasattr(self, 'last_operate_time'):
            elapsed = time.time() - self.last_operate_time
            self.remaining_seconds = max(0, self.timeout_seconds - int(elapsed))
            self.timer_updated.emit(self.remaining_seconds)
            
            # If timed out, trigger timeout signal and switch to normal mode
            if self.remaining_seconds == 0 and self.is_admin_mode_active():
                self.switch_to_normal_mode()
                self.timeout_occurred.emit()
                self.stop_timer()
    
    def get_remaining_time_str(self):
        """Get remaining time string (MM:SS format)"""
        if not self.is_admin_mode_active():
            return ""
        
        minutes = self.remaining_seconds // 60
        seconds = self.remaining_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def save_state(self):
        """Persist state to local file"""
        state = {
            "last_operate_time": self.last_operate_time if hasattr(self, 'last_operate_time') else 0,
            "timeout_seconds": self.timeout_seconds,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            with open(self.state_file, "wb") as f:
                pickle.dump(state, f)
        except Exception as e:
            print(f"State save failed: {e}")
    
    def load_state(self):
        """Load state from local file, check timeout"""
        try:
            with open(self.state_file, "rb") as f:
                state = pickle.load(f)
            
            self.last_operate_time = state.get("last_operate_time", 0)
            self.timeout_seconds = state.get("timeout_seconds", 180)
            
            # Check if timed out
            if self.is_timed_out():
                self.last_operate_time = 0
                print("Loaded state has timed out, reset to normal mode")
        
        except FileNotFoundError:
            # Cache file doesn't exist, use default state
            self.last_operate_time = 0
            self.timeout_seconds = 180
            print("State file doesn't exist, using default config")
        
        except Exception as e:
            print(f"State load failed, using default config: {e}")
            self.last_operate_time = 0
            self.timeout_seconds = 180
    
    def set_timeout_seconds(self, seconds):
        """Set timeout seconds"""
        self.timeout_seconds = seconds
        self.save_state()
        if self.is_admin_mode_active():
            self.reset_timer()
    
    def switch_to_normal_mode(self):
        """Switch current admin user to normal mode"""
        if self.is_admin_mode_active():
            # Get current user and change role to VIEWER
            current_user = self.user_manager.get_current_user()
            if current_user:
                # Create a temporary viewer user with same username
                # This is a simplified approach - in real system you might want
                # to keep the user as admin but just restrict permissions
                print(f"Switching user {current_user.username} from admin to normal mode")
                
                # Log the switch
                print("Admin mode timeout: User switched to normal view mode")
                
                # Note: In a real implementation, you would:
                # 1. Change user role in user manager
                # 2. Update UI through signals
                # 3. Save the state
                
                # For now, we'll just log it and let the UI handle the switch
                # through the timeout_occurred signal


# Global timeout manager instance
_timeout_manager_instance = None

def get_timeout_manager() -> TimeoutManager:
    """Get timeout manager singleton instance"""
    global _timeout_manager_instance
    if _timeout_manager_instance is None:
        _timeout_manager_instance = TimeoutManager()
    return _timeout_manager_instance
