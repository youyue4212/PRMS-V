import sys
import os
import glob
import time
from datetime import datetime, timedelta
import serial
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFileDialog, QCheckBox,QLineEdit,
                             QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QTextEdit, QFormLayout, QGridLayout,QSizePolicy,QStyle,
                             QTabWidget, QDockWidget, QAction, QToolBar, QStatusBar, QMessageBox, QScrollArea)
from PyQt5.QtCore import QThread, QTimer, QMutex, pyqtSignal, Qt, QObject, QEvent, QMetaObject, Q_ARG
from PyQt5.QtGui import QFont, QIcon
from dataclasses import dataclass
from typing import Optional
import struct
import subprocess
import pandas as pd
import numpy as np
import pyqtgraph as pg
pg.setConfigOptions(antialias=False, useOpenGL=False)


from core.config import (
    ConfigManager,
    DEFAULT_TCP_PORT_MASTER,
    DEFAULT_TCP_PORT_PROBE,
)
from core import algorithm as alg

from core.detector import CmdFeedback, SpectrumPacket, search_serial_devices, SerialPacketWorker, DevMessage
from core.tcp_detector import TcpPacketWorker, ClientInfo
from core.tcp_multi_port import MultiPortTcpPacketWorker, is_tcp_worker
from core.raw_logger import RawLogger
from core import logger 
from core.alarm_logger import get_alarm_logger  # 导入报警记录器
from core.diagnostics import DiagnosticsManager  # 导入诊断管理器
from core.autosave_worker import AutoSaveWorker
from core.translation import _t  # 导入翻译函数

log_inst=logger.get_logger()


FILTER_ENABLED =  True
FILTER_WIN_SIZE = 4
FILTER_NUM_SIGMA = 2

MAX_SPECTRUM_STORED = 100
# 计数率图最多保留的历史（覆盖可选最大窗口 15 分钟）
CPS_HISTORY_KEEP_SEC = 15 * 60
CPS_WINDOW_CHOICES = (1, 5, 15)





class FocusEventFilter(QObject):
    """监听输入框焦点事件，手动触发虚拟键盘"""
    def __init__(self):
        super().__init__()
        self.last_trigger_time = 0
        self.platform = sys.platform
        self.keyboard_process = None  # 跟踪键盘进程
        # 电脑默认关；工控触摸屏 / USE_SOFTWARE_KEYBOARD=1 自动开
        try:
            from core.software_keyboard import should_use_software_keyboard
            self.keyboard_enabled = bool(should_use_software_keyboard())
        except Exception:
            self.keyboard_enabled = False
        self.current_focused_obj = None  # 当前获得焦点的输入控件
        self.debug_keyboard = str(os.environ.get('KEYBOARD_DEBUG', '')).strip() == '1'
        # 环境变量强制开时关掉系统 OSK，避免冲突
        if self.keyboard_enabled or str(os.environ.get('USE_SOFTWARE_KEYBOARD', '')).strip() == '1':
            self.keyboard_enabled = True
            try:
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.a11y.applications', 'screen-keyboard-enabled', 'false'],
                               stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    def _resolve_keyboard_target(self, obj):
        """若聚焦在 SpinBox 内部 lineEdit，绑定到父 SpinBox。"""
        target_obj = obj
        if isinstance(obj, QLineEdit):
            parent = obj.parent()
            while parent is not None:
                if isinstance(parent, (QSpinBox, QDoubleSpinBox)):
                    return parent
                parent = parent.parent()
        return target_obj

    def _show_internal_software_keyboard(self, obj):
        """弹出内置工业软键盘；关后短时抑制，避免回焦再弹。"""
        current_time = time.time()
        if current_time - self.last_trigger_time < 0.35:
            return False
        try:
            from core.software_keyboard import get_keyboard_manager
            km = get_keyboard_manager()
            # 与改样式前一致：关后约 0.5s 抑制回弹；不再 clearFocus
            if current_time - getattr(km, "last_closed_time", 0) < 0.5:
                return False
            target_obj = self._resolve_keyboard_target(obj)
            if km.is_visible() and getattr(km, "current_input", None) is target_obj:
                return False
            self.last_trigger_time = current_time
            self.current_focused_obj = target_obj
            log_inst.debug("Showing internal software keyboard")
            # 传入所属窗口：登录模态时键盘会挂到登录框前，避免被挡在后面
            km.show_keyboard_for_input(target_obj, obj.window())
            return True
        except Exception as e:
            log_inst.error(f"Failed to show internal software keyboard: {e}")
            return False

    def eventFilter(self, obj, event):
        if self.debug_keyboard and event.type() == QEvent.FocusIn:
            log_inst.info(f"DEBUG: FocusIn event detected on {type(obj).__name__}")
        
        use_software_keyboard = os.environ.get('USE_SOFTWARE_KEYBOARD')
        if self.debug_keyboard:
            log_inst.info(f"DEBUG eventFilter: USE_SOFTWARE_KEYBOARD={use_software_keyboard}, repr={repr(use_software_keyboard)}")
        use_software_keyboard_str = str(use_software_keyboard).strip() if use_software_keyboard else ''
        # 环境变量或设置页开关：统一走内置软键盘（工业做法，避免系统 OSK 关两次）
        prefer_internal = use_software_keyboard_str == '1' or self.keyboard_enabled
        # 仅当显式要求系统键盘时才回退（调试/兼容）
        use_system_keyboard = str(os.environ.get('USE_SYSTEM_KEYBOARD', '')).strip() == '1'

        if prefer_internal and not use_system_keyboard:
            is_input = isinstance(obj, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit))
            if is_input and (use_software_keyboard_str == '1' or self.keyboard_enabled):
                if event.type() == QEvent.FocusIn:
                    self._show_internal_software_keyboard(obj)
                elif event.type() == QEvent.MouseButtonPress:
                    # 输入框已聚焦时再次点击不会有 FocusIn，需用点击补一次弹出
                    try:
                        focused = obj.hasFocus()
                        if not focused and hasattr(obj, "lineEdit") and obj.lineEdit() is not None:
                            focused = obj.lineEdit().hasFocus()
                    except RuntimeError:
                        focused = False
                    if focused:
                        self._show_internal_software_keyboard(obj)
            return super().eventFilter(obj, event)
        
        if not self.keyboard_enabled:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.FocusIn:
            if isinstance(obj, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit)):
                self.current_focused_obj = obj
                current_time = time.time()
                if current_time - self.last_trigger_time < 1.0:
                    return super().eventFilter(obj, event)
                # 系统键盘路径也做关后抑制（若能感知关闭则更好；此处至少防抖）
                if current_time - getattr(self, "last_system_kb_close_hint", 0) < 1.2:
                    return super().eventFilter(obj, event)
                self.last_trigger_time = current_time

                try:
                    log_inst.info("Input focus detected, attempting to show virtual keyboard...")
                    if self.platform == "win32":
                        self.show_windows_keyboard()
                    elif self.platform == "linux" or self.platform == "linux2":
                        self.show_linux_keyboard()
                    else:
                        log_inst.warning(f"Unsupported platform: {self.platform}")
                except Exception as e:
                    log_inst.error(f"Error triggering keyboard: {e}")
        return super().eventFilter(obj, event)
    
    def show_windows_keyboard(self):
        """显示 Windows 屏幕键盘"""
        try:
            # 方法1：使用 osk.exe（传统屏幕键盘）
            subprocess.Popen(['osk.exe'], 
                            stderr=subprocess.DEVNULL, 
                            stdout=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            log_inst.info("Windows screen keyboard (osk.exe) launched")
        except Exception as e:
            log_inst.error(f"Failed to launch osk.exe: {e}")
            try:
                # 方法2：使用 tabtip.exe（触摸键盘）
                subprocess.Popen(['C:\\Windows\\System32\\TabTip.exe'],
                                stderr=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
                log_inst.info("Windows touch keyboard (TabTip.exe) launched")
            except Exception as e2:
                log_inst.error(f"Failed to launch TabTip.exe: {e2}")
    
    def show_linux_keyboard(self):
        """显示 Linux 虚拟键盘（GNOME OSK）"""
        # 调试：打印环境变量
        use_software_keyboard = os.environ.get('USE_SOFTWARE_KEYBOARD')
        log_inst.info(f"DEBUG: USE_SOFTWARE_KEYBOARD environment variable value: {use_software_keyboard}, repr: {repr(use_software_keyboard)}")
        
        # 检查是否使用软件键盘方案
        if str(use_software_keyboard) == '1':
            log_inst.info("USE_SOFTWARE_KEYBOARD is set, skipping external keyboard launch")
            # 延迟恢复焦点，确保输入框可以接收输入
            if self.current_focused_obj is not None:
                from PyQt5.QtCore import QTimer
                obj = self.current_focused_obj
                QTimer.singleShot(300, lambda: self.restore_focus_for_obj(obj))
            return
        
        try:
            log_inst.info("Attempting to show GNOME OSK...")
            
            # 方法1: 使用 dbus-send 命令（标准方法）
            log_inst.info("Method 1: Using dbus-send command...")
            try:
                result = subprocess.run(['dbus-send', '--dest=org.gnome.Shell', '/org/gnome/Shell', 
                                       'org.gnome.Shell.ShowOSK'],
                                      stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5, text=True)
                if result.returncode == 0:
                    log_inst.info("dbus-send command executed successfully")
                    if result.stderr:
                        log_inst.info(f"dbus-send stderr: {result.stderr.strip()}")
                else:
                    log_inst.warning(f"dbus-send failed with return code {result.returncode}")
                    if result.stderr:
                        log_inst.warning(f"dbus-send stderr: {result.stderr.strip()}")
            except Exception as e:
                log_inst.error(f"dbus-send command failed: {e}")
            
            # 方法2: 确保屏幕键盘功能已启用
            log_inst.info("Method 2: Ensuring screen keyboard is enabled...")
            try:
                # 检查当前设置
                check_result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.a11y.applications', 'screen-keyboard-enabled'],
                                             stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=2, text=True)
                if check_result.returncode == 0:
                    current_setting = check_result.stdout.strip()
                    log_inst.info(f"Current screen keyboard setting: {current_setting}")
                    
                    # 如果未启用，则启用它
                    if 'true' not in current_setting.lower():
                        log_inst.info("Screen keyboard is disabled, enabling it...")
                        enable_result = subprocess.run(['gsettings', 'set', 'org.gnome.desktop.a11y.applications', 'screen-keyboard-enabled', 'true'],
                                                      stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=2, text=True)
                        if enable_result.returncode == 0:
                            log_inst.info("Screen keyboard enabled successfully")
                        else:
                            log_inst.warning(f"Failed to enable screen keyboard: {enable_result.stderr}")
                    else:
                        log_inst.info("Screen keyboard is already enabled")
                else:
                    log_inst.warning(f"Failed to check screen keyboard setting: {check_result.stderr}")
            except Exception as e:
                log_inst.error(f"gsettings command failed: {e}")
            
            # 方法3: 使用 gdbus 命令（另一种 DBus 调用方式）
            log_inst.info("Method 3: Trying gdbus command...")
            try:
                gdbus_result = subprocess.run([
                    'gdbus', 'call', '--session', 
                    '--dest', 'org.gnome.Shell',
                    '--object-path', '/org/gnome/Shell',
                    '--method', 'org.gnome.Shell.ShowOSK'
                ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=5, text=True)
                if gdbus_result.returncode == 0:
                    log_inst.info(f"gdbus command executed successfully: {gdbus_result.stdout.strip()}")
                else:
                    log_inst.warning(f"gdbus failed: {gdbus_result.stderr.strip()}")
            except Exception as e:
                log_inst.error(f"gdbus command failed: {e}")
            
            # 方法4: 检查 GNOME Shell 扩展状态
            log_inst.info("Method 4: Checking GNOME Shell extensions...")
            try:
                ext_result = subprocess.run([
                    'gsettings', 'get', 'org.gnome.shell', 'enabled-extensions'
                ], stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=2, text=True)
                if ext_result.returncode == 0:
                    extensions = ext_result.stdout.strip()
                    log_inst.info(f"Enabled GNOME Shell extensions: {extensions}")
                else:
                    log_inst.warning(f"Failed to get extensions: {ext_result.stderr}")
            except Exception as e:
                log_inst.error(f"Failed to check extensions: {e}")
            
            # 等待一会儿，观察键盘是否弹出
            log_inst.info("Waiting 1 second to see if keyboard appears...")
            time.sleep(1)
            
            # 如果以上方法都失败，尝试备选键盘
            log_inst.info("All GNOME OSK methods attempted, trying alternative keyboards...")
            self.try_alternative_keyboards()
                
        except Exception as e:
            log_inst.error(f"Error in show_linux_keyboard: {e}")
            # 即使出错也尝试备选键盘
            self.try_alternative_keyboards()
        finally:
            # 延迟恢复焦点，确保键盘启动后输入框可以接收输入
            # 减少延迟时间，避免焦点丢失
            if self.current_focused_obj is not None:
                from PyQt5.QtCore import QTimer
                # 保存当前焦点对象的引用，避免在延迟期间被修改
                obj = self.current_focused_obj
                QTimer.singleShot(300, lambda: self.restore_focus_for_obj(obj))
    
    def try_alternative_keyboards(self):
        """尝试启动备选虚拟键盘，优先使用带数字键的键盘"""
        try:
            # 首先检查环境变量指定的优先键盘
            preferred_keyboard = os.environ.get('PREFERRED_KEYBOARD', '').lower()
            
            # 如果指定了优先键盘，优先尝试
            if preferred_keyboard:
                log_inst.info(f"Preferred keyboard specified: {preferred_keyboard}")
                
                if preferred_keyboard == 'wvkbd-mobintl' or preferred_keyboard == 'wvkbd':
                    # 检查 wvkbd-mobintl 是否可用
                    wvkbd_available = False
                    try:
                        # 尝试 wvkbd-mobintl
                        result = subprocess.run(['which', 'wvkbd-mobintl'], capture_output=True, text=True, timeout=1)
                        if result.returncode != 0:
                            # 如果 wvkbd-mobintl 不可用，尝试 wvkbd
                            result = subprocess.run(['which', 'wvkbd'], capture_output=True, text=True, timeout=1)
                        wvkbd_available = result.returncode == 0
                    except:
                        pass
                    
                    if wvkbd_available:
                        log_inst.info("wvkbd-mobintl/wvkbd detected, launching...")
                        time.sleep(0.1)
                        try:
                            # 尝试启动 wvkbd-mobintl
                            subprocess.Popen(['wvkbd-mobintl'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                            log_inst.info("wvkbd-mobintl launched")
                        except Exception as e:
                            log_inst.warning(f"Failed to launch wvkbd-mobintl: {e}, trying wvkbd...")
                            # 如果失败，尝试 wvkbd
                            subprocess.Popen(['wvkbd'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        return
                
                elif preferred_keyboard == 'matchbox-keyboard':
                    # 检查 matchbox-keyboard 是否可用
                    matchbox_available = False
                    try:
                        result = subprocess.run(['which', 'matchbox-keyboard'], capture_output=True, text=True, timeout=1)
                        matchbox_available = result.returncode == 0
                    except:
                        pass
                    
                    if matchbox_available:
                        log_inst.info("Matchbox-keyboard detected (preferred), launching...")
                        time.sleep(0.1)
                        subprocess.Popen(['matchbox-keyboard'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        return
                
                elif preferred_keyboard == 'florence':
                    # 检查 florence 是否可用
                    florence_available = False
                    try:
                        result = subprocess.run(['which', 'florence'], capture_output=True, text=True, timeout=1)
                        florence_available = result.returncode == 0
                    except:
                        pass
                    
                    if florence_available:
                        log_inst.info("Florence keyboard detected (preferred), launching...")
                        time.sleep(0.1)
                        subprocess.Popen(['florence'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        return
                
                elif preferred_keyboard == 'onboard':
                    # 检查 onboard 是否可用
                    onboard_available = False
                    try:
                        result = subprocess.run(['which', 'onboard'], capture_output=True, text=True, timeout=1)
                        onboard_available = result.returncode == 0
                    except:
                        pass
                    
                    if onboard_available:
                        log_inst.info("Onboard keyboard detected (preferred), launching with numeric keypad...")
                        time.sleep(0.1)
                        # 尝试启动onboard并加载数字键盘布局
                        try:
                            cmd = ['onboard', '--layout', 'Numpad', '--theme', 'Droid']
                            subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                            log_inst.info("Onboard launched with Numpad layout")
                        except Exception as e:
                            log_inst.warning(f"Failed to launch onboard with Numpad layout: {e}, trying default layout...")
                            subprocess.Popen(['onboard'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        return
            
            # 如果没有指定优先键盘或优先键盘不可用，按默认顺序尝试
            
            # 检查 wvkbd-mobintl 是否可用（新增支持）
            wvkbd_available = False
            try:
                # 尝试 wvkbd-mobintl
                result = subprocess.run(['which', 'wvkbd-mobintl'], capture_output=True, text=True, timeout=1)
                if result.returncode != 0:
                    # 如果 wvkbd-mobintl 不可用，尝试 wvkbd
                    result = subprocess.run(['which', 'wvkbd'], capture_output=True, text=True, timeout=1)
                wvkbd_available = result.returncode == 0
            except:
                pass
            
            if wvkbd_available:
                log_inst.info("wvkbd-mobintl/wvkbd detected, launching...")
                time.sleep(0.1)
                try:
                    # 尝试启动 wvkbd-mobintl
                    subprocess.Popen(['wvkbd-mobintl'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                    log_inst.info("wvkbd-mobintl launched")
                except Exception as e:
                    log_inst.warning(f"Failed to launch wvkbd-mobintl: {e}, trying wvkbd...")
                    # 如果失败，尝试 wvkbd
                    subprocess.Popen(['wvkbd'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                return
            
            # 检查 onboard 是否可用（支持数字键盘）
            onboard_available = False
            try:
                result = subprocess.run(['which', 'onboard'], capture_output=True, text=True, timeout=1)
                onboard_available = result.returncode == 0
            except:
                pass
            
            if onboard_available:
                log_inst.info("Onboard keyboard detected, launching with numeric keypad...")
                time.sleep(0.1)
                
                # 尝试获取当前窗口ID
                window_id = None
                if self.current_focused_obj is not None:
                    try:
                        widget = self.current_focused_obj
                        while widget and not hasattr(widget, 'windowId'):
                            widget = widget.parent()
                        if widget and hasattr(widget, 'windowId'):
                            win_id = widget.windowId()
                            if win_id and win_id != 0:
                                window_id = win_id
                                log_inst.info(f"Got window ID: {window_id}")
                    except Exception as e:
                        log_inst.warning(f"Failed to get window ID: {e}")
                
                # 尝试启动onboard并加载数字键盘布局
                try:
                    cmd = ['onboard', '--layout', 'Numpad', '--theme', 'Droid']
                    if window_id is not None:
                        cmd.extend(['--window-id', str(window_id)])
                    subprocess.Popen(cmd, 
                                    stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                    log_inst.info("Onboard launched with Numpad layout" + (f" attached to window {window_id}" if window_id else ""))
                except Exception as e:
                    log_inst.warning(f"Failed to launch onboard with Numpad layout: {e}, trying default layout...")
                    cmd = ['onboard']
                    if window_id is not None:
                        cmd.extend(['--window-id', str(window_id)])
                    subprocess.Popen(cmd, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                return
            
            # 检查 matchbox-keyboard 是否可用
            matchbox_available = False
            try:
                result = subprocess.run(['which', 'matchbox-keyboard'], capture_output=True, text=True, timeout=1)
                matchbox_available = result.returncode == 0
            except:
                pass
            
            if matchbox_available:
                log_inst.info("Matchbox-keyboard detected, launching...")
                time.sleep(0.1)
                subprocess.Popen(['matchbox-keyboard'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                return
            
            # 检查 florence 是否可用
            florence_available = False
            try:
                result = subprocess.run(['which', 'florence'], capture_output=True, text=True, timeout=1)
                florence_available = result.returncode == 0
            except:
                pass
            
            if florence_available:
                log_inst.info("Florence keyboard detected, launching...")
                time.sleep(0.1)
                subprocess.Popen(['florence'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                return
            
            log_inst.warning("No alternative virtual keyboards found. Please install wvkbd-mobintl, onboard, matchbox-keyboard, or florence.")
            log_inst.warning("For numeric input, we recommend installing 'onboard' which supports numeric keypad.")
            
        except Exception as e:
            log_inst.error(f"Error trying alternative keyboards: {e}")
    
    def restore_focus(self):
        """恢复焦点到当前输入框，确保键盘输入能够被接收"""
        try:
            if self.current_focused_obj is not None:
                # 重新设置焦点到输入框
                self.current_focused_obj.setFocus()
                log_inst.info("Restored focus to input field after keyboard launch")
        except Exception as e:
            log_inst.error(f"Error restoring focus: {e}")
        finally:
            self.current_focused_obj = None

    def restore_focus_for_obj(self, obj):
        """为特定对象恢复焦点"""
        try:
            if obj is not None:
                # 检查对象是否仍然有效（没有被销毁）
                if hasattr(obj, 'setFocus'):
                    obj.setFocus()
                    log_inst.info("Restored focus to specific input field after keyboard launch")
                else:
                    log_inst.warning("Focus object is no longer valid")
        except Exception as e:
            log_inst.error(f"Error restoring focus for specific object: {e}")
        finally:
            # 如果当前焦点对象仍然是这个对象，则清空
            if self.current_focused_obj is obj:
                self.current_focused_obj = None

class NoWheelEditFilter(QObject):
    """滚轮只滚动页面，不改数字框和下拉框。下拉列表已打开时仍可滚动列表。"""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return False
        target = obj
        if isinstance(obj, QLineEdit):
            parent = QWidget.parentWidget(obj)
            while parent is not None:
                if isinstance(parent, (QSpinBox, QDoubleSpinBox, QComboBox)):
                    target = parent
                    break
                parent = QWidget.parentWidget(parent)
            else:
                return False
        elif not isinstance(obj, (QSpinBox, QDoubleSpinBox, QComboBox)):
            return False
        event.ignore()
        parent = QWidget.parentWidget(target)
        while parent is not None:
            if isinstance(parent, QScrollArea):
                QApplication.sendEvent(parent, event)
                return True
            parent = QWidget.parentWidget(parent)
        return True


class UIBase():
    def __init__(self):
        self.focus_filter = FocusEventFilter()
        QApplication.instance().installEventFilter(self.focus_filter)
        self._no_wheel_edit_filter = NoWheelEditFilter()
        QApplication.instance().installEventFilter(self._no_wheel_edit_filter)

        self.config = ConfigManager()
        self.diagnostics_manager = DiagnosticsManager(self.config)
        self.baudrate=self.config.baudrate
        self.current_signal_source = 'internal'
        self.raw_logger = None
        self.log_output=[]
        self.spectro_buffer_data=None
        self.spectro_buffer_time=[]


        self.current_stat ={'hv':0,
                                    'rates': 0,
                                    'temp':0}
        
        # Multi-client data tracking
        self.client_data = {}  # {client_id: {'hv': 0, 'rates': 0, 'temp': 0, 'last_update': timestamp}}
        self.total_count_rate = 0  # Sum of all client count rates
        # 探头编号：优先用唯一的 product_id；若冲突/缺失再按 IP 分配 1/2/...
        self._probe_ip_index = {}
        self._probe_registry = {}  # {ip: {'product_id': int, 'client_id': str}}
        
        # Create worker based on configuration
        self.worker = None
        self.worker_thread = QThread()
        self.mirror_hub = None
        
        # Initialize worker based on TCP enabled setting
        self.initialize_worker()
        
        if self.worker:
            self.worker.moveToThread(self.worker_thread)




        
        self.read_timer = QTimer()
        if self.worker:
            # Connect appropriate read loop based on worker type
            if isinstance(self.worker, SerialPacketWorker):
                self.read_timer.timeout.connect(self.worker.read_serial_loop)
            elif is_tcp_worker(self.worker):
                self.read_timer.timeout.connect(self.worker.read_tcp_loop)
        self.read_timer.setInterval(10)

        # 绘图节流：数据仍每包累积，但绘图固定 ~10Hz 刷新，
        # 避免"每包全量重绘 3 张图 + 重建控件"导致的卡顿。
        self._plot_dirty = False
        self._last_client_ids = None
        self._spectrogram_ranges_set = False
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self._on_plot_timer)
        self.plot_timer.start(250)  # 首页默认 4Hz；切到曲线/能谱页再升到 10Hz

        self.packet_counts = {'cmd': 0, 'spectrum': 0, 'errors': 0,'dev_msg':0}
        self.relay_states = None  # (r0, r1, r2) after first packet; None = not yet received
        self.is_acquiring = False
        # 维护人员在概览/能谱点「停止」后置位：连着也不自动开采，直到点开始或退出登录
        self._acq_hold_lock = False
        # 用户主动「停止采集」后抑制自动开采（切端口/reinit 不断监视）
        self._acq_user_stopped = False
        self._tcp_worker_reinit_busy = False
        
        # Multi-client time series data storage
        self.client_time_series = {}  # {client_id: [(timestamp, counter, temperature, HV, spec_sum), ...]}
        self.client_spectrum_data = {}  # {client_id: spectrum_array} - Store spectrum data for each client
        # Auto-save segment buffers (display keeps 15min trim; archive holds since last save)
        self.client_archive_time_series = {}
        self.client_segment_spectrum = {}
        self._last_autosave_client_ids = []
        self.client_latest_packets = {}  # {client_id: latest SpectrumPacket} - used for immediate display switching
        self.primary_client_id = None  # The client whose data is displayed in the chart
        self._last_probe_cps_log_at = 0.0

        # Master L2 summary (homepage / hard-alarm authority)
        self.latest_master_summary = None
        self.master_client_id = None
        self.master_summary_callback = None
        self._master_was_online = False
        self._last_master_ip = ""
        self._master_sensor_mode = 2
        self._sensor_mode_dirty = False
        self._sensor_mode_ack_hold = False
        self._sensor_mode_ack_hold_until = 0.0
        self._sensor_mode_ack_unconfigured = False
        self._pending_sensor_mode_at = 0.0
        self._pending_product_id_write = None
        
        self.spectrum_data = np.zeros(self.config.adc_channels)  # Current displayed spectrum data
        self.temperature_data = []
        self.hv_data = []
        self.timestamps = []
        
        self.channels = np.arange(self.config.adc_channels+ 1)

        self.gain_stabilizer_flag = 2
        # 1 enabled, 0: disabled, 2 not initialized or unknown
        self.gain_stabilizer_pending = False  # Flag to indicate we're waiting for device confirmation
        
        self.worker_thread.start()
        self._autosave_worker = None
        self._autosave_running = False
        self._read_timer_bound = False
        self._tcp_reinit_grace_until = 0.0
        self._bind_read_timer_to_worker()
        
        # Setup UI connections
        self.setup_ui()

        self.data_updated_callback =None
        self.alarm_status_callback = None
        
        # Auto-save configuration - DEFAULT ENABLED as requested by user
        self.auto_save_enabled = True  # Changed from False to True
        self.auto_save_interval = 3600  # 1 hour; segment archive supports long intervals
        self.auto_save_path = ""
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save_data)
        self.last_auto_save_time = time.time()
        self.auto_save_counter = 0
        
        # Start auto-save timer if enabled
        if self.auto_save_enabled:
            self.auto_save_timer.start(self.auto_save_interval * 1000)

        # Master offline watchdog (~1 Hz summary → 3 s timeout)
        self.master_watchdog_timer = QTimer()
        self.master_watchdog_timer.timeout.connect(self._check_master_link)
        self.master_watchdog_timer.start(1000)

        self._setup_data_retention_timers()

    def is_master_online(self) -> bool:
        from core.master_summary import is_master_online
        return is_master_online(self.latest_master_summary)

    def _check_master_link(self):
        """Notify UI once when master summary ages out."""
        online = self.is_master_online()
        if online:
            self._master_was_online = True
            return
        if not self._master_was_online:
            return
        self._master_was_online = False
        if self.master_summary_callback is not None:
            self.master_summary_callback(None, self.master_client_id)

    def on_master_link_seen(self, client_id: str = None):
        """Master TCP frame header seen (may still be awaiting valid CRC)."""
        if not client_id:
            return
        self.master_client_id = client_id
        self._remember_master_endpoint(client_id)
        if hasattr(self, "worker") and self.worker is not None:
            try:
                self.worker.master_client_id = client_id
            except Exception:
                pass
        # 主控不是探头：清掉本会话，以及同一主控 IP 上未识别阶段留下的 E101/E102
        self._clear_master_sessions_from_probe_faults(client_id)
        if self.master_summary_callback is not None and not self.is_master_online():
            # Refresh home status to "TCP connected / waiting L2"
            self.master_summary_callback(None, client_id)

    def on_master_summary_received(self, packet, client_id: str = None):
        """Handle MasterSummaryPacket (60B L2). Homepage CPS/alarm follow this."""
        self.latest_master_summary = packet
        self._master_was_online = True
        if client_id:
            self.master_client_id = client_id
            self._remember_master_endpoint(client_id)
            if hasattr(self, "worker") and self.worker is not None:
                try:
                    self.worker.master_client_id = client_id
                except Exception:
                    pass
            self._clear_master_sessions_from_probe_faults(client_id)
        if self.master_summary_callback is not None:
            self.master_summary_callback(packet, client_id)
        self._maybe_log_all_probe_cps()
        if hasattr(self, "_release_probe_radiation_logs_for_master"):
            self._release_probe_radiation_logs_for_master()

    def _apply_cps_plot_labels(self):
        """Apply localized title/axis labels to count-rate plot."""
        if not hasattr(self, 'cps_widget') or self.cps_widget is None:
            return
        if not hasattr(self.cps_widget, 'setTitle'):
            return
        from core.translation import _t
        n = int(getattr(self, "cps_window_minutes", 5) or 5)
        self.cps_widget.setTitle(
            _t("plot_cps_title_window", n=n), color='#ffffff', size='12pt'
        )
        self.cps_widget.setLabel('left', _t("plot_cps_y"), color='#ffffff')
        self.cps_widget.setLabel('bottom', _t("plot_cps_x_local"), color='#ffffff')
        if hasattr(self, 'curve_cps') and self.curve_cps is not None:
            try:
                self.curve_cps.opts['name'] = _t("plot_cps_legend")
            except Exception:
                pass
        if hasattr(self, "cps_window_label"):
            self.cps_window_label.setText(_t("plot_cps_window"))
        if hasattr(self, "cps_window_combo"):
            cur = self.cps_window_combo.currentData()
            self.cps_window_combo.blockSignals(True)
            self.cps_window_combo.clear()
            for m in CPS_WINDOW_CHOICES:
                self.cps_window_combo.addItem(_t("plot_cps_window_min", n=m), m)
            idx = self.cps_window_combo.findData(cur if cur in CPS_WINDOW_CHOICES else n)
            self.cps_window_combo.setCurrentIndex(idx if idx >= 0 else 1)
            self.cps_window_combo.blockSignals(False)

    def _apply_spec_plot_labels(self):
        """Apply localized title/axis labels to spectrum plot."""
        if not hasattr(self, 'spec_widget') or self.spec_widget is None:
            return
        if not hasattr(self.spec_widget, 'setTitle'):
            return
        from core.translation import _t
        channels = getattr(self.config, 'adc_channels', 4096)
        self.spec_widget.setTitle(
            _t("plot_spec_title", channels=channels), color='#ffffff', size='12pt'
        )
        self.spec_widget.setLabel('left', _t("plot_spec_y"), color='#ffffff')
        self.spec_widget.setLabel('bottom', _t("plot_spec_x"), color='#ffffff')
        if hasattr(self, 'curve_spectrum') and self.curve_spectrum is not None:
            try:
                self.curve_spectrum.opts['name'] = _t("plot_spec_legend")
            except Exception:
                pass

    def _apply_spectrogram_plot_labels(self):
        """Apply localized title/axis labels to spectrogram plot."""
        from core.translation import _t
        if hasattr(self, 'plot_spectrogram') and self.plot_spectrogram is not None:
            try:
                self.plot_spectrogram.setTitle(_t("plot_spectrogram_title"))
                self.plot_spectrogram.setLabel('bottom', _t("plot_spectrogram_x"))
                self.plot_spectrogram.setLabel('left', _t("plot_spectrogram_y"))
            except Exception:
                pass
        if hasattr(self, 'colorbar') and self.colorbar is not None:
            try:
                # ColorBarItem label API varies by pyqtgraph version
                if hasattr(self.colorbar, 'setLabel'):
                    self.colorbar.setLabel(_t("plot_colorbar_counts"))
                elif hasattr(self.colorbar, 'label'):
                    label = self.colorbar.label
                    if hasattr(label, 'setText'):
                        label.setText(_t("plot_colorbar_counts"))
            except Exception:
                pass

    def retranslate_plot_labels(self):
        """Refresh plot titles/axes after language switch."""
        self._apply_cps_plot_labels()
        self._apply_spec_plot_labels()
        self._apply_spectrogram_plot_labels()
    
    def set_chart_stylesheet(self, widget):
        """
        设置图表样式表
        Args:
            widget: 图表widget
        """
        # 设置图表背景和轴颜色
        widget.setBackground('#1a1a1a')
        
        # 设置所有图表的样式
        for plot in widget.ci.items:
            if isinstance(plot, pg.PlotItem):
                # 设置轴颜色
                plot.getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
                plot.getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
                plot.getAxis('right').setPen(pg.mkPen(color='#666666', width=1))
                plot.getAxis('top').setPen(pg.mkPen(color='#666666', width=1))
                
                # 设置轴文本颜色
                plot.getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
                plot.getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
                
                # 设置标题颜色
                label_style = {'color': '#ffffff', 'font-size': '12pt'}
                plot.setTitle(plot.titleLabel.text, color='#ffffff', size='12pt')
    

    def create_cps_widget(self):
        # 创建一个QWidget容器（仅图表，窗口选择放在标题行以免挤占曲线高度）
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        from core.translation import _t
        self.cps_window_minutes = int(getattr(self.config, "cps_window_minutes", 5) or 5)
        if self.cps_window_minutes not in CPS_WINDOW_CHOICES:
            self.cps_window_minutes = 5

        # 若尚未创建窗口控件（由总览页标题行挂载），在此兜底创建
        if not hasattr(self, "cps_window_combo") or self.cps_window_combo is None:
            self._ensure_cps_window_controls()
        
        # 创建PlotWidget：底轴用本地时间
        try:
            date_axis = pg.DateAxisItem(orientation='bottom')
            self.cps_widget = pg.PlotWidget(axisItems={'bottom': date_axis})
        except Exception as e:
            print(f"Error creating PlotWidget: {e}")
            self.cps_widget = QWidget()
            layout.addWidget(QLabel("Chart initialization failed"))
            return container
        
        # 设置图表样式
        self.cps_widget.setBackground('#1a1a1a')
        self._apply_cps_plot_labels()
        
        # 设置轴颜色
        self.cps_widget.getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
        self.cps_widget.getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
        self.cps_widget.getAxis('right').setPen(pg.mkPen(color='#666666', width=1))
        self.cps_widget.getAxis('top').setPen(pg.mkPen(color='#666666', width=1))
        
        # 设置轴文本颜色
        self.cps_widget.getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        self.cps_widget.getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
        
        # 创建曲线
        self.curve_cps = self.cps_widget.plot(
            [], [], pen=pg.mkPen(color='#1f77b4', width=2), name=_t("plot_cps_legend")
        )
        
        # 添加图例
        self.cps_widget.addLegend()
        
        # Y 自动；X 由时间窗口固定
        self.cps_widget.enableAutoRange('y', True)
        self.cps_widget.disableAutoRange('x')
        
        # 确保曲线正确初始化
        self.curve_cps.setData([], [])
        
        # 添加到布局
        layout.addWidget(self.cps_widget)
        
        return container

    def _ensure_cps_window_controls(self):
        """Create compact time-window label+combo (mounted on overview title row)."""
        from core.translation import _t
        if hasattr(self, "cps_window_combo") and self.cps_window_combo is not None:
            return
        minutes = int(getattr(self, "cps_window_minutes",
                              getattr(self.config, "cps_window_minutes", 5)) or 5)
        if minutes not in CPS_WINDOW_CHOICES:
            minutes = 5
        self.cps_window_minutes = minutes
        self.cps_window_label = QLabel(_t("plot_cps_window"))
        self.cps_window_label.setStyleSheet("color: #ffffff; font-size: 12px;")
        self.cps_window_combo = QComboBox()
        self.cps_window_combo.setFixedHeight(24)
        self.cps_window_combo.setMinimumWidth(88)
        self.cps_window_combo.setMaximumWidth(120)
        for m in CPS_WINDOW_CHOICES:
            self.cps_window_combo.addItem(_t("plot_cps_window_min", n=m), m)
        idx = self.cps_window_combo.findData(minutes)
        self.cps_window_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.cps_window_combo.currentIndexChanged.connect(self.on_cps_window_changed)

    def create_cps_window_controls_widget(self):
        """Return a compact widget for the chart title row (does not steal plot height)."""
        self._ensure_cps_window_controls()
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.cps_window_label)
        row.addWidget(self.cps_window_combo)
        wrap.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        return wrap

    def on_cps_window_changed(self, _index=None):
        """切换计数率图时间窗口（1/5/15 分钟）。"""
        if not hasattr(self, "cps_window_combo"):
            return
        minutes = self.cps_window_combo.currentData()
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 5
        if minutes not in CPS_WINDOW_CHOICES:
            minutes = 5
        self.cps_window_minutes = minutes
        self.config.update_settings(cps_window_minutes=minutes)
        self.config.save_settings()
        self._apply_cps_plot_labels()
        try:
            self.update_data()
        except Exception:
            pass
        self.log(f"CPS time window set to {minutes} min", 'INFO')


    def create_spec_widget(self):
        # 创建一个QWidget容器
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建PlotWidget - 更简单，兼容性更好
        try:
            self.spec_widget = pg.PlotWidget()
        except Exception as e:
            # 如果创建失败，尝试不同的方法
            print(f"Error creating PlotWidget for spectrum: {e}")
            # 创建一个普通的QWidget作为后备
            self.spec_widget = QWidget()
            layout.addWidget(QLabel("Spectrum chart initialization failed"))
            return container
        
        # 设置图表样式：与页面同色，避免坐标轴下方多出一条灰带
        self.spec_widget.setBackground('#1a1a1a')
        self._apply_spec_plot_labels()
        
        # 设置轴颜色
        self.spec_widget.getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
        self.spec_widget.getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
        self.spec_widget.getAxis('right').setPen(pg.mkPen(color='#666666', width=1))
        self.spec_widget.getAxis('top').setPen(pg.mkPen(color='#666666', width=1))
        self.spec_widget.showAxis('right', False)
        self.spec_widget.showAxis('top', False)
        
        # 设置轴文本颜色
        self.spec_widget.getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        self.spec_widget.getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
        try:
            self.spec_widget.getAxis('bottom').setStyle(
                autoExpandTextSpace=False, tickTextOffset=4
            )
        except Exception:
            pass
        
        # 创建曲线 - 使用stepMode="center"显示阶梯状能谱
        from core.translation import _t
        self.curve_spectrum = self.spec_widget.plot(
            [], [], stepMode="center", fillLevel=0,
            brush=(31, 119, 180, 100), pen=pg.mkPen(color='#1f77b4', width=2),
            name=_t("plot_spec_legend")
        )
        
        # 添加图例
        self.spec_widget.addLegend()
        
        # 设置X轴范围
        self.spec_widget.setXRange(0, self.config.adc_channels)
        
        # 启用自动范围
        self.spec_widget.enableAutoRange('y', True)
        
        # 确保曲线正确初始化
        self.curve_spectrum.setData([], [])
        
        # 添加到布局
        layout.addWidget(self.spec_widget)
        
        return container
    
    def create_spectrogram_widget(self):
        """Create spectrogram widget"""
        # 创建一个QWidget容器来包装GraphicsLayoutWidget
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建GraphicsLayoutWidget - 确保它被正确识别为QWidget
        try:
            widget = pg.GraphicsLayoutWidget()
        except Exception as e:
            # 如果创建失败，尝试不同的方法
            print(f"Error creating GraphicsLayoutWidget for spectrogram: {e}")
            # 创建一个普通的QWidget作为后备
            widget = QWidget()
            layout.addWidget(QLabel("Spectrogram initialization failed"))
            return container
        
        from core.translation import _t
        self.plot_spectrogram = widget.addPlot(
            row=0, col=0, title=_t("plot_spectrogram_title")
        )
        self.plot_spectrogram.showAxis('right', True)
        self.plot_spectrogram.showAxis('top', True)
        self.plot_spectrogram.getAxis('right').setStyle(showValues=False)
        self.plot_spectrogram.getAxis('top').setStyle(showValues=False)
        self.plot_spectrogram.setLabel('bottom', _t("plot_spectrogram_x"))
        self.plot_spectrogram.setLabel('left', _t("plot_spectrogram_y"))
        
        # Initialize the spectrogram data buffer
        self.spectrogram_data = np.zeros((MAX_SPECTRUM_STORED, self.config.adc_channels))
        self.spectrogram_time_index = 0
        
        # Create ImageItem for the spectrogram
        self.img_spectrogram = pg.ImageItem()
        self.plot_spectrogram.addItem(self.img_spectrogram)
        
        # Set up the color map
        colormap = pg.colormap.get('viridis')
        self.img_spectrogram.setColorMap(colormap)
        
        # Initialize the image with data first
        # Transpose data so Time is on X-axis and Channel is on Y-axis
        display_data = self.spectrogram_data  # Shape becomes (channels, time)
        self.img_spectrogram.setImage(display_data)
        
        # Now set the position and scale of the image
        # QRectF(x, y, width, height) maps to (time_start, channel_start, time_extent, channel_extent)
        self.img_spectrogram.setRect(
            pg.QtCore.QRectF(
                0, 0,  # Start at origin
                MAX_SPECTRUM_STORED,  # Width = time extent
                self.config.adc_channels  # Height = channel extent
            )
        )
        
        # Add color bar
        from core.translation import _t
        self.colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=colormap,
            label=_t("plot_colorbar_counts")
        )
        self.colorbar.setImageItem(self.img_spectrogram)
        widget.addItem(self.colorbar, row=0, col=1)
        
        self.set_chart_stylesheet(widget)
        
        # 确保widget是QWidget类型
        if isinstance(widget, QWidget):
            layout.addWidget(widget)
        else:
            print(f"Warning: spectrogram widget is not QWidget, type: {type(widget)}")
            try:
                layout.addWidget(widget)
            except TypeError as e:
                print(f"Error adding spectrogram widget to layout: {e}")
                # 创建一个简单的QLabel作为后备
                fallback_widget = QLabel("Spectrogram initialization failed")
                fallback_widget.setStyleSheet("color: white; background-color: #2a2a2a;")
                layout.addWidget(fallback_widget)
        
        return container

    def update_spectrogram(self):
        """Update the spectrogram with new spectrum data"""
        # Update data from buffer
        self.spectrogram_data = self.spectro_buffer_data
        
        # Transpose so dimensions match: (channels, time)
        # This ensures Time is on X-axis and Channel is on Y-axis
        display_data = self.spectrogram_data
        
        # Calculate appropriate levels for visualization
        max_value = np.max(display_data)
        if max_value > 0:
            levels = (0, max_value)
        else:
            levels = (0, 1)
        
        # Update the image
        self.img_spectrogram.setImage(
            display_data,
            autoLevels=False,  # Use manual levels for better control
            levels=levels
        )
        
        # Update axis ranges —— 固定不变，只需设置一次，避免每次刷新都重算视图
        if not self._spectrogram_ranges_set:
            self.plot_spectrogram.setXRange(0, MAX_SPECTRUM_STORED)
            self.plot_spectrogram.setYRange(0, self.config.adc_channels)
            self._spectrogram_ranges_set = True

      
        
    def disconnect_worker_signals(self, worker=None):
        """Unbind all slots from a worker being retired (avoid PyQt disconnect AttributeError)."""
        w = worker if worker is not None else getattr(self, "worker", None)
        if not w or not is_tcp_worker(w):
            if w is not None and isinstance(w, SerialPacketWorker):
                for sig in (
                    w.cmd_feedback_received,
                    w.spectrum_packet_received,
                    w.dev_message_received,
                    w.connection_status_changed,
                    w.error_occurred,
                    w.has_log,
                ):
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass
            return
        if hasattr(w, "_unwire_children"):
            try:
                w._unwire_children()
            except (TypeError, RuntimeError, AttributeError):
                pass
        signals = [
            w.cmd_feedback_received,
            w.dev_message_received,
            w.spectrum_packet_received,
            w.connection_status_changed,
            w.error_occurred,
            w.has_log,
            w.command_sent,
            w.client_connected,
            w.client_disconnected,
        ]
        if hasattr(w, "master_summary_received"):
            signals.append(w.master_summary_received)
        if hasattr(w, "master_link_seen"):
            signals.append(w.master_link_seen)
        for sig in signals:
            try:
                sig.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass

    def connect_worker_signals(self):
        """Bind PyQt signals to the current self.worker (after worker replace)."""
        if not self.worker:
            self.log("Warning: Worker not initialized for signal connect", "WARNING")
            return
        w = self.worker
        w.cmd_feedback_received.connect(
            self.on_cmd_feedback_received, Qt.UniqueConnection
        )
        w.dev_message_received.connect(
            self.on_dev_message_received, Qt.UniqueConnection
        )
        w.spectrum_packet_received.connect(
            self.on_spectrum_packet_received, Qt.UniqueConnection
        )
        if hasattr(w, "master_summary_received"):
            w.master_summary_received.connect(
                self.on_master_summary_received, Qt.UniqueConnection
            )
        if hasattr(w, "master_link_seen"):
            w.master_link_seen.connect(self.on_master_link_seen, Qt.UniqueConnection)
        w.connection_status_changed.connect(
            self.on_connection_status_changed, Qt.UniqueConnection
        )
        w.error_occurred.connect(self.on_error_occurred, Qt.UniqueConnection)
        w.has_log.connect(self.on_has_log, Qt.UniqueConnection)
        w.command_sent.connect(self.on_command_sent, Qt.UniqueConnection)
        if is_tcp_worker(w):
            w.client_connected.connect(self.on_tcp_client_connected, Qt.UniqueConnection)
            w.client_disconnected.connect(
                self.on_tcp_client_disconnected, Qt.UniqueConnection
            )

    def setup_ui(self):
        self.connect_worker_signals()
        


    def toggle_raw_packet_logging(self, state):
        enabled = state == Qt.Checked
        self.log_raw_packet_enabled= enabled
        self.log_path_input.setEnabled(enabled)
        self.select_path_btn.setEnabled(enabled)
        self.log(f"Raw packet logging {'enabled' if enabled else 'disabled'}")
        if self.raw_logger:
            self.raw_logger.set_enabled(self.log_raw_packet_enabled)

    def select_log_path(self):
        path = QFileDialog.getExistingDirectory(
            self,
            _t("dlg_select_log_folder"),
            self.log_file_path or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontUseNativeDialog
        )
        if path:
            self.log_file_path = path
            self.log_path_input.setText(path)
            self.log(f"Raw packets will be saved to: {path}")

            self.raw_logger = RawLogger(path)
            self.worker.set_logger(self.raw_logger, self.log)
            self.raw_logger.set_enabled(self.log_raw_packet_enabled)

    def toggle_signal_source(self):
        if self.ensure_serial_ready():
            from_internal = False if self.current_signal_source =='internal' else True
            self.worker.set_input_signal_source(from_internal)

    def toggle_gain_stabilizer(self):
        if self.ensure_serial_ready():
            # If gain_stabilizer_flag is 2 (not initialized), default to turning it ON
            if self.gain_stabilizer_flag == 2:
                stat = 1  # Turn ON
            else:
                stat = 0 if self.gain_stabilizer_flag == 1 else 1
            
            self.log(f"Current gain_stabilizer_flag: {self.gain_stabilizer_flag}, setting to: {stat}", 'DEBUG')
            
            # Set pending flag to prevent immediate overwrite by spectrum packets
            self.gain_stabilizer_pending = True
            
            # Send command to device
            success = self.worker.set_gain_stabilizer_flag(bool(stat))
            
            if success:
                # Immediately update local state and UI
                self.gain_stabilizer_flag = stat
                self.update_control_labels()
                self.log(f"Gain stabilizer set to {'ON' if stat == 1 else 'OFF'}", 'INFO')
            else:
                self.log("Failed to send gain stabilizer command", 'ERROR')
                self.gain_stabilizer_pending = False

    def _make_settings_action_btn(self, text, color):
        from core.ui_tokens import CR_CHROME_H, CR_CHROME_FONT_PX
        desktop = bool(getattr(self, "control_room_mode", False))
        h = CR_CHROME_H + 4 if desktop else 40
        fs = CR_CHROME_FONT_PX if desktop else 14
        btn = QPushButton(text)
        btn.setMinimumHeight(h)
        btn.setStyleSheet("""
            QPushButton {
                background-color: %s; color: white; border: none;
                border-radius: 8px; font-size: %dpx; font-weight: bold;
                padding: 0 18px; min-height: %dpx;
            }
            QPushButton:pressed { background-color: #333333; }
            QPushButton:disabled { background-color: #555555; color: #999999; }
        """ % (color, fs, h))
        return btn

    def add_widgets_to_setting_layout(self, settings_layout):
       # Settings placeholder
        
        from core.translation import _t, TranslationManager
        from core.app_version import software_version_display

        self.version_group = QGroupBox(_t("set_version_info"))
        version_layout = QGridLayout(self.version_group)
        self.software_version_title_label = QLabel(_t("set_software_version"))
        self.software_version_title_label.setToolTip(_t("tip_software_version"))
        lang = TranslationManager().get_language()
        multi = bool(getattr(self.config, "tcp_multi_port", False))
        self.software_version_value_label = QLabel(
            software_version_display(lang, multi_port=multi)
        )
        self.software_version_value_label.setToolTip(_t("tip_software_version"))
        self.software_version_value_label.setStyleSheet(
            "color: #ff9800; font-size: 13px; font-weight: bold;"
        )
        version_layout.addWidget(self.software_version_title_label, 0, 0)
        version_layout.addWidget(self.software_version_value_label, 0, 1, 1, 3)
        settings_layout.addWidget(self.version_group)

        self.comm_group = QGroupBox(_t("set_comm_settings"))
        comm_layout = QGridLayout(self.comm_group)
        
        # TCP/IP Enable Checkbox
        self.tcp_enable_checkbox = QCheckBox(_t("set_tcp_enable"))
        self.tcp_enable_checkbox.setChecked(self.config.tcp_enabled)
        self.tcp_enable_checkbox.stateChanged.connect(self.on_tcp_enable_changed)
        comm_layout.addWidget(self.tcp_enable_checkbox, 0, 0, 1, 4)
        
        # Server Settings (always shown when TCP is enabled)
        self.server_host_label = QLabel(_t("set_server_host"))
        comm_layout.addWidget(self.server_host_label, 1, 0)
        self.tcp_host_input = QLineEdit(self.config.tcp_host)
        self.tcp_host_input.setPlaceholderText(_t("set_server_host_placeholder"))
        self.tcp_host_input.textChanged.connect(self.on_tcp_host_changed)
        comm_layout.addWidget(self.tcp_host_input, 1, 1)
        
        self.server_port_label = QLabel(_t("set_server_port"))
        comm_layout.addWidget(self.server_port_label, 1, 2)
        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1, 65535)
        self.tcp_port_spin.setValue(self.config.tcp_port)
        self.tcp_port_spin.valueChanged.connect(self.on_tcp_port_changed)
        comm_layout.addWidget(self.tcp_port_spin, 1, 3)

        self.tcp_multi_port_checkbox = QCheckBox(_t("set_tcp_multi_port"))
        self.tcp_multi_port_checkbox.setChecked(bool(getattr(self.config, "tcp_multi_port", False)))
        self.tcp_multi_port_checkbox.stateChanged.connect(self.on_tcp_multi_port_changed)
        comm_layout.addWidget(self.tcp_multi_port_checkbox, 2, 0, 1, 4)

        self.tcp_port_master_label = QLabel(_t("set_tcp_port_master"))
        comm_layout.addWidget(self.tcp_port_master_label, 3, 0)
        self.tcp_port_master_spin = QSpinBox()
        self.tcp_port_master_spin.setRange(1, 65535)
        self.tcp_port_master_spin.setValue(
            int(getattr(self.config, "tcp_port_master", DEFAULT_TCP_PORT_MASTER))
        )
        self.tcp_port_master_spin.valueChanged.connect(self.on_tcp_port_master_changed)
        comm_layout.addWidget(self.tcp_port_master_spin, 3, 1)

        self.tcp_port_probe_label = QLabel(_t("set_tcp_port_probe"))
        comm_layout.addWidget(self.tcp_port_probe_label, 3, 2)
        self.tcp_port_probe_spin = QSpinBox()
        self.tcp_port_probe_spin.setRange(1, 65535)
        self.tcp_port_probe_spin.setValue(
            int(getattr(self.config, "tcp_port_probe", DEFAULT_TCP_PORT_PROBE))
        )
        self.tcp_port_probe_spin.valueChanged.connect(self.on_tcp_port_probe_changed)
        comm_layout.addWidget(self.tcp_port_probe_spin, 3, 3)
        
        # Serial Settings (only shown when TCP is disabled)
        self.serial_port_label = QLabel(_t("set_serial_port"))
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.addItems(search_serial_devices())
        self.serial_port_combo.setCurrentText(self.config.device)
        self.serial_port_combo.currentTextChanged.connect(self.on_serial_port_changed)
        
        # Add refresh button next to serial port combo
        self.refresh_serial_btn = QPushButton(_t("btn_refresh"))
        self.refresh_serial_btn.setToolTip("Refresh available serial ports")
        self.refresh_serial_btn.clicked.connect(self.refresh_serial_ports)
        
        self.baudrate_label = QLabel(_t("set_baudrate"))
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baudrate_combo.setCurrentText(str(self.config.baudrate))
        self.baudrate_combo.currentTextChanged.connect(self.on_baudrate_changed)
        
        # Add serial settings to layout
        comm_layout.addWidget(self.serial_port_label, 4, 0)
        comm_layout.addWidget(self.serial_port_combo, 4, 1)
        comm_layout.addWidget(self.refresh_serial_btn, 4, 2)
        
        # Add manual reconnect button
        self.reconnect_serial_btn = QPushButton(_t("btn_reconnect"))
        self.reconnect_serial_btn.setToolTip("Manually reconnect to selected serial port")
        self.reconnect_serial_btn.clicked.connect(self.manual_reconnect_serial)
        comm_layout.addWidget(self.reconnect_serial_btn, 4, 3)
        
        comm_layout.addWidget(self.baudrate_label, 5, 0)
        comm_layout.addWidget(self.baudrate_combo, 5, 1)
        
        # Client Selection for multi-client mode - MOVED HERE as requested by user
        self.client_selection_label = QLabel(_t("set_display_client"))
        self.client_selection_combo = QComboBox()
        self.client_selection_combo.addItem(_t("set_display_client_auto"))
        self.client_selection_combo.currentTextChanged.connect(self.on_client_selection_changed)
        self.client_selection_combo.setEnabled(False)  # Initially disabled until clients are available
        
        comm_layout.addWidget(self.client_selection_label, 6, 0, 1, 1)
        comm_layout.addWidget(self.client_selection_combo, 6, 1, 1, 3)
        
        # Update visibility based on current settings
        self.update_comm_settings_visibility()
        
        settings_layout.addWidget(self.comm_group)
  
        # Group 2: Detector Settings
        self.det_group = QGroupBox(_t("set_det_settings"))
        det_layout = QGridLayout(self.det_group)
        
        self.hv_spin = QDoubleSpinBox()
        self.hv_spin.setDecimals(2)
        self.hv_spin.setRange(0, 1500)  # 根据参考代码修改范围
        self.hv_spin.setValue(self.config.hv)
        self.hv_spin.editingFinished.connect(self.persist_hv_setting)
        
        self.hv_set_btn = QPushButton(_t("btn_set_hv"))
        self.hv_set_btn.clicked.connect(self.set_high_voltage)
        
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 2200)
        self.threshold_spin.setValue(self.config.threshold)
        self.threshold_spin.editingFinished.connect(self.persist_threshold_setting)
        
        self.threshold_set_btn = QPushButton(_t("btn_set_threshold"))
        self.threshold_set_btn.clicked.connect(self.set_threshold)
        
        self.bias_voltage_label = QLabel(_t("set_bias_voltage"))
        det_layout.addWidget(self.bias_voltage_label, 0, 0)
        det_layout.addWidget(self.hv_spin, 0, 1)
        det_layout.addWidget(self.hv_set_btn, 0, 2)
        self.threshold_label = QLabel(_t("set_threshold"))
        det_layout.addWidget(self.threshold_label, 1, 0)
        det_layout.addWidget(self.threshold_spin, 1, 1)
        det_layout.addWidget(self.threshold_set_btn, 1, 2)
        
        settings_layout.addWidget(self.det_group)
        
        # Group 3: Control
        self.ctrl_group = QGroupBox(_t("set_control"))
        ctrl_layout = QGridLayout(self.ctrl_group)

        # 根据参考代码，只保留Gain Stabilizer
        self.gain_stabilizer_btn = QPushButton(_t("btn_turn_on"))
        self.gain_stabilizer_label = QLabel(_t("status_off"))
        self.gain_stabilizer_btn.clicked.connect(lambda: self.toggle_gain_stabilizer())
        self.gain_stabilizer_title_label = QLabel(_t("set_gain_stabilizer"))
        ctrl_layout.addWidget(self.gain_stabilizer_title_label, 0, 0, 1, 1)
        ctrl_layout.addWidget(self.gain_stabilizer_label, 0, 1)
        ctrl_layout.addWidget(self.gain_stabilizer_btn, 0, 2)

        # UI mode: field tablet vs control-room PC (restart required)
        self.ui_mode_label = QLabel(_t("set_ui_mode"))
        self.ui_mode_label.setToolTip(_t("tip_ui_mode"))
        self.ui_mode_combo = QComboBox()
        self.ui_mode_combo.addItem(_t("set_ui_mode_tablet"), "tablet")
        self.ui_mode_combo.addItem(_t("set_ui_mode_control_room"), "control_room")
        cur_mode = str(getattr(self.config, "ui_mode", "tablet") or "tablet")
        idx = self.ui_mode_combo.findData(cur_mode)
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ui_mode_combo.setToolTip(_t("tip_ui_mode"))
        self.ui_mode_combo.currentIndexChanged.connect(self.on_ui_mode_changed)
        ctrl_layout.addWidget(self.ui_mode_label, 1, 0)
        ctrl_layout.addWidget(self.ui_mode_combo, 1, 1, 1, 2)

        # Home probe card location labels (count follows expected_probe_count)
        self.probe_locations_label = QLabel(_t("set_probe_locations"))
        self.probe_locations_label.setToolTip(_t("tip_probe_locations"))
        ctrl_layout.addWidget(self.probe_locations_label, 2, 0, 1, 3)
        self.probe_location_wrap = QWidget()
        self.probe_location_grid = QGridLayout(self.probe_location_wrap)
        self.probe_location_grid.setContentsMargins(0, 0, 0, 0)
        self.probe_location_grid.setSpacing(6)
        self.probe_location_edits = []
        self.probe_location_slot_labels = []
        self.probe_location_cells = []
        self._rebuild_probe_location_edits()
        ctrl_layout.addWidget(self.probe_location_wrap, 3, 0, 1, 3)

        # One-click factory parameter reset (command 0x14 → probe TCP/serial)
        self.factory_reset_label = QLabel(_t("set_factory_reset"))
        self.reset_defaults_current_btn = QPushButton(_t("btn_reset_current"))
        self.reset_defaults_current_btn.setToolTip(_t("tip_reset_defaults"))
        self.reset_defaults_current_btn.clicked.connect(lambda: self.reset_factory_defaults(all_probes=False))
        self.reset_defaults_all_btn = QPushButton(_t("btn_reset_all"))
        self.reset_defaults_all_btn.setToolTip(_t("tip_reset_defaults"))
        self.reset_defaults_all_btn.clicked.connect(lambda: self.reset_factory_defaults(all_probes=True))
        ctrl_layout.addWidget(self.factory_reset_label, 4, 0)
        ctrl_layout.addWidget(self.reset_defaults_current_btn, 4, 1)
        ctrl_layout.addWidget(self.reset_defaults_all_btn, 4, 2)

        settings_layout.addWidget(self.ctrl_group)

        # --- Virtual Keyboard Group ---
        self.keyboard_group = QGroupBox(_t("set_keyboard"))
        keyboard_layout = QGridLayout(self.keyboard_group)

        from core.software_keyboard import should_use_software_keyboard
        kb_on = bool(should_use_software_keyboard())
        self.keyboard_enable_checkbox = QCheckBox(_t("set_keyboard_enable"))
        self.keyboard_enable_checkbox.setChecked(kb_on)
        self.focus_filter.keyboard_enabled = kb_on
        self.keyboard_enable_checkbox.stateChanged.connect(self.toggle_virtual_keyboard)
        keyboard_layout.addWidget(self.keyboard_enable_checkbox, 0, 0, 1, 2)
        
        self.keyboard_status_label = QLabel(
            _t("status_enabled") if kb_on else _t("status_disabled")
        )
        if kb_on:
            self.keyboard_status_label.setStyleSheet("color: green;")
        else:
            self.keyboard_status_label.setStyleSheet("color: gray;")
        keyboard_layout.addWidget(self.keyboard_status_label, 1, 0, 1, 2)
        
        settings_layout.addWidget(self.keyboard_group)

        # --- Device Control and Status Group (根据参考代码添加) ---
        self.device_group = QGroupBox(_t("set_device_status"))
        device_layout = QGridLayout(self.device_group)
        
        # Product ID (只显示，不设置)
        self.product_id_label = QLabel("--")
        self.product_id_title_label = QLabel(_t("label_product_id"))
        device_layout.addWidget(self.product_id_title_label, 0, 0)
        device_layout.addWidget(self.product_id_label, 0, 1, 1, 4)

        self.identity_maintenance_label = QLabel(_t("set_identity_maintenance"))
        self.identity_maintenance_label.setToolTip(_t("tip_identity_maintenance"))
        self.product_id_spin = QSpinBox()
        self.product_id_spin.setRange(0, 65535)
        self.product_id_spin.setToolTip(_t("tip_product_id_maintenance"))
        self.product_id_read_btn = QPushButton(_t("btn_read_product_id"))
        self.product_id_read_btn.setToolTip(_t("tip_product_id_maintenance"))
        self.product_id_read_btn.clicked.connect(self.read_product_id)
        self.product_id_write_btn = QPushButton(_t("btn_write_product_id"))
        self.product_id_write_btn.setToolTip(_t("tip_product_id_maintenance"))
        self.product_id_write_btn.clicked.connect(self.set_product_id)
        self.product_id_unlock_btn = QPushButton(_t("btn_unlock_product_id"))
        self.product_id_unlock_btn.setToolTip(_t("tip_product_id_maintenance"))
        self.product_id_unlock_btn.clicked.connect(self.unlock_product_id_edit)
        self.product_id_lock_label = QLabel(_t("status_product_id_locked"))
        self.product_id_lock_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.product_id_lock_label.setWordWrap(True)

        device_layout.addWidget(self.identity_maintenance_label, 1, 0)
        device_layout.addWidget(self.product_id_spin, 1, 1)
        device_layout.addWidget(self.product_id_read_btn, 1, 2)
        device_layout.addWidget(self.product_id_write_btn, 1, 3)
        device_layout.addWidget(self.product_id_unlock_btn, 1, 4)
        device_layout.addWidget(self.product_id_lock_label, 2, 0, 1, 5)
        
        # Sensitivity Coefficient (报警灵敏度系数)
        self.sensitivity_label = QLabel("--")
        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setDecimals(1)
        self.sensitivity_spin.setSingleStep(0.1)
        self.sensitivity_spin.setRange(1.0, 10.0)
        self.sensitivity_spin.setValue(float(self.config.sensitivity))
        self.sensitivity_spin.editingFinished.connect(self.persist_sensitivity_setting)
        self.sensitivity_set_btn = QPushButton(_t("btn_set"))
        self.sensitivity_set_btn.clicked.connect(self.set_sensitivity_coefficient)
        self.sensitivity_read_btn = QPushButton(_t("btn_read"))
        self.sensitivity_read_btn.clicked.connect(self.read_sensitivity_coefficient)
        
        self.sensitivity_title_label = QLabel(_t("label_sensitivity"))
        device_layout.addWidget(self.sensitivity_title_label, 3, 0)
        device_layout.addWidget(self.sensitivity_label, 3, 1)
        device_layout.addWidget(self.sensitivity_spin, 3, 2)
        device_layout.addWidget(self.sensitivity_set_btn, 3, 3)
        device_layout.addWidget(self.sensitivity_read_btn, 3, 4)
        
        # Relay Control (探头继电器 — 发往当前选中探头，勿发主控)
        self.relay0_checkbox = QCheckBox("Relay 0")
        self.relay0_checkbox.stateChanged.connect(lambda state: self.control_single_relay(0, state == Qt.Checked))
        self.relay1_checkbox = QCheckBox("Relay 1")
        self.relay1_checkbox.stateChanged.connect(lambda state: self.control_single_relay(1, state == Qt.Checked))
        self.relay2_checkbox = QCheckBox("Relay 2")
        self.relay2_checkbox.stateChanged.connect(lambda state: self.control_single_relay(2, state == Qt.Checked))
        
        self.relay_status_label = QLabel(_t("set_relay_status"))
        self.relay_read_btn = QPushButton(_t("btn_read_status"))
        self.relay_read_btn.clicked.connect(self.read_relay_status)
        
        # 创建一个水平布局来均匀放置三个继电器复选框
        relay_checkbox_layout = QHBoxLayout()
        relay_checkbox_layout.addWidget(self.relay0_checkbox)
        relay_checkbox_layout.addWidget(self.relay1_checkbox)
        relay_checkbox_layout.addWidget(self.relay2_checkbox)
        relay_checkbox_layout.addStretch()  # 添加弹性空间
        
        self.relay_control_title_label = QLabel(_t("set_probe_relay_control"))
        device_layout.addWidget(self.relay_control_title_label, 4, 0)
        device_layout.addLayout(relay_checkbox_layout, 4, 1, 1, 3)
        device_layout.addWidget(self.relay_read_btn, 4, 4)
        device_layout.addWidget(self.relay_status_label, 5, 0, 1, 5)
        self.probe_relay_hint_label = QLabel(_t("tip_probe_relay_hint"))
        self.probe_relay_hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.probe_relay_hint_label.setWordWrap(True)
        device_layout.addWidget(self.probe_relay_hint_label, 6, 0, 1, 5)
        
        # Alarm Status (报警状态)
        self.alarm_status_label = QLabel("--")
        self.alarm_read_btn = QPushButton(_t("btn_read_alarm"))
        self.alarm_read_btn.clicked.connect(self.read_alarm_status)
        
        self.alarm_status_title_label = QLabel(_t("card_alarm_title"))
        device_layout.addWidget(self.alarm_status_title_label, 7, 0)
        device_layout.addWidget(self.alarm_status_label, 7, 1, 1, 3)
        device_layout.addWidget(self.alarm_read_btn, 7, 4)
        
        # Occupancy Status — 通道占用跟主控 L2（红外/雷达），不跟探头 bit5
        self.occupancy_status_label = QLabel("--")
        self.occupancy_title_label = QLabel(_t("set_occupancy"))
        device_layout.addWidget(self.occupancy_title_label, 8, 0)
        device_layout.addWidget(self.occupancy_status_label, 8, 1, 1, 4)
        
        # Counter Display
        self.counter_label = QLabel("--")
        self.counter_title_label = QLabel(_t("set_counter"))
        device_layout.addWidget(self.counter_title_label, 9, 0)
        device_layout.addWidget(self.counter_label, 9, 1, 1, 4)
        
        settings_layout.addWidget(self.device_group)

        # --- Master Relay Control (same UX as probe: checkbox toggle = send) ---
        self.master_relay_group = QGroupBox(_t("set_master_relay"))
        master_relay_layout = QGridLayout(self.master_relay_group)

        self.master_relay0_checkbox = QCheckBox(_t("master_relay_cb0"))
        self.master_relay0_checkbox.stateChanged.connect(
            lambda state: self.control_master_relay(0, state == Qt.Checked)
        )
        self.master_relay1_checkbox = QCheckBox(_t("master_relay_cb1"))
        self.master_relay1_checkbox.setEnabled(False)
        self.master_relay1_checkbox.setToolTip(_t("tip_master_relay1_auto"))
        self.master_relay2_checkbox = QCheckBox(_t("master_relay_cb2"))
        self.master_relay2_checkbox.stateChanged.connect(
            lambda state: self.control_master_relay(2, state == Qt.Checked)
        )

        master_cb_row = QHBoxLayout()
        master_cb_row.addWidget(self.master_relay0_checkbox)
        master_cb_row.addWidget(self.master_relay1_checkbox)
        master_cb_row.addWidget(self.master_relay2_checkbox)
        master_cb_row.addStretch()

        self.master_relay_read_btn = QPushButton(_t("btn_read_status"))
        self.master_relay_read_btn.clicked.connect(self.read_master_relay_status)
        self.master_relay_status_label = QLabel(_t("set_master_relay_status"))
        self.master_relay_states = None  # (r0, r1, r2)
        self._pending_master_relay_cmd = 0.0
        self._pending_master_relay_num = None
        self._pending_probe_relay_cmd = 0.0
        self._probe_relay_hold_until = 0.0
        # keep attrs so older enable/retranslate code does not crash
        self.master_relay_r1_btn = None
        self.master_relay_r2_btn = None
        self.master_relay_apply_btn = None
        self.master_relay_draft_label = None

        self.master_relay_control_title = QLabel(_t("set_master_relay_control"))
        master_relay_layout.addWidget(self.master_relay_control_title, 0, 0)
        master_relay_layout.addLayout(master_cb_row, 0, 1, 1, 3)
        master_relay_layout.addWidget(self.master_relay_read_btn, 0, 4)
        self.master_force_gate_btn = QPushButton(_t("btn_force_open_gate"))
        self.master_force_gate_btn.setToolTip(_t("tip_force_open_gate"))
        self.master_force_gate_btn.clicked.connect(self.force_open_master_gate)
        self.master_force_gate_btn.setVisible(False)
        master_relay_layout.addWidget(self.master_force_gate_btn, 0, 5)
        master_relay_layout.addWidget(self.master_relay_status_label, 1, 0, 1, 6)
        self.master_relay_hint_label = QLabel(_t("tip_master_relay_hint"))
        self.master_relay_hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.master_relay_hint_label.setWordWrap(True)
        master_relay_layout.addWidget(self.master_relay_hint_label, 2, 0, 1, 6)

        settings_layout.addWidget(self.master_relay_group)

        # --- 通道开通（期望探头数 + 传感器模式；占用状态只读，不在此写入）---
        self.channel_gate_group = QGroupBox(_t("set_channel_gate"))
        gate_layout = QGridLayout(self.channel_gate_group)

        self.expected_probe_label = QLabel(_t("set_expected_probes"))
        self.expected_probe_spin = QSpinBox()
        self.expected_probe_spin.setRange(0, 16)
        self.expected_probe_spin.setValue(int(getattr(self.config, "expected_probe_count", 2) or 0))
        self.expected_probe_spin.setToolTip(_t("tip_expected_probes"))
        self.expected_probe_spin.valueChanged.connect(self.on_expected_probe_count_changed)
        self.adopt_probe_count_btn = QPushButton(_t("btn_adopt_probe_count"))
        self.adopt_probe_count_btn.setToolTip(_t("tip_adopt_probe_count"))
        self.adopt_probe_count_btn.clicked.connect(self.adopt_current_probe_count)
        gate_layout.addWidget(self.expected_probe_label, 0, 0)
        gate_layout.addWidget(self.expected_probe_spin, 0, 1)
        gate_layout.addWidget(self.adopt_probe_count_btn, 0, 2, 1, 3)

        self.sensor_mode_label = QLabel(_t("set_sensor_mode"))
        self.sensor_mode_combo = QComboBox()
        self.sensor_mode_combo.addItem(_t("sensor_mode_ir"), 0)
        self.sensor_mode_combo.addItem(_t("sensor_mode_radar"), 1)
        self.sensor_mode_combo.addItem(_t("sensor_mode_unconfigured"), 2)
        self.sensor_mode_combo.setToolTip(_t("tip_sensor_mode"))
        self.sensor_mode_combo.currentIndexChanged.connect(self.on_sensor_mode_combo_changed)
        self.sensor_mode_read_btn = QPushButton(_t("btn_read_sensor_mode"))
        self.sensor_mode_read_btn.clicked.connect(self.read_master_sensor_mode)
        self.sensor_mode_write_btn = QPushButton(_t("btn_write_sensor_mode"))
        self.sensor_mode_write_btn.setToolTip(_t("tip_write_sensor_mode"))
        self.sensor_mode_write_btn.clicked.connect(self.write_master_sensor_mode)
        self.sensor_mode_status_label = QLabel(_t("tip_sensor_mode"))
        self.sensor_mode_status_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.sensor_mode_status_label.setWordWrap(True)
        self.commission_status_label = QLabel(_t("commission_status_need_master"))
        self.commission_status_label.setStyleSheet("color: #888888; font-size: 12px; font-weight: bold;")
        self.commission_status_label.setWordWrap(True)
        gate_layout.addWidget(self.sensor_mode_label, 1, 0)
        gate_layout.addWidget(self.sensor_mode_combo, 1, 1, 1, 2)
        gate_layout.addWidget(self.sensor_mode_read_btn, 1, 3)
        gate_layout.addWidget(self.sensor_mode_write_btn, 1, 4)
        gate_layout.addWidget(self.sensor_mode_status_label, 2, 0, 1, 5)
        gate_layout.addWidget(self.commission_status_label, 3, 0, 1, 5)

        self.alarm_clear_mode_label = QLabel(_t("set_alarm_clear_mode"))
        self.alarm_clear_mode_combo = QComboBox()
        self.alarm_clear_mode_combo.addItem(_t("latch_mode_auto"), 0)
        self.alarm_clear_mode_combo.addItem(_t("latch_mode_latch"), 1)
        self.alarm_clear_mode_combo.setToolTip(_t("tip_alarm_clear_mode"))
        self.alarm_clear_mode_combo.currentIndexChanged.connect(self.on_alarm_clear_mode_combo_changed)
        self.alarm_clear_mode_read_btn = QPushButton(_t("btn_read_clear_mode"))
        self.alarm_clear_mode_read_btn.clicked.connect(self.read_master_alarm_clear_mode)
        self.alarm_clear_mode_write_btn = QPushButton(_t("btn_write_clear_mode"))
        self.alarm_clear_mode_write_btn.setToolTip(_t("tip_write_clear_mode"))
        self.alarm_clear_mode_write_btn.clicked.connect(self.write_master_alarm_clear_mode)
        gate_layout.addWidget(self.alarm_clear_mode_label, 4, 0)
        gate_layout.addWidget(self.alarm_clear_mode_combo, 4, 1, 1, 2)
        gate_layout.addWidget(self.alarm_clear_mode_read_btn, 4, 3)
        gate_layout.addWidget(self.alarm_clear_mode_write_btn, 4, 4)

        self.channel_gate_hint_label = QLabel(_t("tip_channel_gate"))
        self.channel_gate_hint_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.channel_gate_hint_label.setWordWrap(True)
        gate_layout.addWidget(self.channel_gate_hint_label, 5, 0, 1, 5)

        # 旧「本通道接了红外」勾选已取消：对射明细跟主控传感器模式自动对齐
        self.ir_installed_checkbox = None

        settings_layout.addWidget(self.channel_gate_group)


        # --- Telemetry Logging Group ---
        self.log_group = QGroupBox(_t("set_raw_logging"))
        log_to_file_layout = QVBoxLayout(self.log_group)

        self.telemetry_checkbox = QCheckBox(_t("set_logging_enable"))
        self.telemetry_checkbox.setChecked(False)
        self.telemetry_checkbox.stateChanged.connect(self.toggle_raw_packet_logging)

        self.log_path_input = QLineEdit()
        self.log_path_input.setPlaceholderText(_t("set_logging_placeholder"))
        self.log_path_input.setEnabled(False)

        self.select_path_btn = QPushButton(_t("btn_browse"))
        self.select_path_btn.setEnabled(False)
        self.select_path_btn.clicked.connect(self.select_log_path)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.log_path_input)
        path_layout.addWidget(self.select_path_btn)

        log_to_file_layout.addWidget(self.telemetry_checkbox)
        log_to_file_layout.addLayout(path_layout)

        settings_layout.addWidget(self.log_group)

        # Storage for telemetry config
        self.log_raw_packet_enabled= False
        self.log_file_path = ""

        # --- Auto-Save Group ---
        self.auto_save_group = QGroupBox(_t("set_auto_save"))
        auto_save_layout = QGridLayout(self.auto_save_group)
        
        # Auto-save enable checkbox - DEFAULT CHECKED as requested by user
        self.auto_save_checkbox = QCheckBox(_t("set_auto_save_enable"))
        self.auto_save_checkbox.setChecked(True)  # Default checked
        self.auto_save_checkbox.stateChanged.connect(self.toggle_auto_save)
        auto_save_layout.addWidget(self.auto_save_checkbox, 0, 0, 1, 4)
        
        # Auto-save interval
        self.save_interval_title_label = QLabel(_t("set_save_interval"))
        auto_save_layout.addWidget(self.save_interval_title_label, 1, 0)
        self.auto_save_interval_spin = QSpinBox()
        self.auto_save_interval_spin.setRange(60, 86400)  # 1 minute to 1 day (24 hours)
        self.auto_save_interval_spin.setValue(self.auto_save_interval)
        self.auto_save_interval_spin.setSingleStep(300)  # 5 minute steps for better usability
        self.auto_save_interval_spin.valueChanged.connect(self.set_auto_save_interval)
        auto_save_layout.addWidget(self.auto_save_interval_spin, 1, 1)
        _tip_archive = _t("tip_auto_save_interval")
        self.save_interval_title_label.setToolTip(_tip_archive)
        self.auto_save_interval_spin.setToolTip(_tip_archive)
        
        # Add time unit conversion helper
        self.auto_save_interval_label = QLabel(f"({self.format_time_interval(self.auto_save_interval)})")
        auto_save_layout.addWidget(self.auto_save_interval_label, 1, 2)
        
        # Auto-save path
        self.save_path_title_label = QLabel(_t("set_save_path"))
        auto_save_layout.addWidget(self.save_path_title_label, 2, 0)
        self.auto_save_path_input = QLineEdit()
        self.auto_save_path_input.setPlaceholderText(_t("set_save_path_placeholder"))
        self.auto_save_path_input.setText(self.auto_save_path)
        self.auto_save_path_input.setEnabled(False)
        auto_save_layout.addWidget(self.auto_save_path_input, 2, 1, 1, 2)
        
        self.auto_save_path_btn = QPushButton(_t("btn_browse"))
        self.auto_save_path_btn.clicked.connect(self.select_auto_save_path)
        self.auto_save_path_btn.setEnabled(False)
        auto_save_layout.addWidget(self.auto_save_path_btn, 2, 3)
        
        # Enable path controls since auto-save is enabled by default
        self.auto_save_path_input.setEnabled(True)
        self.auto_save_path_btn.setEnabled(True)
        
        # Auto-save counter display
        self.auto_save_counter_label = QLabel(_t("set_auto_saves_count", count=0))
        auto_save_layout.addWidget(self.auto_save_counter_label, 3, 0, 1, 4)
        
        # Enable/disable path controls based on auto-save state
        self.auto_save_path_input.setEnabled(self.auto_save_enabled)
        self.auto_save_path_btn.setEnabled(self.auto_save_enabled)
        
        settings_layout.addWidget(self.auto_save_group)

        # --- Accounts & Data / Maintenance actions ---
        self.admin_ops_group = QGroupBox(_t("set_admin_ops"))
        admin_ops_layout = QVBoxLayout(self.admin_ops_group)
        self.admin_ops_hint = QLabel(_t("tip_admin_ops"))
        self.admin_ops_hint.setStyleSheet("color: #888888; font-size: 11px;")
        self.admin_ops_hint.setWordWrap(True)
        admin_ops_layout.addWidget(self.admin_ops_hint)

        admin_ops_btn_row = QHBoxLayout()
        self.settings_save_btn = self._make_settings_action_btn(_t("btn_save"), "#2196F3")
        self.settings_save_btn.clicked.connect(self.save_data)
        admin_ops_btn_row.addWidget(self.settings_save_btn)

        self.settings_clear_btn = self._make_settings_action_btn(_t("btn_clear"), "#ff9800")
        self.settings_clear_btn.clicked.connect(self.clear_data)
        admin_ops_btn_row.addWidget(self.settings_clear_btn)

        self.settings_users_btn = self._make_settings_action_btn(_t("btn_user_mgmt"), "#9C27B0")
        self.settings_users_btn.clicked.connect(self.show_user_management)
        admin_ops_btn_row.addWidget(self.settings_users_btn)

        self.settings_logout_btn = self._make_settings_action_btn(_t("btn_logout"), "#e53935")
        self.settings_logout_btn.clicked.connect(self.logout)
        admin_ops_btn_row.addWidget(self.settings_logout_btn)
        admin_ops_btn_row.addStretch()
        admin_ops_layout.addLayout(admin_ops_btn_row)
        settings_layout.addWidget(self.admin_ops_group)

        settings_layout.addStretch()



    def log(self, message, dtype='INFO'):
        if dtype == 'ERROR':
            log_inst.error(message)
        elif dtype in ('WARN', 'WARNING'):
            log_inst.warning(message)
        elif dtype == 'DEBUG':
            log_inst.debug(message)
        else:
            log_inst.info(message)

    def update_control_labels(self):
        if self.gain_stabilizer_flag == 1:
            self.gain_stabilizer_btn.setText(_t("btn_turn_off"))
            self.gain_stabilizer_label.setText(_t("status_on"))
            self.gain_stabilizer_label.setStyleSheet('background-color:#b8e994; color:#000000;')
        else:
            self.gain_stabilizer_btn.setText(_t("btn_turn_on"))
            self.gain_stabilizer_label.setText(_t("status_off"))
            self.gain_stabilizer_label.setStyleSheet('background-color:#ffcccc; color:#000000;')
        
        # Update client selection combo box —— 仅当客户端集合变化时才重建，
        # 避免每个数据包都 clear()+重建下拉框造成卡顿/闪烁
        current_ids = tuple(self.get_available_clients())
        if current_ids != self._last_client_ids:
            self._last_client_ids = current_ids
            self.update_client_selection_combo()
    
    def update_auto_save_counter_label(self):
        """更新自动保存计数器标签"""
        if hasattr(self, 'auto_save_counter_label'):
            self.auto_save_counter_label.setText(_t("set_auto_saves_count", count=self.auto_save_counter))
    
    def set_hv_off(self):
        if self.set_operation_mode('STANDBY'):
            pass
            #self.standby_btn.setStyleSheet("QPushButton { background-color: #ffcccc; }")
    def save_settings(self):
        #port = self.port_combo.currentText()
        hv = self._read_spinbox_value(self.hv_spin, self.hv_spin.value())
        thr = self._read_spinbox_value(self.threshold_spin, self.threshold_spin.value())
        try:
            self.hv_spin.setValue(float(hv))
        except Exception:
            pass
        try:
            self.threshold_spin.setValue(int(thr))
        except Exception:
            pass
        self.config.update_settings(hv=hv, threshold=thr)
        self.config.save_settings()
            
    def initialize_worker(self):
        """Initialize the appropriate worker based on configuration"""
        if self.config.tcp_enabled:
            if getattr(self.config, "tcp_multi_port", False):
                self.worker = MultiPortTcpPacketWorker()
                self.log("TCP multi-port mode enabled (master + probe listeners)", "INFO")
            else:
                self.worker = TcpPacketWorker()
                self.log("TCP/IP mode enabled", 'INFO')
        else:
            # Use serial worker
            self.worker = SerialPacketWorker()
            self.log("Serial mode enabled", 'INFO')
    
    def ensure_connection_ready(self):
        """Ensure connection is ready (serial or TCP)"""
        self.save_settings()
        
        if self.config.tcp_enabled:
            # TCP mode - always server mode
            if is_tcp_worker(self.worker):
                if not self.worker.is_tcp_ready():
                    # Always connect as server
                    return self.worker.connect_tcp(
                        self.config.tcp_host, 
                        self.config.tcp_port, 
                        "server"
                    )
                return True
            else:
                # Worker type mismatch, reinitialize
                self._detach_read_timer_to_gui_thread()
                self.initialize_worker()
                if self.worker:
                    self.worker.moveToThread(self.worker_thread)
                    self._bind_read_timer_to_worker()
                return False
        else:
            # Serial mode
            if isinstance(self.worker, SerialPacketWorker):
                if not self.worker.is_serial_ready():
                    return self.worker.connect_serial(self.config.device, self.config.baudrate)
                return True
            else:
                # Worker type mismatch, reinitialize
                self._detach_read_timer_to_gui_thread()
                self.initialize_worker()
                if self.worker:
                    self.worker.moveToThread(self.worker_thread)
                    self._bind_read_timer_to_worker()
                return False

    def _qtimer_invoke(self, timer: QTimer, method: str, *, blocking: bool = False) -> None:
        """QTimer start/stop 必须在 timer 所在线程执行，否则 Qt 报 killTimer 跨线程。"""
        if timer is None:
            return
        if timer.thread() is QThread.currentThread():
            getattr(timer, method)()
            return
        conn = Qt.BlockingQueuedConnection if blocking else Qt.QueuedConnection
        if not QMetaObject.invokeMethod(timer, method, conn):
            if method == "stop":
                try:
                    timer.stop()
                except Exception:
                    pass
    
    def _bind_read_timer_to_worker(self):
        """TCP read timer on worker thread so Excel/UI stalls do not stop recv."""
        if self._read_timer_bound or self.worker is None:
            return
        if self.read_timer.thread() is not QThread.currentThread():
            self._detach_read_timer_to_gui_thread()
        try:
            self.read_timer.setInterval(10)
            try:
                self.read_timer.timeout.disconnect()
            except TypeError:
                pass
            if is_tcp_worker(self.worker):
                self.read_timer.timeout.connect(
                    self.worker.read_tcp_loop, Qt.DirectConnection
                )
            elif isinstance(self.worker, SerialPacketWorker):
                self.read_timer.timeout.connect(
                    self.worker.read_serial_loop, Qt.DirectConnection
                )
            self.read_timer.moveToThread(self.worker_thread)
            self._read_timer_bound = True
        except Exception as e:
            self.log("Failed to bind read timer to worker thread: %s" % e, "WARNING")

    def _start_read_timer(self):
        if self.worker is None:
            return
        if not self._read_timer_bound:
            self._bind_read_timer_to_worker()
        if not self.read_timer.isActive():
            self._qtimer_invoke(self.read_timer, "start", blocking=False)

    def _stop_read_timer(self):
        if not hasattr(self, "read_timer") or self.read_timer is None:
            return
        self._qtimer_invoke(self.read_timer, "stop", blocking=False)

    def _stop_read_timer_sync(self):
        """退出 / TCP reinit 前同步停表，避免 Queued stop 未完成就析构 worker。"""
        if not hasattr(self, "read_timer") or self.read_timer is None:
            return
        self._qtimer_invoke(self.read_timer, "stop", blocking=True)

    def _detach_read_timer_to_gui_thread(self):
        """Stop read loop timer and allocate a fresh QTimer (avoid illegal moveToThread)."""
        old_timer = getattr(self, "read_timer", None)
        if old_timer is not None:
            gui = QThread.currentThread()
            owner = old_timer.thread()
            if owner is not gui:
                self._qtimer_invoke(old_timer, "stop", blocking=True)
                self._qtimer_invoke(old_timer, "deleteLater", blocking=True)
            else:
                old_timer.stop()
                try:
                    old_timer.timeout.disconnect()
                except TypeError:
                    pass
                old_timer.deleteLater()
        self.read_timer = QTimer()
        self._read_timer_bound = False

    def _shutdown_tcp_worker_blocking(self, worker):
        """Close sockets and stop read loop on worker thread (fixes WinError 10038 / timer races)."""
        if worker is None:
            return
        self._stop_read_timer_sync()
        self._detach_read_timer_to_gui_thread()
        if not is_tcp_worker(worker):
            try:
                worker.stop_reading()
            except Exception:
                pass
            return
        if QThread.currentThread() is self.worker_thread:
            worker.shutdown_tcp_io()
            return
        if not hasattr(worker, "shutdown_tcp_io"):
            worker.stop_reading()
            worker.disconnect_tcp()
            return
        ok = QMetaObject.invokeMethod(
            worker, "shutdown_tcp_io", Qt.BlockingQueuedConnection
        )
        if not ok:
            worker.stop_reading()
            worker.disconnect_tcp()

    def _reset_master_link_state_for_tcp_reinit(self):
        """Avoid stale L2 timestamps causing M102 right after port/mode rebind."""
        self._last_any_master_at = 0.0
        self._last_sane_master_at = 0.0
        self._master_timeout_pending_since = 0.0
        self.master_client_id = None
        self.latest_master_summary = None
        worker = getattr(self, "worker", None)
        if worker is not None:
            try:
                worker.master_client_id = None
            except Exception:
                pass
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None:
            return
        from core.diagnostics import FaultCode

        for code in (
            FaultCode.M101,
            FaultCode.M102,
            FaultCode.M103,
            FaultCode.M104,
        ):
            dm.remove_fault("master", code)

    def _queue_worker_delete(self, worker):
        if worker is None:
            return
        try:
            if QThread.currentThread() is self.worker_thread:
                worker.deleteLater()
            else:
                QMetaObject.invokeMethod(worker, "deleteLater", Qt.QueuedConnection)
        except (RuntimeError, AttributeError):
            pass
    
    def ensure_serial_ready(self):
        """Backward compatibility method"""
        return self.ensure_connection_ready()


    
    def is_acq_hold_locked(self) -> bool:
        return bool(getattr(self, "_acq_hold_lock", False))

    def set_acq_hold_lock(self, locked: bool):
        self._acq_hold_lock = bool(locked)

    def release_acq_hold_lock(self, resume=True):
        """退出检修会话时解除停采锁；resume 时若已连接则恢复自动开采。"""
        was_locked = self.is_acq_hold_locked()
        self._acq_hold_lock = False
        if not was_locked:
            return False
        self.log("Maintenance acquisition hold released", "INFO")
        if resume and not self.is_acquiring:
            try:
                if self.ensure_connection_ready():
                    self.start_acquisition()
            except Exception as e:
                self.log("Resume acquisition after hold release failed: %s" % e, "WARNING")
        return True

    def _ensure_tcp_link_layer(self):
        """Keep TCP accept/recv running even when not accumulating (listen or hold)."""
        if not is_tcp_worker(self.worker):
            return
        if not self.worker.is_tcp_ready():
            return
        if not getattr(self.worker, "is_running", False):
            self.worker.start_reading()
        self._start_read_timer()

    def start_acquisition(self, from_auto=False):
        if from_auto and self.is_acq_hold_locked():
            self.log("Auto-start skipped: maintenance acquisition hold", "DEBUG")
            return False
        if from_auto and getattr(self, "_acq_user_stopped", False):
            self.log("Auto-start skipped: user stopped acquisition (monitor only)", "DEBUG")
            return False
        if self.ensure_connection_ready():
            self._acq_hold_lock = False
            self._acq_user_stopped = False
            # 先打采集时间戳并清故障表，避免同 tick 内 _sync_probe_count_fault 误报 E103
            self.diagnostics_manager.start_acquisition()
            self.is_acquiring = True
            self._start_read_timer()
            
            # 延迟启动数据读取，让UI先响应
            QTimer.singleShot(100, lambda: self._delayed_start_reading())
            self.last_auto_save_time = time.time()
            self.set_status_label('Starting acquisition...', True)
            
            # 重置数据状态，准备接收新数据（但不清除客户端选择）
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.client_data = {}
            # 保留client_time_series和client_spectrum_data，不清除历史数据
            # 只重置显示数据
            self.spectrum_data = np.zeros(self.config.adc_channels)
            self.total_count_rate = 0
            
            # 如果有数据更新回调，通知UI重置
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, {})
            
            return True
        else:
            self.log("Failed to ensure connection ready", 'WARNING')
            return False
    
    def _delayed_start_reading(self):
        """延迟启动数据读取，减少UI卡顿"""
        if not self.is_acquiring:
            return
        if self.worker:
            self.worker.start_reading()
            self.set_status_label('Running ...', True)
            self.log("Acquisition started", 'INFO')

    def _clear_acquisition_memory(self):
        self.reset_plots()
        self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
        self.client_data = {}
        self.client_time_series = {}
        self.client_spectrum_data = {}
        self.client_archive_time_series = {}
        self.client_segment_spectrum = {}
        self.client_latest_packets = {}
        self.primary_client_id = None
        self.total_count_rate = 0
        self.spectrum_data = np.zeros(self.config.adc_channels)
        if self.data_updated_callback is not None:
            self.data_updated_callback(self.current_stat, 0, {})

    def stop_acquisition(self, hold=False, clear_memory=None, user_initiated=True):
        """Stop accumulating/saving. TCP 监视链路保持，总览 CPS 继续刷新（除非 clear_memory）。"""
        if hold:
            self._acq_hold_lock = True
        if clear_memory is None:
            # 停止采集 ≠ 清空总览；仅「清空数据」或显式传 True 才清内存
            clear_memory = False
        if self.is_acquiring:
            # 停止前先落盘一次，避免随后清内存导致只能导出空文件
            try:
                if self.auto_save_enabled:
                    self._auto_save_all_clients(force=True, blocking=True)
            except Exception as e:
                self.log(f"Final auto-save before stop failed: {e}", 'WARNING')

            if self.config.tcp_enabled and is_tcp_worker(getattr(self, "worker", None)):
                # 与检修停采一致：不断 TCP accept/recv，避免总览探头整片消失
                self._ensure_tcp_link_layer()
            elif not hold:
                self.worker.stop_reading()
                self._stop_read_timer()
            else:
                self._ensure_tcp_link_layer()

            if not hold and self.raw_logger:
                self.raw_logger.stop()

            self.is_acquiring = False
            self.diagnostics_manager.stop_acquisition()
            if user_initiated and not hold:
                self._acq_user_stopped = True

            if clear_memory:
                self._clear_acquisition_memory()

            self.set_status_label('Held.' if hold else 'Stopped.', False)

            if hold and user_initiated:
                self._acq_user_stopped = True
                self.log("Acquisition held by maintenance (auto-start suppressed; link stays up)", "INFO")
            elif self.config.tcp_enabled:
                self.log(
                    "Acquisition stopped; TCP monitor kept (overview CPS still updates)",
                    "INFO",
                )


    
    def save_data(self, auto_save=False, auto_save_path=""):
        # 权限检查在 MainWindow.save_data；这里只写盘。
        if auto_save:
            # 自动保存：每路探头各写一份
            self._auto_save_all_clients(force=bool(auto_save_path))
            return

        is_tcp_mode = bool(self.config.tcp_enabled)
        client_id = self._manual_save_client_id()
        if not client_id:
            QMessageBox.warning(
                self, _t("msg_no_client_data_title"), _t("msg_save_select_probe")
            )
            return
        
        ts = self.client_time_series.get(client_id) or []
        spec = self.client_spectrum_data.get(client_id)
        has_spec = spec is not None and np.sum(spec) > 0
        if not ts and not has_spec:
            QMessageBox.warning(self, _t("msg_no_data_title"), _t("msg_no_data_text"))
            return
            
        label = self._export_probe_label(client_id, 0)
        meta = self._export_probe_meta(client_id)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        default_filename = "rayzen_spectrometer_data_%s.xlsx" % (
            self._export_file_stem(client_id, timestamp)
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            _t("dlg_save_data_for", client=label),
            default_filename,
            "Excel Files (*.xlsx);;All Files (*)",
        )
        if not filename:
            return
        try:
            n_ts, spec_sum, size = self._write_client_excel(filename, client_id, is_tcp_mode)
            loc = meta.get("location") or ""
            ident = "%s %s" % (label, loc) if loc else label
            self.log(
                "Data saved to %s (probe=%s, ip=%s, points=%d, spectrum_sum=%.1f, bytes=%d)"
                % (filename, ident.strip(), meta.get("ip") or "-", n_ts, spec_sum, size),
                "INFO",
            )
            if hasattr(self, "log_output") and self.log_output is not None:
                self.log_output.append(
                    "<span style='color: green;'>Data saved to %s (%s)</span>"
                    % (filename, label)
                )
        except Exception as e:
            self.log("Save error: %s" % e, "ERROR")
            if hasattr(self, "log_output") and self.log_output is not None:
                self.log_output.append(
                    "<span style='color: red;'>Save error: %s</span>" % e
                )

    def _manual_save_client_id(self):
        """Manual export follows the probe currently selected on Overview/Spectrum."""
        master = getattr(self, "master_client_id", None)
        cid = getattr(self, "primary_client_id", None)
        if cid and cid != master and cid not in ("system", "master"):
            return cid
        if not bool(getattr(self.config, "tcp_enabled", False)):
            if "serial_client" in (self.client_time_series or {}):
                return "serial_client"
            ids = self._clients_with_saveable_data()
            return ids[0] if ids else None
        return None
    
    def _export_fs_token(self, text: str) -> str:
        s = str(text or "").replace("·", "-").replace(" ", "")
        out = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in s)
        while "__" in out:
            out = out.replace("__", "_")
        return out.strip("._") or ""

    def _export_probe_location(self, client_id: str) -> str:
        """Resolve display-slot location for this TCP client. Do not guess by 1号→槽位0."""
        sources = []
        home = getattr(self, "home_page", None)
        if home is not None:
            sources.append((home, list(getattr(home, "_probe_entries", None) or [])))
        cr = getattr(self, "control_room_page", None)
        if cr is not None:
            sources.append((cr, list(getattr(cr, "_probe_entries", None) or [])))
        for owner, entries in sources:
            for i, entry in enumerate(entries):
                if str(entry.get("client_id") or "") != str(client_id or ""):
                    continue
                loc = str(entry.get("location") or "").strip()
                if loc:
                    return loc
                if owner is not None and hasattr(owner, "_slot_location"):
                    try:
                        loc = str(owner._slot_location(i) or "").strip()
                        if loc:
                            return loc
                    except Exception:
                        pass
                elif home is not None and hasattr(home, "_slot_location"):
                    try:
                        loc = str(home._slot_location(i) or "").strip()
                        if loc:
                            return loc
                    except Exception:
                        pass
        return ""

    def _export_probe_meta(self, client_id: str) -> dict:
        """Human identity for files/logs: 1号 + 左侧-上 + IP."""
        label = self._export_probe_label(client_id, 0)
        ip = ""
        if hasattr(self, "_extract_client_ip"):
            ip = str(self._extract_client_ip(client_id) or "")
        loc = self._export_probe_location(client_id)
        product_id = ""
        info = (getattr(self, "client_data", None) or {}).get(client_id) or {}
        if info.get("product_id") not in (None, "", "--"):
            product_id = str(info.get("product_id"))
        return {
            "label": label,
            "location": loc,
            "ip": ip,
            "product_id": product_id,
            "client_id": client_id,
        }

    def _export_file_stem(self, client_id: str, timestamp: str) -> str:
        meta = self._export_probe_meta(client_id)
        parts = [
            self._export_fs_token(meta.get("label")),
            self._export_fs_token(meta.get("location")),
            self._export_endpoint_tag(client_id) or self._export_fs_token(meta.get("ip")),
            str(timestamp or ""),
        ]
        return "_".join(p for p in parts if p)

    def _export_endpoint_tag(self, client_id: str) -> str:
        """IP or IP_port from client_id, unique when two sockets share a host."""
        cid = str(client_id or "")
        if not cid or cid in ("system", "master", "serial_client"):
            return self._export_fs_token(cid)
        tail = cid.split("_")[-1] if "_" in cid else cid
        return self._export_fs_token(tail.replace(":", "_"))

    def _export_client_tag(self, client_id: str) -> str:
        tag = self._export_endpoint_tag(client_id)
        if tag:
            return tag
        ip = ""
        if hasattr(self, "_extract_client_ip"):
            ip = self._extract_client_ip(client_id) or ""
        if ip:
            return self._export_fs_token(ip.replace(":", "_"))
        return self._export_fs_token(str(client_id or "probe"))

    def _export_probe_label(self, client_id: str, index: int) -> str:
        label = ""
        if hasattr(self, "get_probe_label"):
            try:
                label = str(self.get_probe_label(client_id) or "").strip()
            except Exception:
                label = ""
        if label:
            return label
        ip = ""
        if hasattr(self, "_extract_client_ip"):
            ip = str(self._extract_client_ip(client_id) or "").strip()
        if ip and ip not in ("serial",):
            return ip
        tag = self._export_endpoint_tag(client_id)
        if tag:
            return tag
        try:
            from core.translation import _t
            return _t("probe_slot_name", n=index + 1)
        except Exception:
            return "Probe %d" % (index + 1)

    def _ensure_autosave_buffers(self, client_id, adc_channels: int):
        if client_id not in self.client_archive_time_series:
            self.client_archive_time_series[client_id] = []
        if client_id not in self.client_segment_spectrum:
            self.client_segment_spectrum[client_id] = np.zeros(int(adc_channels))

    def _clear_autosave_segments(self, client_ids):
        for cid in client_ids or []:
            if cid in self.client_archive_time_series:
                self.client_archive_time_series[cid] = []
            if cid in self.client_segment_spectrum:
                self.client_segment_spectrum[cid][:] = 0

    def _clients_with_saveable_archive(self):
        """Probe clients with pending segment data for auto-save."""
        ids = set(self.client_archive_time_series.keys()) | set(
            self.client_segment_spectrum.keys()
        )
        master = getattr(self, "master_client_id", None)
        result = []
        for cid in ids:
            if not cid or cid in ("system", "master") or (master and cid == master):
                continue
            ts = self.client_archive_time_series.get(cid) or []
            spec = self.client_segment_spectrum.get(cid)
            has_ts = len(ts) > 0
            has_spec = spec is not None and np.sum(spec) > 0
            if has_ts or has_spec:
                result.append(cid)
        result.sort(key=lambda c: (self._export_probe_label(c, 0), c))
        return result

    def _clients_with_saveable_data(self):
        """Return probe client_ids that have non-empty time series or non-zero spectrum."""
        ids = set(self.client_time_series.keys()) | set(self.client_spectrum_data.keys())
        master = getattr(self, "master_client_id", None)
        result = []
        for cid in ids:
            if not cid or cid in ("system", "master") or (master and cid == master):
                continue
            ts = self.client_time_series.get(cid) or []
            spec = self.client_spectrum_data.get(cid)
            has_ts = len(ts) > 0
            has_spec = spec is not None and np.sum(spec) > 0
            if has_ts or has_spec:
                result.append(cid)
        result.sort(key=lambda c: (self._export_probe_label(c, 0), c))
        return result

    def _write_client_excel(self, filename, client_id_to_save, is_tcp_mode):
        """Write one client's spectrum/time-series/device info to an xlsx file."""
        spectrum_data_to_save = self.client_spectrum_data.get(
            client_id_to_save, np.zeros(self.config.adc_channels)
        )
        time_series_data = list(self.client_time_series.get(client_id_to_save, []))
        client_info = self.client_data.get(client_id_to_save, {})
        meta = self._export_probe_meta(client_id_to_save)
        probe = meta.get("label") or self._export_probe_label(client_id_to_save, 0)
        loc = meta.get("location") or ""
        ip = meta.get("ip") or ""
        spec_col = self._export_fs_token("_".join([probe, loc])) or "Spectrum"
        spec_col = "Counts_%s" % spec_col if spec_col != "Spectrum" else "Spectrum"
        df_spectrum = pd.DataFrame({
            "Channel": list(range(len(spectrum_data_to_save))),
            spec_col: spectrum_data_to_save,
        })
        ts_cols = [
            "Probe", "Location", "IP",
            "Timestamp", "Counter", "Temperature", "HV", "Spectrum_Counts",
        ]
        if time_series_data:
            timestamps, counters, temperatures, hvs, spec_counts = zip(*time_series_data)
            n = len(timestamps)
            df_time_series = pd.DataFrame({
                "Probe": [probe] * n,
                "Location": [loc] * n,
                "IP": [ip] * n,
                "Timestamp": [
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t)))
                    for t in timestamps
                ],
                "Counter": counters,
                "Temperature": temperatures,
                "HV": hvs,
                "Spectrum_Counts": spec_counts,
            })
        else:
            df_time_series = pd.DataFrame(columns=ts_cols)
                
        df_client_info = pd.DataFrame({
            "Probe": [probe],
            "Location": [loc or "--"],
            "IP": [ip or "--"],
            "Mode": ["TCP" if is_tcp_mode else "Serial"],
            "Client_ID": [client_id_to_save],
            "Product_ID": [client_info.get("product_id", "--")],
            "Sensitivity": [client_info.get("sensitivity", "--")],
            "Save_Time": [time.strftime("%Y-%m-%d %H:%M:%S")],
            "TimeSeries_Points": [len(time_series_data)],
            "Spectrum_Sum": [float(np.sum(spectrum_data_to_save))],
        })

        from core.excel_io import write_excel_atomic

        def _write(tmp: str):
            with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
                df_spectrum.to_excel(writer, sheet_name='Spectrum', index=False)
                df_time_series.to_excel(writer, sheet_name='TimeSeries', index=False)
                df_client_info.to_excel(writer, sheet_name='DeviceInfo', index=False)
                
        size = write_excel_atomic(filename, _write, min_bytes=200)
        return len(time_series_data), float(np.sum(spectrum_data_to_save)), size

    def _wait_autosave_worker(self, timeout: float = 120.0) -> bool:
        """Wait for a background autosave thread. Apply its result on this thread
        so queued finished_ok cannot double-clear segments after a later save."""
        worker = getattr(self, "_autosave_worker", None)
        if worker is None:
            self._autosave_running = False
            return True
        if worker.isRunning():
            finished = worker.wait(int(max(1.0, float(timeout)) * 1000))
            if not finished:
                self.log("Auto-save worker still running after wait timeout", "WARNING")
                return False
        try:
            worker.finished_ok.disconnect(self._on_autosave_worker_done)
        except (TypeError, RuntimeError):
            pass
        result = getattr(worker, "result", None)
        if result is not None and getattr(self, "_autosave_running", False):
            self._on_autosave_worker_done(*result)
        else:
            self._autosave_running = False
            self._autosave_worker = None
        return True

    def _archive_settings(self):
        return {
            "archive_enabled": bool(getattr(self.config, "archive_enabled", False)),
            "archive_path": getattr(self.config, "archive_path", "") or "",
            "site_id": getattr(self.config, "archive_site_id", "") or "",
            "machine_id": getattr(self.config, "archive_machine_id", "") or "",
        }

    def _build_autosave_jobs(self, timestamp: str, save_dir: str):
        """Snapshot segment archive on UI thread (since last auto-save)."""
        clients = self._clients_with_saveable_archive()
        if not clients:
            return []
        os.makedirs(save_dir, exist_ok=True)
        is_tcp_mode = bool(self.config.tcp_enabled)
        jobs = []
        for client_id in clients:
            stem = self._export_file_stem(client_id, timestamp)
            filename = os.path.join(save_dir, "data_auto_%s.xlsx" % stem)
            if os.path.exists(filename):
                filename = os.path.join(
                    save_dir,
                    "data_auto_%s_%s.xlsx" % (stem, self._export_client_tag(client_id)),
                )
            spec = self.client_segment_spectrum.get(client_id)
            if spec is None:
                spec_copy = np.zeros(self.config.adc_channels)
            else:
                spec_copy = np.array(spec, copy=True)
                spec[:] = 0
            ts_copy = list(self.client_archive_time_series.get(client_id, []))
            self.client_archive_time_series[client_id] = []
            meta = self._export_probe_meta(client_id)
            ident = " ".join(
                p for p in (meta.get("label"), meta.get("location")) if p
            ) or client_id
            jobs.append({
                "filename": filename,
                "client_id": client_id,
                "spectrum": spec_copy,
                "time_series": ts_copy,
                "client_info": dict(self.client_data.get(client_id, {}) or {}),
                "meta": dict(meta),
                "ident": ident,
                "is_tcp_mode": is_tcp_mode,
                "spectrum_kind": "segment",
                "archive_settings": self._archive_settings(),
            })
        return jobs

    def _restore_failed_autosave_segments(self, jobs, saved_cids):
        """写盘失败的路把快照拼回当前缓冲，避免丢掉保存期间新到的谱。"""
        saved = set(cid for cid in (saved_cids or []) if cid)
        for job in jobs or []:
            cid = job.get("client_id")
            if not cid or cid in saved:
                continue
            spec = np.asarray(job.get("spectrum"), dtype=float)
            ts = list(job.get("time_series") or [])
            nchan = int(spec.size) if spec is not None and spec.size else int(self.config.adc_channels)
            self._ensure_autosave_buffers(cid, nchan)
            cur = self.client_segment_spectrum.get(cid)
            if spec is not None and spec.size:
                if cur is None or getattr(cur, "shape", None) != spec.shape:
                    self.client_segment_spectrum[cid] = np.array(spec, copy=True)
                else:
                    self.client_segment_spectrum[cid] = spec + cur
            if ts:
                self.client_archive_time_series[cid] = ts + list(
                    self.client_archive_time_series.get(cid) or []
                )

    def _on_autosave_worker_done(self, saved: int, logs, saved_cids=None):
        self._autosave_running = False
        self._autosave_worker = None
        for msg, level in list(logs or []):
            self.log(msg, level)
        jobs = getattr(self, "_autosave_snapshot_jobs", None)
        self._restore_failed_autosave_segments(jobs, saved_cids)
        self._autosave_snapshot_jobs = None
        self._last_autosave_client_ids = []
        if int(saved or 0) > 0:
            self.auto_save_counter += int(saved)
            self.last_auto_save_time = time.time()
            self.update_auto_save_counter_label()

    def _auto_save_all_clients(self, force=False, blocking=False):
        """Save every client that has real data. Default: background thread."""
        if blocking:
            if not self._wait_autosave_worker():
                self.log("Auto-save blocked: previous worker still running", "WARNING")
                return 0
        elif self._autosave_running:
            self.log("Auto-save skipped: previous run still in progress", "DEBUG")
            return 0
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        if self.auto_save_path:
            save_dir = self.auto_save_path
        else:
            save_dir = os.path.join(os.path.expanduser("~"), "Raysen", "AutoSave")

        jobs = self._build_autosave_jobs(timestamp, save_dir)
        if not jobs:
            self.log("Auto-save skipped: no pending segment data", "INFO")
            return 0
        self._autosave_snapshot_jobs = jobs
        self._last_autosave_client_ids = [j.get("client_id") for j in jobs if j.get("client_id")]

        dm = getattr(self, "diagnostics_manager", None)
        if dm is not None and hasattr(dm, "defer_comm_timeouts"):
            # 写盘期间 + 主线程消化积压包：暂缓 E102/M102
            dm.defer_comm_timeouts(max(20.0, 5.0 + 3.0 * len(jobs)))

        if blocking:
            from core.autosave_worker import write_autosave_job
            saved = 0
            saved_ids = []
            for job in jobs:
                try:
                    n_ts, spec_sum, size = write_autosave_job(job)
                    self.log(
                        "Auto-saved %s (probe=%s, points=%d, spectrum_sum=%.1f, bytes=%d)"
                        % (job["filename"], job.get("ident"), n_ts, spec_sum, size),
                        "INFO",
                    )
                    try:
                        from core.archive_manager import archive_file

                        archive = archive_file(
                            job.get("filename"),
                            "AutoSave",
                            metadata={
                                "client_id": job.get("client_id"),
                                "probe": job.get("ident"),
                                "time_series_points": n_ts,
                                "spectrum_sum": spec_sum,
                                "spectrum_kind": job.get("spectrum_kind") or "segment",
                            },
                            settings=job.get("archive_settings") or {},
                        )
                        if archive.get("archive_status") == "archived":
                            self.log(
                                "Archived %s -> %s"
                                % (job.get("filename"), archive.get("archive_path")),
                                "INFO",
                            )
                        elif archive.get("archive_status") == "failed":
                            self.log(
                                "Archive failed for %s: %s"
                                % (job.get("filename"), archive.get("error") or archive.get("manifest_error")),
                                "WARNING",
                            )
                    except Exception as e:
                        self.log("Archive record failed for %s: %s" % (job.get("filename"), e), "WARNING")
                    saved += 1
                    self.auto_save_counter += 1
                    cid = job.get("client_id")
                    if cid:
                        saved_ids.append(cid)
                except Exception as e:
                    self.log("Auto-save failed for %s: %s" % (job.get("client_id"), e), "ERROR")
            self._restore_failed_autosave_segments(jobs, saved_ids)
            self._autosave_snapshot_jobs = None
            self._last_autosave_client_ids = []
            if saved:
                self.last_auto_save_time = time.time()
                self.update_auto_save_counter_label()
            return saved

        self._autosave_running = True
        worker = AutoSaveWorker(jobs)
        worker.finished_ok.connect(self._on_autosave_worker_done)
        worker.finished.connect(worker.deleteLater)
        self._autosave_worker = worker
        worker.start()
        return len(jobs)

    def auto_save_data(self):
        """自动保存数据（后台线程写 Excel，不阻塞 TCP/界面）。"""
        if not self.auto_save_enabled:
            self.log("Auto-save is disabled, skipping", 'DEBUG')
            return

        if not getattr(self, 'is_acquiring', False):
            self.log("Auto-save skipped: acquisition not running", 'DEBUG')
            return

        if self._autosave_running:
            self.log("Auto-save skipped: previous run still in progress", 'DEBUG')
            return

        current_time = time.time()
        if self.last_auto_save_time <= 0:
            self.last_auto_save_time = current_time
        time_since_last_save = current_time - self.last_auto_save_time
        if time_since_last_save < self.auto_save_interval:
            self.log(
                f"Auto-save not triggered yet. Need {self.auto_save_interval - time_since_last_save:.1f} more seconds",
                'DEBUG'
            )
            return

        try:
            self.log(f"Auto-save triggered after {time_since_last_save:.1f}s", 'INFO')
            self._auto_save_all_clients(force=False, blocking=False)
        except Exception as e:
            self._autosave_running = False
            self.log(f"Auto-save error: {str(e)}", 'ERROR')
            import traceback
            self.log(f"Auto-save traceback: {traceback.format_exc()}", 'ERROR')
    
    def toggle_virtual_keyboard(self, state):
        """切换虚拟键盘自动触发开关（写入设置，电脑/工控可手动覆盖自动检测）。"""
        from core.translation import _t
        enabled = state == Qt.Checked
        self.focus_filter.keyboard_enabled = enabled
        try:
            from PyQt5.QtCore import QSettings
            QSettings("Raysen", "Spectrometer").setValue(
                "SOFTWARE_KEYBOARD_ENABLED", bool(enabled)
            )
        except Exception:
            pass

        if hasattr(self, 'keyboard_status_label'):
            if enabled:
                self.keyboard_status_label.setText(_t("status_enabled"))
                self.keyboard_status_label.setStyleSheet("color: green;")
                self.log("Virtual keyboard auto-trigger enabled", 'INFO')
            else:
                self.keyboard_status_label.setText(_t("status_disabled"))
                self.keyboard_status_label.setStyleSheet("color: gray;")
                self.log("Virtual keyboard auto-trigger disabled", 'INFO')

    def toggle_auto_save(self, state):
        """切换自动保存开关"""
        enabled = state == Qt.Checked
        self.auto_save_enabled = enabled
        
        # 启用/禁用路径控件
        self.auto_save_path_input.setEnabled(enabled)
        self.auto_save_path_btn.setEnabled(enabled)
        
        if enabled:
            # 启动自动保存定时器
            self.auto_save_timer.start(self.auto_save_interval * 1000)  # 转换为毫秒
            self.log(f"Auto-save enabled, will save every {self.auto_save_interval} seconds", 'INFO')
        else:
            # 停止自动保存定时器
            self.auto_save_timer.stop()
            self.log("Auto-save disabled", 'INFO')
        
        # 更新计数器标签
        self.update_auto_save_counter_label()
    
    
    def set_auto_save_interval(self, interval):
        """设置自动保存间隔"""
        if interval < 60:  # 最小1分钟
            interval = 60
        elif interval > 86400:  # 最大1天
            interval = 86400
        
        self.auto_save_interval = interval
        
        # 更新时间单位显示标签
        self.update_auto_save_interval_label(interval)
        
        # 如果定时器正在运行，重新启动
        if self.auto_save_timer.isActive():
            self.auto_save_timer.stop()
            self.auto_save_timer.start(interval * 1000)
        
        self.log(f"Auto-save interval set to {interval} seconds ({self.format_time_interval(interval)})", 'INFO')
    
    def update_auto_save_interval_label(self, interval):
        """更新自动保存间隔标签显示"""
        if hasattr(self, 'auto_save_interval_label'):
            formatted_time = self.format_time_interval(interval)
            self.auto_save_interval_label.setText(f"({formatted_time})")

    def _setup_data_retention_timers(self):
        self._retention_midnight_timer = QTimer()
        self._retention_midnight_timer.setSingleShot(True)
        self._retention_midnight_timer.timeout.connect(self._run_retention_cleanup)
        self._schedule_next_retention_cleanup()

    def _schedule_next_retention_cleanup(self):
        now = time.time()
        lt = time.localtime(now)
        next_midnight = datetime(lt.tm_year, lt.tm_mon, lt.tm_mday) + timedelta(days=1)
        delay_ms = max(1000, int((next_midnight.timestamp() - now) * 1000))
        self._retention_midnight_timer.start(delay_ms)

    def _run_retention_cleanup(self):
        try:
            from pathlib import Path
            from core.data_retention import run_retention_cleanup, raysen_root

            extra = None
            lp = (getattr(self, "log_file_path", None) or "").strip()
            if lp:
                extra = Path(lp).parent
            result = run_retention_cleanup(extra_raw_dir=extra)
            root = raysen_root()
            root.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            summary = (
                "%s retention keep_days=%s deleted=%s dry_run=%s\n"
                % (stamp, result.get("keep_days"), result.get("deleted"), result.get("dry_run"))
            )
            log_path = root / "cleanup.log"
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(summary)
                for line in list(result.get("lines") or [])[:200]:
                    fh.write("  %s\n" % line)
            deleted = int(result.get("deleted") or 0)
            if deleted:
                self.log(
                    "Data retention: removed %d file(s), keep %s day(s) — see %s"
                    % (deleted, result.get("keep_days"), log_path),
                    "INFO",
                )
        except Exception as e:
            self.log("Data retention cleanup failed: %s" % e, "WARNING")
        finally:
            self._schedule_next_retention_cleanup()
    
    def format_time_interval(self, seconds):
        """格式化时间间隔为可读格式（随当前语言切换）"""
        if seconds < 60:
            return _t("time_seconds", n=seconds)
        elif seconds < 3600:  # 小于1小时
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return _t("time_min_sec", m=minutes, s=remaining_seconds)
            else:
                return _t("time_minutes", n=minutes)
        elif seconds < 86400:  # 小于1天
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return _t("time_hour_min", h=hours, m=remaining_minutes)
            else:
                return _t("time_hours", n=hours)
        else:  # 1天或以上
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours > 0:
                return _t("time_day_hour", d=days, h=remaining_hours)
            else:
                return _t("time_days", n=days)
    
    def select_auto_save_path(self):
        """选择自动保存路径"""
        path = QFileDialog.getExistingDirectory(
            self,
            _t("dlg_select_autosave_folder"),
            self.auto_save_path or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontUseNativeDialog
        )
        if path:
            self.auto_save_path = path
            self.auto_save_path_input.setText(path)
            self.log(f"Auto-save path set to: {path}", 'INFO')
        
    def refresh_software_version_labels(self):
        from core.translation import _t, TranslationManager
        from core.app_version import software_version_display, software_version_short

        lang = TranslationManager().get_language()
        multi = bool(getattr(self.config, "tcp_multi_port", False))
        if hasattr(self, "version_group"):
            self.version_group.setTitle(_t("set_version_info"))
        if hasattr(self, "software_version_title_label"):
            self.software_version_title_label.setText(_t("set_software_version"))
            self.software_version_title_label.setToolTip(_t("tip_software_version"))
        if hasattr(self, "software_version_value_label"):
            self.software_version_value_label.setText(
                software_version_display(lang, multi_port=multi)
            )
            self.software_version_value_label.setToolTip(_t("tip_software_version"))
        cr = getattr(self, "control_room_page", None)
        if cr is not None and hasattr(cr, "version_label"):
            cr.version_label.setText(
                _t("control_room_version_fmt", version=software_version_short())
            )

    def show_about(self):
        from core.translation import _t, TranslationManager
        from core.app_version import software_version_about

        lang = TranslationManager().get_language()
        title = _t("sys_title") if hasattr(self, "config") else "DAQ Tablet"
        QMessageBox.about(self, title, software_version_about(lang) + "\n© Raysen")
    
    def on_cmd_feedback_received(self, packet: CmdFeedback):
        self.packet_counts['cmd'] += 1
        status_text = "Success" if packet.status else "Failed"

        # 解析控制码对应的命令类型
        control_code_desc = self._get_control_code_description(packet.control_code)
        
        text = (f"[{self.packet_counts['cmd']:04d}] CMD Feedback - "
                f"ID: 0x{packet.id:04X}, "
                f"Timestamp: {packet.timestamp}, "
                f"Control: 0x{packet.control_code:02X} ({control_code_desc}), "
                f"Value: 0x{packet.value:02X} ({packet.value}), "
                f"Status: {status_text}")
        self.log(text)
        
        # 如果是参数设置命令且成功，添加Flash写入警告
        if packet.status == 1 and packet.control_code in [0x07, 0x08, 0x0C, 0x0E]:
            # 0x07: HV_SET_CODE, 0x08: TRIGGER_SET_CODE, 0x0C: SEN_COEF_SET_CODE, 0x0E: PRODUCT_ID_SET_CODE
            self.log(f"警告：参数设置命令 0x{packet.control_code:02X} ({control_code_desc}) 已发送成功，但Flash写入需要时间。", 'WARNING')
            self.log(f"建议：等待至少100ms后再断电，确保参数已保存到EEPROM。", 'WARNING')
            self.log(f"注意：MODBUS参数保存正常，但串口命令反馈可能发送太快，Flash还未写入完成。", 'WARNING')

        # Relay command feedback:
        # - 0x06 value = that channel's 0/1 (NOT a 3-bit mask)
        # - 0x11 / 0x12 value = actual 3-ch mask
        src = getattr(packet, "source_client_id", None)
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else None
        pending_relay_age = time.time() - float(getattr(self, "_pending_master_relay_cmd", 0) or 0)
        pending_reset_age = time.time() - float(getattr(self, "_pending_channel_reset_at", 0) or 0)
        pending_clear_mode_age = time.time() - float(
            getattr(self, "_pending_alarm_clear_mode_at", 0) or 0
        )
        pending_sensor_mode_age = time.time() - float(
            getattr(self, "_pending_sensor_mode_at", 0) or 0
        )
        from_master = bool(master_cid and src and src == master_cid)
        if not from_master and master_cid and not src:
            if (
                0 <= pending_relay_age <= 3.0
                or 0 <= pending_reset_age <= 5.0
                or 0 <= pending_clear_mode_age <= 5.0
                or 0 <= pending_sensor_mode_age <= 5.0
            ):
                from_master = True

        # 通道报警人工复位 0x15（仅主控）
        if from_master and packet.control_code == 0x15:
            if hasattr(self, "on_channel_alarm_reset_feedback"):
                self.on_channel_alarm_reset_feedback(packet)
        elif from_master and packet.control_code == 0x16:
            if hasattr(self, "on_alarm_clear_mode_feedback"):
                self.on_alarm_clear_mode_feedback(packet)
        elif from_master and packet.control_code == 0x19:
            if hasattr(self, "on_sensor_mode_feedback"):
                self.on_sensor_mode_feedback(packet)
        elif packet.control_code in (0x0C, 0x0F) and packet.status == 1:
            self._apply_sensitivity_from_feedback(packet)
        elif packet.control_code in (0x0D, 0x0E):
            if hasattr(self, "on_product_id_feedback"):
                self.on_product_id_feedback(packet)
        elif from_master and packet.control_code in (0x06, 0x11, 0x12) and hasattr(self, "master_relay_status_label"):
            if not packet.status:
                from core.translation import _t
                self.log(
                    "Master relay command failed (status=0), control=0x%02X value=0x%02X"
                    % (int(packet.control_code), int(packet.value) & 0xFF),
                    "WARNING",
                )
                self.master_relay_status_label.setText(_t("set_master_relay_fail"))
            elif packet.control_code == 0x06:
                # Single-relay ack: value is 0/1 for the commanded channel only
                rnum = getattr(self, "_pending_master_relay_num", None)
                if rnum in (0, 1, 2):
                    on = bool(int(packet.value) & 0x01)
                    self._set_master_relay_bit_ui(rnum, on)
                self._pending_master_relay_num = None
                self._pending_master_relay_cmd = 0.0
                # Optional sync of full mask (R0 etc.) — blockSignals so no re-send
                QTimer.singleShot(120, self._sync_master_relay_status_after_06)
            else:
                # 0x11 / 0x12: value is 3-ch mask
                self._apply_master_relay_mask_to_ui(int(packet.value) & 0x07)
                self._pending_master_relay_cmd = 0.0
                self._pending_master_relay_num = None

        # Probe relay 0x06/0x12 from non-master: refresh probe status label only
        elif (
            (not from_master)
            and packet.control_code in (0x06, 0x11, 0x12)
            and packet.status
            and hasattr(self, "relay_status_label")
        ):
            if packet.control_code in (0x11, 0x12):
                mask = int(packet.value) & 0x07
                r0 = bool(mask & 0x01)
                r1 = bool(mask & 0x02)
                r2 = bool(mask & 0x04)
                self.relay_states = (r0, r1, r2)
                from core.translation import _t
                self.relay_status_label.setText(
                    _t("relay_status_format", r0=int(r0), r1=int(r1), r2=int(r2))
                )
                for cb, st in (
                    (self.relay0_checkbox, r0),
                    (self.relay1_checkbox, r1),
                    (self.relay2_checkbox, r2),
                ):
                    cb.blockSignals(True)
                    cb.setChecked(st)
                    cb.blockSignals(False)
            self._pending_probe_relay_cmd = 0.0

    def on_dev_message_received(self, packet: DevMessage):
        self.packet_counts['dev_msg'] += 1
        if packet.message_type==1:
            msg=f'Gain stabilizer changed HV to: {packet.value/100.}'
        elif packet.message_type ==2:
            msg=f'Gain stabilizer status changed to {packet.value}'
        elif packet.message_type ==3:
            msg=f'Reference temperature set to to {packet.value/100.}'

        text = f"[{self.packet_counts['dev_msg']:04d}] Message From Device- {msg}"
        self.log(text)

    
    def on_spectrum_packet_received(self, packet: SpectrumPacket, client_id: str = None):
        self.packet_counts['spectrum'] += 1

        self.current_signal_source='internal' if (packet.device_status & 0b01) == 1 else 'external'

        # Update gain stabilizer flag from packet if we're not waiting for confirmation
        gain_stabilizer_bit = (packet.device_status >> 3) & 0x1
        if not self.gain_stabilizer_pending:
            old_flag = self.gain_stabilizer_flag
            self.gain_stabilizer_flag = gain_stabilizer_bit
            # Only log if gain stabilizer status actually changed
            if old_flag != self.gain_stabilizer_flag:
                self.log(f"Gain stabilizer flag updated from {old_flag} to {self.gain_stabilizer_flag}", 'INFO')
        else:
            # Clear pending flag after first spectrum packet
            self.gain_stabilizer_pending = False
            
        self.update_control_labels()

        spectrum= np.array(packet.ADC)

        # Store data in client-specific time series
        # For serial mode (client_id is None), use a special client ID
        storage_client_id = client_id if client_id is not None else "serial_client"
        self.client_latest_packets[storage_client_id] = packet
        if not getattr(self, "is_acquiring", False):
            # 停采后仍监视：更新 client_data/总览 CPS，但不累计曲线与自动保存缓冲
            actual_client_id = client_id if client_id is not None else "serial_client"
            try:
                self.diagnostics_manager.process_packet(actual_client_id, packet)
            except Exception:
                pass
            self.update_client_data(actual_client_id, packet)
            if storage_client_id == self.primary_client_id or self.primary_client_id is None:
                try:
                    self.update_device_status_from_packet(packet, client_id)
                except Exception:
                    pass
            if self.data_updated_callback is not None:
                try:
                    self.data_updated_callback(
                        self.current_stat,
                        getattr(self, "total_count_rate", 0),
                        dict(getattr(self, "client_data", None) or {}),
                    )
                except Exception:
                    pass
            return
        
        if storage_client_id not in self.client_time_series:
            self.client_time_series[storage_client_id] = []
            # Initialize spectrum data with correct shape from packet
            self.client_spectrum_data[storage_client_id] = np.zeros(packet.adc_channels)
            self._ensure_autosave_buffers(storage_client_id, packet.adc_channels)
            # Set as primary client if not set yet（手动「显示设备」优先于先来包）
            if self.primary_client_id is None:
                chosen = self._resolve_new_primary_client_id(storage_client_id)
                self.primary_client_id = chosen
                if chosen != storage_client_id:
                    self.log(
                        "Fixed display channel %s (packet from %s)"
                        % (chosen, storage_client_id),
                        "INFO",
                    )
                else:
                    self.log(
                        "Set %s as primary client for chart display" % storage_client_id,
                        "INFO",
                    )
        
        # 用主机接收时刻作横轴（本地时间）；设备 tick 不能当挂钟
        host_ts = time.time()
        row = [host_ts, packet.counter, packet.temperature, packet.HV, np.sum(spectrum)]
        self.client_time_series[storage_client_id].append(row)
        self._ensure_autosave_buffers(storage_client_id, packet.adc_channels)
        self.client_archive_time_series[storage_client_id].append(list(row))
        
        # Ensure spectrum data array has correct shape
        if self.client_spectrum_data[storage_client_id].shape != spectrum.shape:
            self.client_spectrum_data[storage_client_id] = np.zeros_like(spectrum)
        
        # Accumulate spectrum data for this client
        self.client_spectrum_data[storage_client_id] += spectrum
        seg = self.client_segment_spectrum[storage_client_id]
        if seg.shape != spectrum.shape:
            self.client_segment_spectrum[storage_client_id] = np.zeros_like(spectrum)
            seg = self.client_segment_spectrum[storage_client_id]
        seg += spectrum
        
        # 按时间裁剪：至少保留最大窗口（15 分钟）历史，便于切换 1/5/15
        cut = host_ts - CPS_HISTORY_KEEP_SEC
        series = self.client_time_series[storage_client_id]
        if series and series[0][0] < cut:
            self.client_time_series[storage_client_id] = [r for r in series if r[0] >= cut]

        # Update displayed spectrum data from primary client
        if storage_client_id == self.primary_client_id:
            # Ensure displayed spectrum data has correct shape
            if storage_client_id in self.client_spectrum_data:
                if self.spectrum_data.shape != self.client_spectrum_data[storage_client_id].shape:
                    self.spectrum_data = np.zeros_like(self.client_spectrum_data[storage_client_id])
                self.spectrum_data = self.client_spectrum_data[storage_client_id].copy()
        elif self.primary_client_id is None:
            # If no primary client set yet, use this client's data
            # Ensure displayed spectrum data has correct shape
            if storage_client_id in self.client_spectrum_data:
                if self.spectrum_data.shape != self.client_spectrum_data[storage_client_id].shape:
                    self.spectrum_data = np.zeros_like(self.client_spectrum_data[storage_client_id])
                self.spectrum_data = self.client_spectrum_data[storage_client_id].copy()

        #print('spectrum counts:',np.sum(spectrum))
        color = '#ccffcc' if packet.HV>200 else '#ffcccc'
        #self.hv_off_btn.setStyleSheet(f"QPushButton {{ background-color: {color}; }}")

        if self.spectro_buffer_data is None: 
            self.spectro_buffer_data= np.array([spectrum])
        else:
            self.spectro_buffer_data=np.append(self.spectro_buffer_data,np.array([spectrum]), axis=0)
        self.spectro_buffer_time.append(packet.timestamp/1000.)

        self.spectro_buffer_data=self.spectro_buffer_data[-MAX_SPECTRUM_STORED:]
        # 同步裁剪时间缓冲，避免长时间采集时该列表只增不减
        self.spectro_buffer_time = self.spectro_buffer_time[-MAX_SPECTRUM_STORED:]

        # 更新设备状态显示（只更新当前主要客户端的参数）
        self.update_device_status_from_packet(packet, client_id)

        # 报警记录：对每个客户端独立做边沿检测并记录，不受“仅主客户端”限制，
        # 确保多 IP 设备的报警都能进记录表（边沿检测在 alarm_logger 内按 client_id 维护）。
        remote_sig_alarm = (packet.device_status & 0b10000) != 0
        self.log_alarm_event(packet, client_id, remote_sig_alarm)

        # Update client data
        # For serial mode (client_id is None), use "serial_client" as client ID
        # For TCP mode, use the provided client_id
        actual_client_id = client_id if client_id is not None else "serial_client"
        self.update_client_data(actual_client_id, packet)

        # 运行设备诊断自检
        self.diagnostics_manager.process_packet(actual_client_id, packet)
        self._maybe_log_all_probe_cps()

        # 只置脏标志；实际重绘由 plot_timer 统一执行（能谱页 ~10Hz，其它页 ~4Hz）
        self._plot_dirty = True

    def _stacked_page_index(self):
        sw = getattr(self, "stacked_widget", None)
        if sw is None:
            return -1
        try:
            return int(sw.currentIndex())
        except Exception:
            return -1

    def _sync_plot_timer_interval(self, page_index=None):
        """曲线/能谱页 10Hz，其它页 4Hz，减轻点击时主线程抢占。"""
        timer = getattr(self, "plot_timer", None)
        if timer is None:
            return
        if page_index is None:
            page_index = self._stacked_page_index()
        interval = 100 if page_index in (1, 2) else 250
        if timer.interval() != interval:
            timer.setInterval(interval)

    def _on_plot_timer(self):
        """绘图节流：有新数据才刷新。未打开曲线/能谱页时不重绘 pyqtgraph。"""
        if not self._plot_dirty:
            return
        self._plot_dirty = False
        idx = self._stacked_page_index()
        self.update_data(update_cps=(idx == 1), update_spectrum=(idx == 2))

    def update_data(self, update_cps=True, update_spectrum=True):
        # Use data from primary client for chart display
        time_series_data = []
        if self.primary_client_id and self.primary_client_id in self.client_time_series:
            time_series_data = self.client_time_series[self.primary_client_id]
        elif not self._client_selection_is_auto():
            picked = self._client_selection_combo_client_id()
            if picked and picked in self.client_time_series:
                if self.primary_client_id != picked:
                    self.primary_client_id = picked
                time_series_data = self.client_time_series[picked]
        elif self.client_time_series:
            # If no primary client set but we have data, use the first client
            first_client_id = list(self.client_time_series.keys())[0]
            if self.primary_client_id != first_client_id:
                self.primary_client_id = first_client_id
                self.log(f"Auto-selected {first_client_id} as primary client", 'INFO')
            time_series_data = self.client_time_series[first_client_id]
        
        if time_series_data:
            last = time_series_data[-1]
            self.current_stat = {
                'hv': last[3],
                'rates': float(last[1]),
                'temp': last[2] / 100
            }
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, self.client_data)

            if update_cps and hasattr(self, "curve_cps"):
                timestamps, counters, temperatures, hvs, spec_counts = zip(*time_series_data)
                if len(timestamps) >= 1:
                    window_min = int(getattr(self, "cps_window_minutes", 5) or 5)
                    if window_min not in CPS_WINDOW_CHOICES:
                        window_min = 5
                    now = time.time()
                    t0 = now - window_min * 60
                    ts = np.asarray(timestamps, dtype=np.float64)
                    rates_all = np.asarray(counters, dtype=np.float64)
                    mask = ts >= t0
                    if np.any(mask):
                        times = ts[mask]
                        rates = rates_all[mask]
                    else:
                        times = ts[-1:]
                        rates = rates_all[-1:]

                    self.curve_cps.setData(times, rates)
                    if hasattr(self, "cps_widget") and hasattr(self.cps_widget, "setXRange"):
                        self.cps_widget.setXRange(t0, now, padding=0)
                        self.cps_widget.enableAutoRange('y', True)

            if update_spectrum and hasattr(self, "curve_spectrum"):
                if FILTER_ENABLED:
                    self.spectrum_data = alg.hampel_filter(
                        self.spectrum_data, FILTER_WIN_SIZE, FILTER_NUM_SIGMA
                    )
            if len(self.channels) != len(self.spectrum_data) + 1:
                self.channels = np.arange(len(self.spectrum_data) + 1)
            self.curve_spectrum.setData(self.channels, self.spectrum_data)
            self.update_spectrogram()
        
    def on_connection_status_changed(self, connected: bool, message: str):
        self.set_status_label(message, connected)
    def on_has_log(self, msg: str, dtype: str):
        # Check if this is a special signal for USB port change
        if dtype == 'SIGNAL' and msg.startswith('USB_PORT_CHANGED:'):
            # Extract the new port
            new_port = msg.split(':')[1]
            self.log(f"Received USB port change signal: {new_port}", 'INFO')
            # Update serial port combo immediately
            self.update_serial_port_combo()
        else:
            self.log(msg, dtype)

    def set_status_label(self, message, is_good = None):
        pass
        #self.status_label.setText(message)
        #if is_good is not None:
        #    color='color:green' if is_good else 'color:red'
        #    self.status_label.setStyleSheet(color)

    
    def on_error_occurred(self, error_message: str):
        msg = str(error_message or "")
        dm = getattr(self, "diagnostics_manager", None)
        if (
            dm is not None
            and hasattr(dm, "comm_timeouts_suppressed")
            and dm.comm_timeouts_suppressed()
            and "communication timeout" in msg.lower()
        ):
            return
        self.packet_counts['errors'] += 1
        self.log(f"ERROR: {error_message}")
    
    
    def on_command_sent(self, message: str):
        self.log_output.append(f"<span style='color: blue;'>{message}</span>")

    def on_tcp_client_connected(self, client_id: str):
        self.log(f"TCP client connected: {client_id}", 'INFO')
        dm = getattr(self, "diagnostics_manager", None)
        if dm is not None and hasattr(dm, "note_client_tcp_connected"):
            dm.note_client_tcp_connected(client_id)
        if self.primary_client_id is None:
            self.primary_client_id = client_id
            self.apply_primary_client_snapshot()
        if getattr(self, "_pinned_product_id_client_id", None) is None and self._is_settings_probe_client(client_id):
            self._pinned_product_id_client_id = client_id
            self._stable_default_probe_client_id = client_id
        self.update_client_selection_combo()
        # 新探头上线且数量已达标时，立刻清幽灵离线故障/编号
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        connected = []
        if hasattr(self, "get_online_probe_client_ids"):
            connected = self.get_online_probe_client_ids()
        elif hasattr(self, "worker") and self.worker is not None:
            connected = list((getattr(self.worker, "client_infos", None) or {}).keys())
        if expected > 0 and len(connected) >= expected and getattr(self, "diagnostics_manager", None):
            known = set(self.diagnostics_manager.active_faults.keys()) | set(
                self.diagnostics_manager.last_packet_time.keys()
            )
            connected_set = set(connected)
            for cid in list(known):
                if cid != "system" and cid not in connected_set:
                    self.diagnostics_manager.remove_client(cid)
            if hasattr(self, "prune_disconnected_probe_labels"):
                self.prune_disconnected_probe_labels(connected)
            if hasattr(self, "update_system_status"):
                self.update_system_status()

    def on_tcp_client_disconnected(self, client_id: str):
        self.log(f"TCP client disconnected: {client_id}", 'INFO')

        # 主控 TCP 断开：首页立即切离线（硬报警不再由 PC 拼）
        # 端口变了、id 还没写上时，用已记住的主控 IP 识别，避免记成探头 E102
        master_ip = str(getattr(self, "_last_master_ip", "") or "")
        cid_ip = self._extract_client_ip(client_id) if client_id else ""
        live_master = str(self.master_client_id or "")
        same_master_ip = bool(master_ip and cid_ip == master_ip)
        if client_id and (client_id == live_master or same_master_ip):
            worker = getattr(self, "worker", None)
            live_still_up = False
            if live_master and client_id != live_master and worker is not None:
                infos = getattr(worker, "client_infos", None) or {}
                sockets = getattr(worker, "client_sockets", None) or {}
                live_still_up = live_master in infos or live_master in sockets
            if live_still_up:
                # 旧端口的断开晚到：新会话已经是主控，不能把首页打成离线
                dm = getattr(self, "diagnostics_manager", None)
                if dm is not None and hasattr(dm, "remove_client"):
                    try:
                        dm.remove_client(client_id)
                    except Exception:
                        pass
                self.remove_client_display_data(client_id)
                if hasattr(self, "update_system_status"):
                    try:
                        self.update_system_status()
                    except Exception:
                        pass
                return
            self._remember_master_endpoint(client_id)
            self.master_client_id = None
            if hasattr(self, "worker") and self.worker is not None:
                try:
                    self.worker.master_client_id = None
                except Exception:
                    pass
            self.latest_master_summary = None
            self._master_was_online = False
            if self.master_summary_callback is not None:
                self.master_summary_callback(None, client_id)
            # 主控不是探头，不记 E102；同一 IP 上旧会话的粘滞故障一并清掉
            self._clear_master_sessions_from_probe_faults(client_id)
            self.remove_client_display_data(client_id)
            return

        old_pid = self._resolve_product_id(client_id)
        old_ip = self._extract_client_ip(client_id)

        # 断线后还剩几台在线（本 client 已从 worker 移除）
        remaining = []
        if hasattr(self, "get_online_probe_client_ids"):
            remaining = self.get_online_probe_client_ids()
        elif self.config.tcp_enabled and hasattr(self, "worker") and self.worker is not None:
            remaining = list((getattr(self.worker, "client_infos", None) or {}).keys())
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0

        reinit_grace = float(getattr(self, "_tcp_reinit_grace_until", 0) or 0)
        if reinit_grace > time.time():
            self.remove_client_display_data(client_id)
            if hasattr(self, "update_system_status"):
                self.update_system_status()
            return

        if (getattr(self, 'diagnostics_manager', None) is not None
                and getattr(self, 'is_acquiring', False)):
            from core.diagnostics import FaultCode
            # 在线数仍 ≥ 期望：属于减配到期望内或热替换过程，不粘住旧 E102
            if expected > 0 and len(remaining) >= expected:
                self.diagnostics_manager.remove_client(client_id)
                if old_ip:
                    self.forget_probe_ip(old_ip)
                self.log(
                    f"Probe disconnected but online {len(remaining)}>={expected}: "
                    f"skip sticky E102 for {client_id}",
                    'INFO'
                )
            else:
                # 真正缺编：保留编号快照并记 E102
                self._remember_probe(client_id, old_pid)
                self.diagnostics_manager.add_fault(client_id, FaultCode.E102)

        if hasattr(self, "_freeze_probe_display_num"):
            self._freeze_probe_display_num(client_id)
        self.remove_client_display_data(client_id)

        if self.primary_client_id == client_id:
            available_clients = self.get_available_clients()
            self.primary_client_id = available_clients[0] if available_clients else None
            self.apply_primary_client_snapshot()

        self.update_client_selection_combo()
        if expected > 0 and len(remaining) >= expected and hasattr(self, "prune_disconnected_probe_labels"):
            self.prune_disconnected_probe_labels(remaining)
        if hasattr(self, 'update_system_status'):
            self.update_system_status()

    def remove_client_display_data(self, client_id: str):
        # 断线前先结算该客户端的报警状态：若仍在报警中，补记一条“报警结束”，
        # 并清理记录器内部状态，避免“报警结束”边沿丢失导致下次报警被漏记。
        self.finalize_client_alarm_on_disconnect(client_id)

        # 保留 time_series / spectrum，供自动保存与 U 盘导出；仅清实时状态
        self.client_latest_packets.pop(client_id, None)
        self.client_data.pop(client_id, None)

        if not self.client_data:
            self.spectrum_data = np.zeros(self.config.adc_channels)
            self.curve_cps.setData([], [])
            if len(self.channels) != len(self.spectrum_data) + 1:
                self.channels = np.arange(len(self.spectrum_data) + 1)
            self.curve_spectrum.setData(self.channels, self.spectrum_data)
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.clear_current_device_status_display()
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, self.client_data)

    def clear_current_device_status_display(self):
        for attr, value in [
            ('counter_label', '0'),
            ('product_id_label', '--'),
            ('sensitivity_label', '--'),
            ('relay_status_label', 'Relay Status: --'),
            ('alarm_status_label', 'INACTIVE'),
            ('occupancy_status_label', '--'),
        ]:
            if hasattr(self, attr):
                getattr(self, attr).setText(value)

        if hasattr(self, 'alarm_status_label'):
            self.alarm_status_label.setStyleSheet("background-color: #ccffcc; color: #000000;")
        if self.alarm_status_callback is not None:
            self.alarm_status_callback(False)
    
    def _read_spinbox_value(self, spin, default_value=0):
        """Read value from spinbox lineEdit to ensure virtual keyboard input is applied."""
        try:
            if hasattr(spin, 'lineEdit') and spin.lineEdit():
                text = spin.lineEdit().text().strip()
                if text:
                    try:
                        return float(text) if isinstance(spin, QDoubleSpinBox) else int(float(text))
                    except Exception:
                        pass
            if hasattr(spin, 'interpretText'):
                spin.interpretText()
            return spin.value()
        except Exception:
            return default_value

    def _current_probe_key(self, client_id: str = None) -> str:
        cid = client_id or self._product_id_panel_client_id() or self.primary_client_id
        if not cid:
            return "serial" if not getattr(self.config, "tcp_enabled", False) else ""
        if cid == "serial_client":
            return "serial"
        return self._extract_client_ip(cid) or cid

    def _client_selection_is_auto(self) -> bool:
        combo = getattr(self, "client_selection_combo", None)
        if combo is None:
            return True
        try:
            return int(combo.currentIndex()) <= 0
        except Exception:
            return True

    def _fixed_display_client_id(self):
        """非「自动」时返回固定显示通道（设置下拉或总览点选）。"""
        if self._client_selection_is_auto():
            return None
        cid = self._client_selection_combo_client_id()
        if cid:
            return cid
        stable = getattr(self, "_stable_default_probe_client_id", None)
        return stable or None

    def pin_display_channel(self, client_id: str):
        """首页/总览点探头卡：固定该路在计数率、能谱页的显示，并同步「显示设备」。"""
        if not client_id:
            return
        self._stable_default_probe_client_id = client_id
        if hasattr(self, "_is_settings_probe_client") and self._is_settings_probe_client(client_id):
            self._pinned_product_id_client_id = client_id
            self._product_id_lock_ui_sig = None
        combo = getattr(self, "client_selection_combo", None)
        if combo is not None:
            for i in range(combo.count()):
                if combo.itemData(i) == client_id:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break
        try:
            self.set_primary_client(client_id)
        except Exception as e:
            self.log("pin_display_channel(%s): %s" % (client_id, e), "WARNING")
            self.primary_client_id = client_id
            try:
                self.apply_primary_client_snapshot()
            except Exception:
                pass
            self._plot_dirty = True

    def _resolve_new_primary_client_id(self, packet_client_id: str) -> str:
        """首包或 primary 为空时：固定显示通道优先，否则跟当前包。"""
        fixed = self._fixed_display_client_id()
        if fixed:
            return fixed
        return packet_client_id

    def _bind_display_channel_after_clear(self):
        """清空累计后恢复设置里固定的显示通道（两路数据仍都会重新累加）。"""
        cid = self._fixed_display_client_id()
        if not cid:
            self.primary_client_id = None
            return
        self.primary_client_id = cid
        if cid not in self.client_spectrum_data:
            self.client_spectrum_data[cid] = np.zeros(self.config.adc_channels)
        self.spectrum_data = np.zeros(self.config.adc_channels)
        if cid not in self.client_time_series:
            self.client_time_series[cid] = []
        try:
            self.apply_primary_client_snapshot()
        except Exception:
            pass
        self._plot_dirty = True
        self.log("Display channel fixed to %s after clear" % cid, "INFO")

    def _get_master_client_id_resolved(self):
        master_cid = getattr(self, "master_client_id", None)
        if not master_cid and getattr(self, "worker", None) is not None:
            master_cid = getattr(self.worker, "master_client_id", None)
        return master_cid

    def _is_settings_probe_client(self, client_id: str) -> bool:
        if not client_id or client_id == "system":
            return False
        master_cid = self._get_master_client_id_resolved()
        return not (master_cid and client_id == master_cid)

    def _stable_probe_client_id_for_panel(self):
        clients = self.get_available_clients() if hasattr(self, "get_available_clients") else []
        live = [c for c in clients if self._is_settings_probe_client(c) and self._probe_client_is_live(c)]

        def sort_key(cid):
            return (self._extract_client_ip(cid) or cid, str(cid))

        live.sort(key=sort_key)
        return live[0] if live else None

    def _reassign_pinned_product_id_client(self):
        cid = self._client_selection_combo_client_id() or self._stable_probe_client_id_for_panel()
        if cid and self._is_settings_probe_client(cid):
            self._pinned_product_id_client_id = cid
        else:
            self._pinned_product_id_client_id = None
        self._product_id_lock_ui_sig = None

    def _client_selection_combo_client_id(self):
        combo = getattr(self, "client_selection_combo", None)
        if combo is None:
            return None
        try:
            idx = int(combo.currentIndex())
        except Exception:
            return None
        if idx <= 0:
            return None
        try:
            return combo.itemData(idx)
        except Exception:
            return None

    def _product_id_panel_client_id(self, hint_client_id: str = None):
        """设置页产品 ID 维护绑定的探头（与谱图 primary 解耦，避免多探头时状态乱跳）。"""
        pinned = getattr(self, "_pinned_product_id_client_id", None)
        if pinned and self._is_settings_probe_client(pinned) and self._probe_client_is_live(pinned):
            return pinned
        selected = self._client_selection_combo_client_id()
        if selected and self._is_settings_probe_client(selected) and self._probe_client_is_live(selected):
            return selected
        if hint_client_id and self._is_settings_probe_client(hint_client_id) and self._probe_client_is_live(hint_client_id):
            return hint_client_id
        stable = getattr(self, "_stable_default_probe_client_id", None)
        if stable and self._is_settings_probe_client(stable) and self._probe_client_is_live(stable):
            return stable
        stable = self._stable_probe_client_id_for_panel()
        if stable:
            self._stable_default_probe_client_id = stable
            return stable
        if (
            self.primary_client_id
            and self._is_settings_probe_client(self.primary_client_id)
            and self._probe_client_is_live(self.primary_client_id)
        ):
            return self.primary_client_id
        return hint_client_id if hint_client_id and self._is_settings_probe_client(hint_client_id) else None

    def pin_product_id_panel_client(self, client_id: str = None):
        cid = client_id or self._client_selection_combo_client_id() or self._stable_probe_client_id_for_panel()
        if cid and not self._is_settings_probe_client(cid):
            cid = self._stable_probe_client_id_for_panel()
        if not cid and self.primary_client_id and self._is_settings_probe_client(self.primary_client_id):
            cid = self.primary_client_id
        if cid and self._is_settings_probe_client(cid):
            self._pinned_product_id_client_id = cid
            self._stable_default_probe_client_id = cid
            self._product_id_lock_ui_sig = None
            if hasattr(self, "load_probe_panel_settings"):
                self.load_probe_panel_settings(cid)
            else:
                self._refresh_product_id_lock_ui(cid)

    def _display_sensitivity_m(self, client_id: str = None, packet=None) -> float:
        """界面显示的 M：优先配置/读回浮点，不用谱包 sen_coef 整数覆盖。"""
        from core.sensitivity_m import clamp_m

        cid = client_id or getattr(self, "primary_client_id", None)
        key = self._current_probe_key(cid) if cid else None
        if key:
            entry = (getattr(self.config, "client_probe_settings", None) or {}).get(key, {})
            if "sensitivity" in entry:
                try:
                    return clamp_m(float(entry["sensitivity"]))
                except (TypeError, ValueError):
                    pass
        if cid and getattr(self, "client_data", None):
            prev = self.client_data.get(cid) or {}
            v = prev.get("sensitivity")
            if v not in (None, "", "--"):
                try:
                    return clamp_m(float(v))
                except (TypeError, ValueError):
                    pass
        if packet is not None and getattr(packet, "sen_coef", None) not in (None, 0):
            return clamp_m(float(packet.sen_coef))
        return clamp_m(getattr(self.config, "sensitivity", 3.0))

    def _save_probe_panel_settings(self, client_id: str = None, hv=None, threshold=None,
                                   sensitivity=None, product_id=None):
        """Persist panel values for the given/current probe IP."""
        cid = client_id or self.primary_client_id
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if cid and master_cid and cid == master_cid:
            return
        key = self._current_probe_key(cid)
        if not key:
            return
        kwargs = {}
        if hv is not None:
            kwargs["hv"] = hv
        if threshold is not None:
            kwargs["threshold"] = threshold
        if sensitivity is not None:
            kwargs["sensitivity"] = sensitivity
        if product_id is not None:
            kwargs["product_id"] = product_id
        if not kwargs:
            return
        self.config.update_probe_settings(key, **kwargs)
        self.config.save_settings()

    def load_probe_panel_settings(self, client_id: str = None):
        """Fill HV/threshold/sensitivity spinboxes for the selected probe."""
        cid = client_id or self._product_id_panel_client_id() or self.primary_client_id
        master_cid = self._get_master_client_id() if hasattr(self, "_get_master_client_id") else getattr(self, "master_client_id", None)
        if cid and master_cid and cid == master_cid:
            return
        key = self._current_probe_key(cid)
        if not key or not hasattr(self, "hv_spin"):
            return

        stored = self.config.get_probe_settings(key)
        # 无历史记录时，尽量用该探头最新包里的实际值作参考显示
        pkt = self.client_latest_packets.get(cid) if cid else None
        data = self.client_data.get(cid) if cid else None
        probe_store = (getattr(self.config, "client_probe_settings", {}) or {}).get(key, {})

        hv = stored["hv"]
        if "hv" not in probe_store:
            if pkt is not None and getattr(pkt, "HV", 0):
                hv = float(pkt.HV)
            elif data and data.get("hv"):
                hv = float(data["hv"])

        thr = stored["threshold"]
        sens = stored["sensitivity"]
        if "sensitivity" not in probe_store:
            if data and data.get("sensitivity") not in (None, 0, "--"):
                try:
                    sens = float(data["sensitivity"])
                except (TypeError, ValueError):
                    pass
            elif pkt is not None and getattr(pkt, "sen_coef", None) not in (None, 0):
                sens = float(pkt.sen_coef)

        pid = stored.get("product_id")
        if pid is None:
            if pkt is not None:
                pid = getattr(pkt, "product_id", None)
            elif data:
                pid = data.get("product_id")

        widgets = []
        if hasattr(self, "hv_spin"):
            widgets.append(self.hv_spin)
        if hasattr(self, "threshold_spin"):
            widgets.append(self.threshold_spin)
        if hasattr(self, "sensitivity_spin"):
            widgets.append(self.sensitivity_spin)
        if hasattr(self, "product_id_spin"):
            widgets.append(self.product_id_spin)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.hv_spin.setValue(float(hv))
            self.threshold_spin.setValue(int(thr))
            from core.sensitivity_m import clamp_m

            self.sensitivity_spin.setValue(clamp_m(sens))
            if hasattr(self, "product_id_spin") and self._product_id_spin_device_sync_allowed(cid):
                try:
                    self.product_id_spin.setValue(int(pid or 0))
                except Exception:
                    self.product_id_spin.setValue(0)
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._refresh_product_id_lock_ui(cid)

    def persist_hv_setting(self):
        try:
            voltage = self._read_spinbox_value(self.hv_spin, self.hv_spin.value())
            self.hv_spin.setValue(float(voltage))
            self._save_probe_panel_settings(hv=voltage)
        except Exception:
            pass

    def persist_threshold_setting(self):
        try:
            level = self._read_spinbox_value(self.threshold_spin, self.threshold_spin.value())
            self.threshold_spin.setValue(int(level))
            self._save_probe_panel_settings(threshold=level)
        except Exception:
            pass

    def _apply_sensitivity_from_feedback(self, packet: CmdFeedback):
        from core.sensitivity_m import clamp_m, decode_feedback_x10, format_m_display

        m = decode_feedback_x10(packet.value)
        src = getattr(packet, "source_client_id", None)
        if src and getattr(self, "client_data", None):
            data = self.client_data.get(src)
            if data is not None:
                data["sensitivity"] = m
        settings_cid = None
        if hasattr(self, "_get_probe_client_id_for_settings"):
            settings_cid = self._get_probe_client_id_for_settings()
        if not settings_cid and hasattr(self, "_product_id_panel_client_id"):
            settings_cid = self._product_id_panel_client_id()
        if not settings_cid:
            settings_cid = getattr(self, "primary_client_id", None)
        if settings_cid and src and src != settings_cid:
            return
        if hasattr(self, "sensitivity_spin"):
            self.sensitivity_spin.blockSignals(True)
            self.sensitivity_spin.setValue(clamp_m(m))
            self.sensitivity_spin.blockSignals(False)
        if hasattr(self, "sensitivity_label"):
            self.sensitivity_label.setText(format_m_display(m))
        self._save_probe_panel_settings(sensitivity=m)
        self.log(f"Sensitivity M readback: {format_m_display(m)} (0x{packet.control_code:02X})", "INFO")

    def persist_sensitivity_setting(self):
        try:
            from core.sensitivity_m import clamp_m

            coefficient = self._read_spinbox_value(self.sensitivity_spin, self.sensitivity_spin.value())
            m = clamp_m(coefficient)
            self.sensitivity_spin.setValue(m)
            self._save_probe_panel_settings(sensitivity=m)
        except Exception:
            pass
    
    def set_high_voltage(self):
        try:
            voltage = self._read_spinbox_value(self.hv_spin, self.hv_spin.value())
            self.hv_spin.setValue(float(voltage))
            # 仅对当前选中探头记录设定值（两台可分别 1100/1200，避免互相反报 E202）
            target_client = None
            if self.config.tcp_enabled and self.primary_client_id:
                target_client = self.primary_client_id
            elif not self.config.tcp_enabled:
                target_client = "serial_client"

            if target_client:
                probe_key = self._extract_client_ip(target_client) or target_client
                self.config.mark_client_hv_setpoint(probe_key, voltage)
                if hasattr(self, "diagnostics_manager") and self.diagnostics_manager:
                    self.diagnostics_manager.mark_client_hv_setpoint(target_client, voltage)
            else:
                self.config.mark_hv_user_set(voltage)
            self.config.save_settings()
        except Exception:
            pass
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'set_hv', voltage)
                    if success:
                        self.log(f"Set HV command sent to client {self.primary_client_id}: {voltage}V")
                    else:
                        self.log(f"Failed to send HV command to client {self.primary_client_id}", 'ERROR')
                else:
                    self.worker.set_high_voltage(voltage)
            else:
                # 串口模式或单客户端
                self.worker.set_high_voltage(voltage)
        else:
            self.log("Connection not ready, HV saved locally only", 'WARNING')
    
    def set_threshold(self):
        try:
            level = self._read_spinbox_value(self.threshold_spin, self.threshold_spin.value())
            self.threshold_spin.setValue(int(level))
            self._save_probe_panel_settings(threshold=level)
        except Exception:
            pass
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'set_threshold', level)
                    if success:
                        self.log(f"Set threshold command sent to client {self.primary_client_id}: {level}mV")
                    else:
                        self.log(f"Failed to send threshold command to client {self.primary_client_id}", 'ERROR')
                else:
                    self.worker.set_threshold(level)
            else:
                # 串口模式或单客户端
                self.worker.set_threshold(level)
        else:
            self.log("Connection not ready, threshold saved locally only", 'WARNING')
    
    def set_operation_mode(self, mode):
        if mode not in ['NOMINAL','STANDBY']:
            self.log(f'Invalid mode:{mode}','ERROR')
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'set_operation_mode', mode)
                    if success:
                        self.log(f"Set operation mode command sent to client {self.primary_client_id}: {mode}")
                    else:
                        self.log(f"Failed to send operation mode command to client {self.primary_client_id}", 'ERROR')
                else:
                    self.worker.set_operation_mode(mode)
            else:
                # 串口模式或单客户端
                self.worker.set_operation_mode(mode)
    
    # TCP/IP Settings Handlers
    def on_tcp_enable_changed(self, state):
        enabled = state == Qt.Checked
        self.config.update_settings(tcp_enabled=enabled, tcp_mode="server")  # Always server mode
        self.update_comm_settings_visibility()
        
        # Reinitialize worker if needed
        if self.worker:
            was_acquiring = bool(self.is_acquiring)
            old_worker = self.worker
            if was_acquiring:
                self.stop_acquisition()
            self.disconnect_worker_signals(old_worker)
            if isinstance(old_worker, SerialPacketWorker):
                self._detach_read_timer_to_gui_thread()
                old_worker.stop_reading()
                old_worker.disconnect_serial()
            elif is_tcp_worker(old_worker):
                self._shutdown_tcp_worker_blocking(old_worker)
            self._queue_worker_delete(old_worker)
            self.worker = None

            self.reset_plots()
            self.client_data = {}
            self.client_time_series = {}
            self.client_spectrum_data = {}
            self.client_archive_time_series = {}
            self.client_segment_spectrum = {}
            self.client_latest_packets = {}
            self.primary_client_id = None
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.total_count_rate = 0
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, {})
            
            self.initialize_worker()
            if self.worker:
                self.worker.moveToThread(self.worker_thread)
                self.connect_worker_signals()
                self._bind_read_timer_to_worker()
                if enabled and self.ensure_connection_ready():
                    self._ensure_tcp_link_layer()
                if was_acquiring and enabled:
                    self.start_acquisition()
                elif enabled and is_tcp_worker(self.worker):
                    self.worker.start_reading()
                    self._start_read_timer()
        
        self.log(f"TCP/IP server mode {'enabled' if enabled else 'disabled'}", 'INFO')
    
    def on_tcp_host_changed(self, host):
        self.config.update_settings(tcp_host=host)
    
    def on_tcp_port_changed(self, port):
        self.config.update_settings(tcp_port=port)
        if self.config.tcp_enabled and not getattr(self.config, "tcp_multi_port", False):
            self._reinit_tcp_worker_after_comm_change("TCP single-port changed to %s" % port)

    def on_tcp_port_master_changed(self, port):
        self.config.update_settings(tcp_port_master=port)
        if self.config.tcp_enabled and getattr(self.config, "tcp_multi_port", False):
            self._reinit_tcp_worker_after_comm_change("TCP master port changed to %s" % port)

    def on_tcp_port_probe_changed(self, port):
        self.config.update_settings(tcp_port_probe=port)
        if self.config.tcp_enabled and getattr(self.config, "tcp_multi_port", False):
            self._reinit_tcp_worker_after_comm_change("TCP probe port changed to %s" % port)

    def on_tcp_multi_port_changed(self, state):
        enabled = state == Qt.Checked
        if enabled:
            self.tcp_port_master_spin.blockSignals(True)
            self.tcp_port_probe_spin.blockSignals(True)
            self.tcp_port_master_spin.setValue(DEFAULT_TCP_PORT_MASTER)
            self.tcp_port_probe_spin.setValue(DEFAULT_TCP_PORT_PROBE)
            self.tcp_port_master_spin.blockSignals(False)
            self.tcp_port_probe_spin.blockSignals(False)
            self.config.update_settings(
                tcp_multi_port=True,
                tcp_port_master=DEFAULT_TCP_PORT_MASTER,
                tcp_port_probe=DEFAULT_TCP_PORT_PROBE,
            )
        else:
            self.config.update_settings(tcp_multi_port=False, tcp_port=self.tcp_port_spin.value())
        self.update_comm_settings_visibility()
        if hasattr(self, "refresh_software_version_labels"):
            self.refresh_software_version_labels()
        if not self.config.tcp_enabled:
            return
        self._reinit_tcp_worker_after_comm_change(
            "TCP multi-port %s" % ("enabled" if enabled else "disabled")
        )

    def _clear_tcp_reconnect_backoff(self):
        """MainWindow 定时重连有指数退避；改端口/模式后应立即 bind。"""
        self._tcp_reconnect_backoff_sec = 0
        self._tcp_reconnect_last_at = 0
        self._tcp_reconnect_key = None

    def _reinit_tcp_worker_after_comm_change(self, reason: str):
        if not self.config.tcp_enabled:
            return
        if getattr(self, "_tcp_worker_reinit_busy", False):
            return
        self._tcp_worker_reinit_busy = True
        was_acquiring = bool(self.is_acquiring)
        old_worker = self.worker
        grace_sec = 90.0
        self._tcp_reinit_grace_until = time.time() + grace_sec
        dm = getattr(self, "diagnostics_manager", None)
        if dm is not None and hasattr(dm, "defer_comm_timeouts"):
            dm.defer_comm_timeouts(grace_sec)
        self._reset_master_link_state_for_tcp_reinit()

        try:
            if was_acquiring:
                self.stop_acquisition(user_initiated=False)
            if old_worker:
                self.disconnect_worker_signals(old_worker)
                self._shutdown_tcp_worker_blocking(old_worker)
                self._queue_worker_delete(old_worker)
            self.worker = None

            self._clear_tcp_reconnect_backoff()
            self.initialize_worker()
            if not self.worker:
                return
            self.worker.moveToThread(self.worker_thread)
            self.connect_worker_signals()
            if self.raw_logger:
                try:
                    self.worker.set_logger(self.raw_logger)
                except TypeError:
                    self.worker.set_logger(self.raw_logger, self.log)
            self._bind_read_timer_to_worker()
            if self.ensure_connection_ready():
                self._ensure_tcp_link_layer()
            if hasattr(self, "prune_disconnected_probe_labels"):
                try:
                    online = (
                        self.get_online_probe_client_ids()
                        if hasattr(self, "get_online_probe_client_ids")
                        else []
                    )
                    self.prune_disconnected_probe_labels(online)
                except Exception:
                    pass
            if was_acquiring:
                self.start_acquisition()
            elif is_tcp_worker(self.worker):
                self.worker.start_reading()
                self._start_read_timer()
            self.log(reason + "; TCP worker reinitialized and listen rebound", "INFO")
        finally:
            self._tcp_worker_reinit_busy = False
    
    def on_serial_port_changed(self, port):
        """串口设备改变时的处理"""
        old_port = self.config.device
        self.config.update_settings(device=port)
        
        # 如果串口设备改变，并且当前是串口模式，尝试重新连接
        if not self.config.tcp_enabled and port != old_port:
            self.log(f"Serial port changed from {old_port} to {port}, attempting to reconnect...", 'INFO')
            was_acquiring = bool(self.is_acquiring)
            
            # 停止当前的数据采集
            if was_acquiring:
                self.stop_acquisition()
            
            # 断开当前连接
            if isinstance(self.worker, SerialPacketWorker):
                self.worker.disconnect_serial()
            
            # 尝试重新连接
            if isinstance(self.worker, SerialPacketWorker):
                connected = self.worker.connect_serial(port, self.config.baudrate)
                if connected:
                    self.log(f"Successfully reconnected to {port}", 'INFO')
                    # 如果之前正在采集数据，重新开始采集
                    if was_acquiring:
                        self.start_acquisition()
                else:
                    self.log(f"Failed to reconnect to {port}", 'ERROR')
    
    def on_baudrate_changed(self, baudrate_text):
        try:
            baudrate = int(baudrate_text)
            self.config.update_settings(baudrate=baudrate)
        except ValueError:
            self.log(f"Invalid baudrate: {baudrate_text}", 'ERROR')

    def on_expected_probe_count_changed(self, value):
        self.apply_expected_probe_count(int(value), source="spinbox")

    def on_ir_installed_changed(self, _state=None):
        cb = getattr(self, "ir_installed_checkbox", None)
        if cb is None:
            return
        checked = bool(cb.isChecked())
        self.config.update_settings(ir_installed=checked)
        self.config.save_settings()
        pkt = getattr(self, "latest_master_summary", None)
        offline = not (hasattr(self, "is_master_online") and self.is_master_online())
        if hasattr(self, "_update_home_occupancy"):
            self._update_home_occupancy(pkt, master_offline=offline)
        if hasattr(self, "_update_overview_occupancy_from_master"):
            self._update_overview_occupancy_from_master(pkt, master_offline=offline)
        if hasattr(self, "_update_settings_occupancy_from_master"):
            self._update_settings_occupancy_from_master(pkt, master_offline=offline)
        if hasattr(self, "_update_home_alarm_from_master"):
            self._update_home_alarm_from_master(pkt, master_offline=offline)
        if hasattr(self, "_update_home_health_and_faults"):
            self._update_home_health_and_faults()
        home = getattr(self, "home_page", None)
        if home is not None and hasattr(home, "schedule_web_flush"):
            home.schedule_web_flush(immediate=True)
        if getattr(self, "control_room_mode", False) and hasattr(self, "_refresh_control_room_snapshot"):
            self._refresh_control_room_snapshot()

    def on_ui_mode_changed(self, _index=None):
        from core.translation import _t
        if not hasattr(self, "ui_mode_combo"):
            return
        mode = self.ui_mode_combo.currentData()
        if mode is None:
            return
        mode = str(mode)
        if mode == str(getattr(self.config, "ui_mode", "tablet")):
            return
        self.config.update_settings(ui_mode=mode)
        self.config.save_settings()
        try:
            from core.industrial_dialogs import show_info
            show_info(self if isinstance(self, QWidget) else None,
                      _t("set_ui_mode"), _t("msg_ui_mode_restart"))
        except Exception:
            pass

    def _stock_probe_slot_location_sets(self):
        from core.translation import STOCK_PROBE_LOCS_ZH, STOCK_PROBE_LOCS_EN
        return list(STOCK_PROBE_LOCS_ZH), list(STOCK_PROBE_LOCS_EN)

    def _probe_location_slot_count(self):
        try:
            n = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        saved = list(getattr(self.config, "probe_slot_locations", None) or [])
        if n <= 0:
            n = max(2, len(saved), 4)
        return max(1, min(16, n))

    def _current_language_probe_slot_locations(self):
        from core.translation import default_probe_location
        return [default_probe_location(i) for i in range(self._probe_location_slot_count())]

    def _rebuild_probe_location_edits(self):
        """Create N location editors matching expected probe count."""
        from core.translation import _t, localize_probe_location
        if not hasattr(self, "probe_location_grid"):
            return
        count = self._probe_location_slot_count()
        saved = list(getattr(self.config, "probe_slot_locations", None) or [])

        # Clear old cells
        while self.probe_location_grid.count():
            item = self.probe_location_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.probe_location_edits = []
        self.probe_location_slot_labels = []
        self.probe_location_cells = []

        cols = 4 if count > 4 else max(1, count)
        for i in range(count):
            cell = QWidget()
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(2)
            slot_lbl = QLabel(_t("probe_num", n=i + 1))
            edit = QLineEdit()
            saved_txt = str(saved[i]).strip() if i < len(saved) else ""
            edit.setText(localize_probe_location(saved_txt, i))
            edit.setPlaceholderText(_t("probe_loc_n", n=i + 1) if i > 3 else _t("probe_loc_%d" % i))
            edit.setToolTip(_t("tip_probe_locations"))
            edit.editingFinished.connect(self.on_probe_slot_locations_changed)
            cell_lay.addWidget(slot_lbl)
            cell_lay.addWidget(edit)
            self.probe_location_grid.addWidget(cell, i // cols, i % cols)
            self.probe_location_edits.append(edit)
            self.probe_location_slot_labels.append(slot_lbl)
            self.probe_location_cells.append(cell)

    def on_probe_slot_locations_changed(self):
        """Save settings-page location labels and refresh home HMI."""
        from core.translation import canonical_probe_location
        if not hasattr(self, "probe_location_edits"):
            return
        locs = []
        all_default = True
        for i, edit in enumerate(self.probe_location_edits):
            text = (edit.text() or "").strip()
            stored = canonical_probe_location(text, i)
            locs.append(stored)
            if stored:
                all_default = False
        if all_default or not any(locs):
            self.config.set_probe_slot_locations([])
        else:
            self.config.set_probe_slot_locations(locs)
        self.config.save_settings()
        home = getattr(self, "home_page", None)
        if home is not None and hasattr(home, "sync_probe_slot_locations"):
            home.sync_probe_slot_locations(immediate=True)
        elif home is not None and hasattr(home, "schedule_web_flush"):
            home.schedule_web_flush()
        if getattr(self, "control_room_mode", False) and hasattr(self, "_refresh_control_room_snapshot"):
            self._refresh_control_room_snapshot()

    def refresh_probe_location_edits(self):
        """Fill settings edits from config or current-language defaults."""
        from core.translation import _t, localize_probe_location
        want = self._probe_location_slot_count()
        if len(getattr(self, "probe_location_edits", []) or []) != want:
            self._rebuild_probe_location_edits()
            return
        saved = list(getattr(self.config, "probe_slot_locations", None) or [])
        for i, edit in enumerate(self.probe_location_edits):
            saved_txt = str(saved[i]).strip() if i < len(saved) else ""
            edit.blockSignals(True)
            edit.setText(localize_probe_location(saved_txt, i))
            edit.setPlaceholderText(
                _t("probe_loc_%d" % i) if i <= 3 else _t("probe_loc_n", n=i + 1)
            )
            edit.setToolTip(_t("tip_probe_locations"))
            edit.blockSignals(False)
        labels = getattr(self, "probe_location_slot_labels", None) or []
        for i, lbl in enumerate(labels):
            if lbl is not None:
                lbl.setText(_t("probe_num", n=i + 1))

    def _master_tcp_client_ids(self):
        """主控 socket（含尚未打上 master_client_id 的同 IP 会话）不计入探头。"""
        out = set()
        worker = getattr(self, "worker", None)
        if isinstance(worker, MultiPortTcpPacketWorker):
            master_child = getattr(worker, "_master", None)
            if master_child is not None:
                out.update(getattr(master_child, "client_sockets", {}) or {})
        mc = getattr(self, "master_client_id", None)
        if not mc and worker is not None:
            mc = getattr(worker, "master_client_id", None)
        if mc:
            out.add(mc)
        master_ip = str(getattr(self, "_last_master_ip", "") or "")
        if worker is not None:
            for cid in (getattr(worker, "client_infos", None) or {}):
                if mc and cid == mc:
                    out.add(cid)
                    continue
                if master_ip and self._extract_client_ip(cid) == master_ip:
                    out.add(cid)
        return list(out)

    def get_online_probe_client_ids(self, fresh_sec: float = 12.0):
        """
        当前有效在线探头（按 IP 去重）。
        优先：TCP client_infos 中近期有活动的连接；避免幽灵会话把台数抬高。
        """
        import time as _time
        now = _time.time()
        candidates = []

        if self.config.tcp_enabled and hasattr(self, "worker") and self.worker is not None:
            infos = getattr(self.worker, "client_infos", None) or {}
            last_pkt = {}
            if getattr(self, "diagnostics_manager", None) is not None:
                last_pkt = getattr(self.diagnostics_manager, "last_packet_time", None) or {}

            for cid, info in infos.items():
                last_active = float(getattr(info, "last_active", 0) or 0)
                pkt_t = float(last_pkt.get(cid, 0) or 0)
                newest = max(last_active, pkt_t)
                if newest <= 0:
                    # 刚连上、尚未刷新时间戳
                    candidates.append(cid)
                elif (now - newest) <= fresh_sec:
                    candidates.append(cid)

            # 兜底：有实时 client_data 且仍在 infos 里
            for cid in list(getattr(self, "client_data", None) or {}):
                if cid in infos and cid not in candidates:
                    candidates.append(cid)

            if not candidates and infos:
                # 极端情况：时间戳全异常时仍按当前 socket 计（去重后）
                candidates = list(infos.keys())
        elif getattr(self, "worker", None) is not None and getattr(self.worker, "is_running", False):
            return ["serial_client"]

        master_ignore = set(self._master_tcp_client_ids())
        master_ip = str(getattr(self, "_last_master_ip", "") or "")
        by_ip = {}
        for cid in candidates:
            if cid in master_ignore:
                continue
            ip = self._extract_client_ip(cid) if hasattr(self, "_extract_client_ip") else ""
            if master_ip and ip == master_ip:
                continue
            key = ip or cid
            by_ip[key] = cid
        return list(by_ip.values())

    def apply_expected_probe_count(self, n: int, source: str = "manual"):
        """写入期望探头数，并立即按新期望清理幽灵故障/编号。"""
        try:
            n = max(0, min(16, int(n)))
        except (TypeError, ValueError):
            n = 0
        self.config.update_settings(expected_probe_count=n)
        self.config.save_settings()
        if hasattr(self, "expected_probe_spin"):
            self.expected_probe_spin.blockSignals(True)
            self.expected_probe_spin.setValue(n)
            self.expected_probe_spin.blockSignals(False)
        if hasattr(self, "_rebuild_probe_location_edits"):
            self._rebuild_probe_location_edits()

        online = self.get_online_probe_client_ids()
        if getattr(self, "diagnostics_manager", None) is not None:
            dm = self.diagnostics_manager
            # 峰值对齐为当前期望，避免旧 peak=3 继续误导
            dm.peak_connected_count = n if n > 0 else len(online)
            online_set = set(online)
            known = set(dm.active_faults.keys()) | set(dm.last_packet_time.keys())
            for cid in list(known):
                if cid == "system":
                    continue
                if cid not in online_set:
                    # 用户已确认/改定期望且在线数达标 → 清掉全部离线幽灵故障
                    if n <= 0 or len(online) >= n:
                        dm.remove_client(cid)
            if n <= 0 or len(online) >= n:
                dm.remove_fault("system", "E101")
            # 若在线仍不足期望，周期检查会再报 E101/E102

        if hasattr(self, "prune_disconnected_probe_labels"):
            self.prune_disconnected_probe_labels(online)
        if hasattr(self, "update_system_status"):
            self.update_system_status()
        page = getattr(self, "home_page", None)
        if page is not None and not getattr(page, "_had_tile_data", False):
            if hasattr(page, "_apply_empty_probe_placeholders"):
                page._apply_empty_probe_placeholders()
        self.log(
            f"Expected probe count={n} via {source}; online_now={len(online)}",
            'INFO'
        )

    def adopt_current_probe_count(self):
        """调试/开通：把当前有效在线探头数写入期望值，并立刻清幽灵故障。"""
        online = self.get_online_probe_client_ids()
        n = len(online)
        if n <= 0:
            self.log("Adopt probe count failed: no online probes detected", 'WARNING')
            return
        self.apply_expected_probe_count(n, source="adopt")
        self.log(f"Adopted online probes as expected: {n} -> {online}", 'INFO')
    
    def update_comm_settings_visibility(self):
        """Update visibility of communication settings based on current configuration"""
        tcp_enabled = self.config.tcp_enabled
        multi = bool(tcp_enabled and getattr(self.config, "tcp_multi_port", False))
        
        # Show/hide TCP-specific settings
        self.tcp_host_input.setVisible(tcp_enabled)
        if hasattr(self, "tcp_multi_port_checkbox"):
            self.tcp_multi_port_checkbox.setVisible(tcp_enabled)
        single_port = tcp_enabled and not multi
        self.server_port_label.setVisible(single_port)
        self.tcp_port_spin.setVisible(single_port)
        for name in (
            "tcp_port_master_label",
            "tcp_port_master_spin",
            "tcp_port_probe_label",
            "tcp_port_probe_spin",
        ):
            w = getattr(self, name, None)
            if w is not None:
                w.setVisible(multi)
        
        # Show/hide serial settings (only visible in serial/USB mode)
        serial_visible = not tcp_enabled
        self.serial_port_label.setVisible(serial_visible)
        self.serial_port_combo.setVisible(serial_visible)
        self.refresh_serial_btn.setVisible(serial_visible)
        self.reconnect_serial_btn.setVisible(serial_visible)
        self.baudrate_label.setVisible(serial_visible)
        self.baudrate_combo.setVisible(serial_visible)
        
        # Update placeholder text
        if tcp_enabled:
            self.tcp_host_input.setPlaceholderText("Bind address (0.0.0.0 for all interfaces)")
    
    def closeEvent(self, event):
        try:
            if getattr(self, "auto_save_enabled", False):
                # 先停读再刷盘，避免写盘期间队列里的谱包进不了最后一次保存
                try:
                    w = getattr(self, "worker", None)
                    if w is not None:
                        w.stop_reading()
                    self._stop_read_timer_sync()
                except Exception:
                    pass
                try:
                    QApplication.processEvents()
                except Exception:
                    pass
                self._auto_save_all_clients(force=True, blocking=True)
                try:
                    QApplication.processEvents()
                except Exception:
                    pass
                if self._clients_with_saveable_archive():
                    self._auto_save_all_clients(force=True, blocking=True)
        except Exception as e:
            self.log("Final auto-save on close failed: %s" % e, "WARNING")
        self._wait_autosave_worker(timeout=120.0)
        for name in (
            "plot_timer",
            "master_watchdog_timer",
            "auto_save_timer",
            "device_mon_timer",
            "_idle_home_timer",
            "_secret_hold_timer",
        ):
            try:
                t = getattr(self, name, None)
                if t is not None:
                    self._qtimer_invoke(t, "stop", blocking=True)
            except Exception:
                pass
        w = getattr(self, "worker", None)
        try:
            if w is not None:
                if is_tcp_worker(w):
                    self._shutdown_tcp_worker_blocking(w)
                else:
                    self._detach_read_timer_to_gui_thread()
                    w.stop_reading()
                    if isinstance(w, SerialPacketWorker):
                        w.disconnect_serial()
            else:
                self._detach_read_timer_to_gui_thread()
        except Exception:
            pass

        self.worker_thread.quit()
        self.worker_thread.wait(5000)
        if self.raw_logger:
            self.raw_logger.close()
        event.accept()

    def reset_plots(self):
        # Reset spectrum data with current config adc_channels
        self.spectrum_data = np.zeros(self.config.adc_channels)
        self.client_time_series = {}
        self.client_spectrum_data = {}
        self.client_latest_packets = {}
        self.primary_client_id = None
        # Reset spectrogram buffer with current config adc_channels
        self.spectro_buffer_data = np.zeros((MAX_SPECTRUM_STORED, self.config.adc_channels))
        self.spectro_buffer_time = []

        # Reset all curves
        self.curve_cps.setData([],[])

    # Device control methods (根据参考代码添加)
    def _current_probe_live_product_id(self, client_id: str = None):
        cid = client_id or self.primary_client_id
        pkt = self.client_latest_packets.get(cid) if cid else None
        if pkt is not None:
            try:
                return int(getattr(pkt, "product_id", 0) or 0)
            except (TypeError, ValueError):
                pass
        data = self.client_data.get(cid) if cid else None
        if data:
            try:
                return int(data.get("product_id", 0) or 0)
            except (TypeError, ValueError):
                pass
        return 0

    def _product_id_spin_device_sync_allowed(self, client_id: str = None) -> bool:
        """维护编辑/等待写回期间，不要用谱包里的 product_id 覆盖 spin。"""
        pending = getattr(self, "_pending_product_id_write", None)
        if pending:
            age = time.time() - float(pending.get("requested_at", 0.0) or 0.0)
            if age <= 8.0:
                return False
        spin = getattr(self, "product_id_spin", None)
        if spin is not None:
            try:
                if spin.hasFocus():
                    return False
            except Exception:
                pass
        key = self._current_probe_key(client_id)
        if not key:
            return True
        live_pid = self._current_probe_live_product_id(client_id)
        state = self.config.get_product_id_state(key, live_product_id=live_pid)
        # 仅「已锁定、不可写」时把 spin 当作设备 ID 的只读镜像；可写期间不覆盖用户输入
        if state.get("unlocked") or not state.get("locked"):
            return False
        return True

    def _refresh_product_id_lock_ui(self, client_id: str = None):
        label = getattr(self, "product_id_lock_label", None)
        spin = getattr(self, "product_id_spin", None)
        write_btn = getattr(self, "product_id_write_btn", None)
        unlock_btn = getattr(self, "product_id_unlock_btn", None)
        if label is None:
            return
        panel_cid = self._product_id_panel_client_id(client_id)
        key = self._current_probe_key(panel_cid)
        live_pid = self._current_probe_live_product_id(panel_cid)
        state = self.config.get_product_id_state(key, live_product_id=live_pid) if key else {"locked": True, "unlocked": False}
        pending_info = getattr(self, "_pending_product_id_write", None)
        if pending_info and (time.time() - float(pending_info.get("requested_at", 0.0) or 0.0)) > 8.0:
            pending_info = None
            self._pending_product_id_write = None
        pending = bool(pending_info)
        if pending:
            new_text = _t("status_product_id_pending")
            new_style = "color: #888888; font-size: 11px;"
        elif state["unlocked"]:
            new_text = _t("status_product_id_unlocked")
            new_style = "color: #ffb74d; font-size: 11px;"
        elif state["locked"]:
            new_text = _t("status_product_id_locked")
            new_style = "color: #888888; font-size: 11px;"
        else:
            new_text = _t("status_product_id_unset")
            new_style = "color: #4caf50; font-size: 11px;"
        can_write = bool(state["unlocked"] or (not state["locked"]))
        ui_sig = (str(key), bool(pending), bool(state["locked"]), bool(state["unlocked"]), bool(can_write))
        if ui_sig == getattr(self, "_product_id_lock_ui_sig", None):
            return
        self._product_id_lock_ui_sig = ui_sig
        if label.text() != new_text or label.styleSheet() != new_style:
            label.setText(new_text)
            label.setStyleSheet(new_style)
        spin_enabled = can_write and not pending and (spin.isVisible() if spin is not None else False)
        write_enabled = can_write and not pending and (write_btn.isVisible() if write_btn is not None else False)
        unlock_enabled = state["locked"] and not pending and (unlock_btn.isVisible() if unlock_btn is not None else False)
        if spin is not None and spin.isEnabled() != spin_enabled:
            spin.setEnabled(spin_enabled)
        if write_btn is not None and write_btn.isEnabled() != write_enabled:
            write_btn.setEnabled(write_enabled)
        if unlock_btn is not None and unlock_btn.isEnabled() != unlock_enabled:
            unlock_btn.setEnabled(unlock_enabled)

    def _apply_product_id_readback(self, client_id: str, product_id: int):
        pending = getattr(self, "_pending_product_id_write", None) or {}
        want_cid = pending.get("client_id")
        want_pid = pending.get("product_id")
        if want_cid is None or want_pid is None:
            self._refresh_product_id_lock_ui(client_id)
            return
        cid = client_id or "serial_client"
        if want_cid != cid or int(product_id) != int(want_pid):
            self._refresh_product_id_lock_ui(client_id)
            return
        key = self._current_probe_key(cid)
        if key:
            self._save_probe_panel_settings(client_id=cid, product_id=int(product_id))
            self.config.set_product_id_state(key, locked=True, unlocked=False)
            self.config.save_settings()
        self._pending_product_id_write = None
        self._product_id_lock_ui_sig = None
        if hasattr(self, "product_id_spin"):
            self.product_id_spin.blockSignals(True)
            self.product_id_spin.setValue(int(product_id))
            self.product_id_spin.blockSignals(False)
        self._refresh_product_id_lock_ui(cid)
        self.log(_t("msg_product_id_set_ok", pid=int(product_id)), "INFO")

    def unlock_product_id_edit(self):
        panel_cid = self._product_id_panel_client_id()
        key = self._current_probe_key(panel_cid)
        if not key:
            return False
        if panel_cid:
            self._pinned_product_id_client_id = panel_cid
        self._product_id_lock_ui_sig = None
        self.config.set_product_id_state(key, locked=True, unlocked=True)
        self.config.save_settings()
        self._refresh_product_id_lock_ui(panel_cid)
        return True

    def set_product_id(self):
        if self.ensure_serial_ready():
            product_id = self.product_id_spin.value()
            target_client = self.primary_client_id if self.primary_client_id else "serial_client"
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'set_product_id', product_id)
                    if success:
                        self.log(f"Set product ID command sent to client {self.primary_client_id}: {product_id}")
                    else:
                        self.log(f"Failed to send product ID command to client {self.primary_client_id}", 'ERROR')
                else:
                    success = self.worker.set_product_id(product_id)
                    if success:
                        self.log(f"Set product ID command sent: {product_id}")
                    else:
                        self.log("Failed to send set product ID command", "ERROR")
            else:
                success = self.worker.set_product_id(product_id)
                if success:
                    self.log(f"Set product ID command sent: {product_id}")
                else:
                    self.log("Failed to send set product ID command", "ERROR")
            if success:
                self._pending_product_id_write = {
                    "client_id": target_client,
                    "product_id": int(product_id),
                    "requested_at": time.time(),
                }
                self._refresh_product_id_lock_ui(target_client)
                return True
        return False
    
    def read_product_id(self):
        if self.ensure_serial_ready():
            success = self.worker.read_product_id(True)
            if success:
                self.log("Read product ID command sent")
            else:
                self.log("Failed to send read product ID command", "ERROR")
            return bool(success)
        return False
    
    def set_sensitivity_coefficient(self):
        from core.sensitivity_m import clamp_m, format_m_display

        coefficient = self._read_spinbox_value(self.sensitivity_spin, self.sensitivity_spin.value())
        try:
            m = clamp_m(coefficient)
            self.sensitivity_spin.setValue(m)
            self._save_probe_panel_settings(sensitivity=m)
        except Exception:
            m = clamp_m(self.sensitivity_spin.value())
        disp = format_m_display(m)
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    probe_cid = (
                        self._get_probe_client_id_for_settings()
                        if hasattr(self, "_get_probe_client_id_for_settings")
                        else self.primary_client_id
                    ) or self.primary_client_id
                    success = self.worker.send_command_to_client(
                        probe_cid, 'set_sensitivity_coefficient', m
                    )
                    if success:
                        self.log(
                            f"Set sensitivity M sent to client {probe_cid}: {disp}"
                        )
                    else:
                        self.log(f"Failed to send sensitivity coefficient command to client {self.primary_client_id}", 'ERROR')
                else:
                    success = self.worker.set_sensitivity_coefficient(m)
                    if success:
                        self.log(f"Set sensitivity M sent: {disp}")
                    else:
                        self.log("Failed to send set sensitivity coefficient command", "ERROR")
            else:
                success = self.worker.set_sensitivity_coefficient(m)
                if success:
                    self.log(f"Set sensitivity M sent: {disp}")
                else:
                    self.log("Failed to send set sensitivity coefficient command", "ERROR")
        else:
            self.log("Connection not ready, sensitivity saved locally only", 'WARNING')
    
    def read_sensitivity_coefficient(self):
        if self.ensure_serial_ready():
            if self.config.tcp_enabled and self.primary_client_id and hasattr(
                self.worker, "send_command_to_client"
            ):
                probe_cid = self._get_probe_client_id_for_settings() if hasattr(
                    self, "_get_probe_client_id_for_settings"
                ) else self.primary_client_id
                if not probe_cid:
                    probe_cid = self.primary_client_id
                success = self.worker.send_command_to_client(
                    probe_cid, "read_sensitivity_coefficient", True
                )
            else:
                success = self.worker.read_sensitivity_coefficient(True)
            if success:
                self.log("Read sensitivity coefficient command sent")
            else:
                self.log("Failed to send read sensitivity coefficient command", "ERROR")
    
    def control_single_relay(self, relay_num: int, state: bool):
        """Probe relay 0x06 — must target a probe, never the master."""
        def _revert():
            cbs = (self.relay0_checkbox, self.relay1_checkbox, self.relay2_checkbox)
            if 0 <= int(relay_num) <= 2:
                cb = cbs[int(relay_num)]
                cb.blockSignals(True)
                cb.setChecked(not bool(state))
                cb.blockSignals(False)

        if not self.ensure_serial_ready():
            _revert()
            return False

        if self.config.tcp_enabled:
            probe_cid = self._get_probe_client_id_for_settings()
            if not probe_cid:
                self.log("No probe selected — cannot control probe relay", "ERROR")
                _revert()
                return False
            if not hasattr(self.worker, "send_command_to_client"):
                self.log("Worker cannot send targeted TCP commands", "ERROR")
                _revert()
                return False
            ok = self.worker.send_command_to_client(
                probe_cid, "control_single_relay", (int(relay_num), bool(state))
            )
            if ok:
                self._pending_probe_relay_cmd = time.time()
                self._probe_relay_hold_until = time.time() + 2.0
                self.log(
                    "Probe relay %d → %s (0x06) via %s"
                    % (int(relay_num), "ON" if state else "OFF", probe_cid)
                )
            else:
                self.log("Failed to send probe relay 0x06", "ERROR")
                _revert()
            return ok

        ok = self.worker.control_single_relay(relay_num, state)
        if ok:
            self._probe_relay_hold_until = time.time() + 2.0
            self.log("Control relay %d command sent: %s" % (relay_num, "ON" if state else "OFF"))
        else:
            self.log("Failed to send control relay %d command" % relay_num, "ERROR")
            _revert()
        return ok
    
    def read_relay_status(self):
        """Probe relay read 0x12 — targeted to current probe only (not broadcast)."""
        if not self.ensure_serial_ready():
            return False
        if self.config.tcp_enabled:
            probe_cid = self._get_probe_client_id_for_settings()
            if not probe_cid:
                self.log("No probe selected — cannot read probe relay", "ERROR")
                return False
            ok = self.worker.send_command_to_client(probe_cid, "read_relay_status", True)
            if ok:
                self._pending_probe_relay_cmd = time.time()
                self.log("Probe relay status read (0x12) via %s" % probe_cid)
            else:
                self.log("Failed to send probe relay 0x12", "ERROR")
            return ok
        ok = self.worker.read_relay_status(True)
        if ok:
            self.log("Read relay status command sent")
        else:
            self.log("Failed to send read relay status command", "ERROR")
        return ok

    def _get_probe_client_id_for_settings(self):
        """Current settings target: primary probe, never master."""
        master_cid = self._get_master_client_id()
        cid = getattr(self, "primary_client_id", None)
        if cid and cid != master_cid:
            return cid
        if hasattr(self, "get_online_probe_client_ids"):
            probes = self.get_online_probe_client_ids()
            if probes:
                return probes[0]
        return None

    def _get_master_client_id(self):
        cid = getattr(self, "master_client_id", None)
        if not cid and getattr(self, "worker", None) is not None:
            cid = getattr(self.worker, "master_client_id", None)
        return cid

    def _clear_master_sessions_from_probe_faults(self, client_id: str = None):
        """Drop probe E101/E102 on the master IP.

        A master socket that disconnects before the L2 header is seen is labeled
        as a probe. A later session from the same IP (new port) must clear that
        sticky fault, not only the current client id.
        """
        if client_id:
            self._remember_master_endpoint(client_id)
        ip = str(getattr(self, "_last_master_ip", "") or "")
        if client_id and not ip and hasattr(self, "_extract_client_ip"):
            parsed = str(self._extract_client_ip(client_id) or "")
            if parsed and parsed not in ("serial", client_id):
                ip = parsed
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not hasattr(dm, "remove_client"):
            return
        ids = set()
        if client_id:
            ids.add(client_id)
        if ip:
            known = set(getattr(dm, "active_faults", {}) or {}) | set(
                getattr(dm, "last_packet_time", {}) or {}
            )
            for cid in known:
                if cid in ("system", "master"):
                    continue
                other = ""
                if hasattr(self, "_extract_client_ip"):
                    other = str(self._extract_client_ip(cid) or "")
                if other == ip:
                    ids.add(cid)
        for cid in ids:
            try:
                dm.remove_client(cid)
            except Exception:
                pass
        if ip and hasattr(self, "forget_probe_ip"):
            self.forget_probe_ip(ip)
        if hasattr(self, "update_system_status"):
            try:
                self.update_system_status()
            except Exception:
                pass

    def _remember_master_endpoint(self, client_id: str):
        """Keep last master peer IP from the TCP socket / client_id."""
        if not client_id:
            return
        ip = ""
        worker = getattr(self, "worker", None)
        if worker is not None:
            info = (getattr(worker, "client_infos", None) or {}).get(client_id)
            if info is not None:
                ip = str(getattr(info, "ip_address", "") or "")
        if not ip and hasattr(self, "_extract_client_ip"):
            parsed = self._extract_client_ip(client_id)
            if parsed and parsed not in ("serial", client_id):
                ip = parsed
        if ip:
            self._last_master_ip = ip

    def get_master_display_ip(self) -> str:
        cid = self._get_master_client_id()
        if cid:
            self._remember_master_endpoint(cid)
        return str(getattr(self, "_last_master_ip", "") or "")

    def control_master_relay(self, relay_num: int, state: bool):
        """
        Master single relay — same UX as probe checkbox:
          55 AA 03 06 [relay_num=0|1|2] [0/1] [xor]
        """
        def _revert():
            cbs = (
                self.master_relay0_checkbox,
                self.master_relay1_checkbox,
                self.master_relay2_checkbox,
            )
            if 0 <= int(relay_num) <= 2:
                cb = cbs[int(relay_num)]
                cb.blockSignals(True)
                cb.setChecked(not bool(state))
                cb.blockSignals(False)

        if int(relay_num) not in (0, 1, 2):
            self.log("Master relay number must be 0-2", "ERROR")
            _revert()
            return False
        if int(relay_num) == 1:
            from core.translation import _t
            self.log(_t("log_master_relay1_ignore"), "WARNING")
            _revert()
            return False
        if not self.config.tcp_enabled:
            self.log("Master relay control requires TCP mode", "ERROR")
            _revert()
            return False
        if not self.ensure_serial_ready():
            _revert()
            return False
        master_cid = self._get_master_client_id()
        if not master_cid:
            self.log("Master not connected — cannot control relay", "ERROR")
            _revert()
            return False
        if not hasattr(self.worker, "send_command_to_client"):
            self.log("Worker cannot send targeted TCP commands", "ERROR")
            _revert()
            return False
        ok = self.worker.send_command_to_client(
            master_cid, "control_single_relay", (int(relay_num), bool(state))
        )
        if ok:
            self._pending_master_relay_cmd = time.time()
            self._pending_master_relay_num = int(relay_num)
            self.log(
                "Master relay %d → %s (0x06) via %s"
                % (int(relay_num), "ON" if state else "OFF", master_cid)
            )
        else:
            self.log("Failed to send master relay 0x06 command", "ERROR")
            _revert()
        return ok

    def _master_relay_draft_mask(self) -> int:
        mask = 0
        if getattr(self, "master_relay0_checkbox", None) and self.master_relay0_checkbox.isChecked():
            mask |= 0x01
        if getattr(self, "master_relay1_checkbox", None) and self.master_relay1_checkbox.isChecked():
            mask |= 0x02
        if getattr(self, "master_relay2_checkbox", None) and self.master_relay2_checkbox.isChecked():
            mask |= 0x04
        return mask & 0x07

    def _refresh_master_relay_draft_mask(self, *_args):
        pass  # kept for compatibility; UI no longer shows draft mask

    def apply_master_relay_mask(self):
        """Optional batch 0x11 from current checkbox states (same mask bits as protocol).

        注意：mask bit0=0 会触发通道消警（仅断 R0）；不向固件写 R1（故障自动）。
        """
        from core.translation import _t
        from PyQt5.QtWidgets import QMessageBox

        if not self.config.tcp_enabled:
            self.log("Master relay control requires TCP mode", "ERROR")
            return False
        if not self.ensure_serial_ready():
            return False
        master_cid = self._get_master_client_id()
        if not master_cid:
            self.log("Master not connected — cannot control relay mask", "ERROR")
            return False
        mask = self._master_relay_draft_mask() & ~0x02  # R1 故障独占，不下发 bit1
        if (mask & 0x01) == 0:
            reply = QMessageBox.question(
                self if isinstance(self, QWidget) else None,
                _t("msg_relay0_off_title"),
                _t("msg_mask_bit0_clear_text"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False
        if not hasattr(self.worker, "send_command_to_client"):
            self.log("Worker cannot send targeted TCP commands", "ERROR")
            return False
        ok = self.worker.send_command_to_client(
            master_cid, "control_multiple_relays", mask
        )
        if ok:
            self._pending_master_relay_cmd = time.time()
            self._pending_master_relay_num = None
            self.log("Master relay mask 0x%02X (0x11) via %s" % (mask, master_cid))
        else:
            self.log("Failed to send master relay 0x11 command", "ERROR")
        return ok

    def force_open_master_gate(self):
        """新固件无报警开闸 override；保留接口以免旧 UI 调用崩溃。"""
        from core.translation import _t
        from PyQt5.QtWidgets import QMessageBox

        QMessageBox.information(
            self if isinstance(self, QWidget) else None,
            _t("msg_force_gate_title"),
            _t("msg_force_gate_text"),
        )
        return False

    def read_master_relay_status(self):
        """Read master multi-relay status via TCP 0x12."""
        if not self.config.tcp_enabled:
            self.log("Master relay read requires TCP mode", "ERROR")
            return False
        if not self.ensure_serial_ready():
            return False
        master_cid = self._get_master_client_id()
        if not master_cid:
            self.log("Master not connected — cannot read relay", "ERROR")
            return False
        ok = self.worker.send_command_to_client(
            master_cid, "read_relay_status", True
        )
        if ok:
            self._pending_master_relay_cmd = time.time()
            self._pending_master_relay_num = None
            self.log("Master relay status read (0x12) via %s" % master_cid)
        else:
            self.log("Failed to send master relay 0x12 command", "ERROR")
        return ok

    def _sync_master_relay_status_after_06(self):
        """Internal follow-up 0x12 after single-relay ack (no extra UI prompts)."""
        try:
            UIBase.read_master_relay_status(self)
        except Exception:
            pass

    def _set_master_relay_bit_ui(self, relay_num: int, on: bool):
        """Update one master relay checkbox from 0x06 ack (value is 0/1)."""
        from core.translation import _t
        cbs = (
            self.master_relay0_checkbox,
            self.master_relay1_checkbox,
            self.master_relay2_checkbox,
        )
        if int(relay_num) not in (0, 1, 2):
            return
        cb = cbs[int(relay_num)]
        cb.blockSignals(True)
        cb.setChecked(bool(on))
        cb.blockSignals(False)
        states = list(getattr(self, "master_relay_states", None) or (False, False, False))
        while len(states) < 3:
            states.append(False)
        states[int(relay_num)] = bool(on)
        self.master_relay_states = tuple(states)
        mask = (int(states[0]) & 1) | ((int(states[1]) & 1) << 1) | ((int(states[2]) & 1) << 2)
        self.master_relay_status_label.setText(
            _t(
                "master_relay_status_format",
                r0=int(states[0]),
                r1=int(states[1]),
                r2=int(states[2]),
                mask=mask,
            )
        )

    def _apply_master_relay_mask_to_ui(self, mask: int):
        """Update master relay checkboxes/status from 3-bit mask (0x11/0x12)."""
        from core.translation import _t

        mask = int(mask) & 0x07
        r0 = bool(mask & 0x01)
        r1 = bool(mask & 0x02)
        r2 = bool(mask & 0x04)
        self.master_relay_states = (r0, r1, r2)
        for cb, st in (
            (self.master_relay0_checkbox, r0),
            (self.master_relay1_checkbox, r1),
            (self.master_relay2_checkbox, r2),
        ):
            cb.blockSignals(True)
            cb.setChecked(st)
            cb.blockSignals(False)
        self.master_relay_status_label.setText(
            _t("master_relay_status_format", r0=int(r0), r1=int(r1), r2=int(r2), mask=mask)
        )
        self._refresh_master_relay_draft_mask()
    
    def read_alarm_status(self):
        if self.ensure_serial_ready():
            success = self.worker.read_alarm_status(True)
            if success:
                self.log("Read alarm status command sent")
            else:
                self.log("Failed to send read alarm status command", "ERROR")
    
    def update_device_status_from_packet(self, packet: SpectrumPacket, client_id: str = None, log_alarm: bool = True):
        """
        从数据包更新设备状态显示
        这个方法可以从on_spectrum_packet_received中调用
        
        Args:
            packet: 数据包
            client_id: 客户端ID，如果为None或与当前主要客户端匹配则更新显示
        """
        # 只更新当前主要客户端的参数显示，避免参数跳变
        if client_id is None or client_id == self.primary_client_id:
            # 更新产品ID显示
            self.product_id_label.setText(f"{packet.product_id}")
            panel_cid = self._product_id_panel_client_id(client_id)
            if panel_cid and client_id == panel_cid and hasattr(self, "product_id_spin"):
                if self._product_id_spin_device_sync_allowed(panel_cid):
                    self.product_id_spin.blockSignals(True)
                    self.product_id_spin.setValue(int(packet.product_id))
                    self.product_id_spin.blockSignals(False)
            
            from core.sensitivity_m import format_m_display

            panel_cid = self._product_id_panel_client_id(client_id)
            if panel_cid is None or client_id is None or client_id == panel_cid:
                m_show = self._display_sensitivity_m(client_id, packet)
                self.sensitivity_label.setText(format_m_display(m_show))
            
            # 更新继电器状态显示（用户刚操作后短时不覆盖勾选，避免跳变）
            relay0_state = (packet.device_status & 0b00001) != 0
            relay1_state = (packet.device_status & 0b00010) != 0
            relay2_state = (packet.device_status & 0b00100) != 0
            hold = time.time() < float(getattr(self, "_probe_relay_hold_until", 0) or 0)
            if not hold:
                self.relay0_checkbox.blockSignals(True)
                self.relay0_checkbox.setChecked(relay0_state)
                self.relay0_checkbox.blockSignals(False)
                
                self.relay1_checkbox.blockSignals(True)
                self.relay1_checkbox.setChecked(relay1_state)
                self.relay1_checkbox.blockSignals(False)
                
                self.relay2_checkbox.blockSignals(True)
                self.relay2_checkbox.setChecked(relay2_state)
                self.relay2_checkbox.blockSignals(False)
            
                self.relay_states = (relay0_state, relay1_state, relay2_state)
                relay_status_text = _t("relay_status_format", r0=int(relay0_state), r1=int(relay1_state), r2=int(relay2_state))
                self.relay_status_label.setText(relay_status_text)
            else:
                # still refresh text from last known user intent if available
                states = getattr(self, "relay_states", None)
                if states is not None and len(states) >= 3:
                    relay_status_text = _t(
                        "relay_status_format",
                        r0=int(states[0]), r1=int(states[1]), r2=int(states[2]),
                    )
            self.relay_status_label.setText(relay_status_text)
            
            # 更新报警状态
            remote_sig_alarm = (packet.device_status & 0b10000) != 0
            alarm_status = "ACTIVE" if remote_sig_alarm else "INACTIVE"
            self.alarm_status_label.setText(f"{alarm_status}")
            
            # 根据报警状态设置颜色：无报警绿色，有报警红色
            if remote_sig_alarm:
                # 有报警：红色背景
                self.alarm_status_label.setStyleSheet("background-color: #ffcccc; color: #000000;")
            else:
                # 无报警：绿色背景
                self.alarm_status_label.setStyleSheet("background-color: #ccffcc; color: #000000;")
            
            # 原「实时概览」仍用探头 bit；公共「主显示」单独吃主控 L2
            if self.alarm_status_callback is not None:
                self.alarm_status_callback(remote_sig_alarm)

            # 注意：报警事件的记录已移至 on_spectrum_packet_received，对每个客户端独立
            # 进行边沿检测与记录，不再受“仅主客户端”限制，确保多 IP 设备的报警都能进记录表。

            # 更新计数器显示
            self.counter_label.setText(f"{packet.counter}")
    
    def update_client_data(self, client_id: str, packet: SpectrumPacket):
        """
        更新客户端数据
        Args:
            client_id: 客户端ID
            packet: 数据包
        """
        current_time = time.time()
        sens_m = self._display_sensitivity_m(client_id, packet)
        client_data = {
            'hv': packet.HV,
            'rates': packet.counter,  # 计数率（cps）
            'temp': packet.temperature / 100.0,  # 温度（°C）
            'last_update': current_time,
            'alarm': (packet.device_status & 0b10000) != 0,  # 报警状态
            'client_id': client_id,
            'product_id': packet.product_id,
            'sensitivity': sens_m,
            'sen_coef_round': int(packet.sen_coef),
        }
        
        self.client_data[client_id] = client_data
        self._remember_probe(client_id, packet.product_id)
        self._apply_product_id_readback(client_id, packet.product_id)
        
        # 清理过期的客户端数据（30秒无更新）；编号登记表按 IP 保留，不断线丢失
        expired_clients = []
        for cid, data in self.client_data.items():
            if current_time - data['last_update'] > 30:  # 30秒超时
                expired_clients.append(cid)
        
        for cid in expired_clients:
            del self.client_data[cid]

    def _maybe_log_all_probe_cps(self, interval_sec=10.0):
        """Throttle a human-readable per-probe CPS line into daq_log."""
        try:
            now = time.time()
            last = float(getattr(self, "_last_probe_cps_log_at", 0.0) or 0.0)
            if now - last < float(interval_sec):
                return
            master = getattr(self, "master_client_id", None)
            parts = []
            for cid, data in (getattr(self, "client_data", None) or {}).items():
                if not cid or cid in ("system", "master") or (master and cid == master):
                    continue
                meta = self._export_probe_meta(cid)
                label = meta.get("label") or cid
                loc = str(meta.get("location") or "").replace(" ", "")
                try:
                    cps = int(float((data or {}).get("rates") or 0))
                except (TypeError, ValueError):
                    cps = 0
                if loc:
                    parts.append("%s/%s %d" % (label, loc, cps))
                else:
                    parts.append("%s %d" % (label, cps))
            slot_txt = ""
            pkt = getattr(self, "latest_master_summary", None)
            if pkt is not None:
                n = int(getattr(pkt, "probe_count_cfg", 0) or 0) or 2
                slot_cps = list(getattr(pkt, "probe_cps", None) or [])[:n]
                if slot_cps:
                    # L2 index = hardware slot, not display-tile order after drag.
                    names = [
                        "slot%d=%d" % (i + 1, int(v or 0))
                        for i, v in enumerate(slot_cps)
                    ]
                    mask = int(getattr(pkt, "online_mask", 0) or 0)
                    tick = int(getattr(pkt, "timestamp_ms", 0) or 0)
                    slot_txt = " | L2: %s mask=0x%04X tick=%d" % (
                        ", ".join(names), mask, tick
                    )
            if not parts and not slot_txt:
                return
            self._last_probe_cps_log_at = now
            if parts:
                self.log("Probe CPS: " + " | ".join(parts) + slot_txt, "INFO")
            else:
                self.log("Probe CPS:" + slot_txt, "INFO")
        except Exception:
            return
    
    def calculate_total_count_rate(self):
        """计算所有客户端的计数率总和（根据用户要求，不再使用）"""
        total = 0
        for client_id, data in self.client_data.items():
            total += data['rates']
        self.total_count_rate = total
        return total
    
    def apply_primary_client_snapshot(self):
        """Immediately refresh all visible data for the selected client."""
        client_id = self.primary_client_id
        if not client_id:
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.clear_current_device_status_display()
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, self.client_data)
            return

        if client_id in self.client_spectrum_data:
            if self.spectrum_data.shape != self.client_spectrum_data[client_id].shape:
                self.spectrum_data = np.zeros_like(self.client_spectrum_data[client_id])
            self.spectrum_data = self.client_spectrum_data[client_id].copy()
        else:
            self.spectrum_data = np.zeros(self.config.adc_channels)

        latest_packet = self.client_latest_packets.get(client_id)
        if latest_packet is not None:
            self.current_stat = {
                'hv': latest_packet.HV,
                'rates': latest_packet.counter,
                'temp': latest_packet.temperature / 100.0
            }
            self.update_device_status_from_packet(latest_packet, client_id, log_alarm=False)
        elif client_id in self.client_data:
            data = self.client_data[client_id]
            self.current_stat = {
                'hv': data.get('hv', 0),
                'rates': data.get('rates', 0),
                'temp': data.get('temp', 0)
            }
        else:
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.clear_current_device_status_display()

        if self.data_updated_callback is not None:
            self.data_updated_callback(self.current_stat, 0, self.client_data)

        # 切换探头时，设置面板恢复该探头此前保存的高压/触发/灵敏度等
        self.load_probe_panel_settings(client_id)

        if len(self.channels) != len(self.spectrum_data) + 1:
            self.channels = np.arange(len(self.spectrum_data) + 1)
        self.curve_spectrum.setData(self.channels, self.spectrum_data)

    def set_primary_client(self, client_id: str):
        """
        设置主要客户端，该客户端的数据将显示在计数率曲线和能谱曲线中
        Args:
            client_id: 要设置为主要客户端的客户端ID
        """
        if client_id in self.get_available_clients() or client_id in self.client_time_series:
            # 切换前先把当前面板数值记到旧探头，避免丢改动
            if self.primary_client_id and self.primary_client_id != client_id:
                try:
                    self._save_probe_panel_settings(
                        client_id=self.primary_client_id,
                        hv=self._read_spinbox_value(self.hv_spin, self.hv_spin.value()),
                        threshold=self._read_spinbox_value(self.threshold_spin, self.threshold_spin.value()),
                        sensitivity=self._read_spinbox_value(self.sensitivity_spin, self.sensitivity_spin.value()),
                    )
                except Exception:
                    pass

            old_primary = self.primary_client_id
            self.primary_client_id = client_id
            
            # Switch displayed spectrum data to the new primary client
            if client_id in self.client_spectrum_data:
                # Ensure displayed spectrum data has correct shape
                if self.spectrum_data.shape != self.client_spectrum_data[client_id].shape:
                    self.spectrum_data = np.zeros_like(self.client_spectrum_data[client_id])
                self.spectrum_data = self.client_spectrum_data[client_id].copy()
                self.log(f"Switched spectrum display to client {client_id}", 'INFO')
            else:
                # Initialize spectrum data for this client if not exists
                # Use default adc_channels from config
                self.client_spectrum_data[client_id] = np.zeros(self.config.adc_channels)
                self.spectrum_data = np.zeros(self.config.adc_channels)
                self.log(f"Initialized spectrum data for new primary client {client_id}", 'INFO')
            
            self.log(f"Switched primary client from {old_primary} to {client_id}", 'INFO')
            
            # Update client selection combo box
            self.update_client_selection_combo()
            
            # 立即更新显示（含该探头面板参数）
            self.apply_primary_client_snapshot()
            self.update_data()
        else:
            self.log(f"Client {client_id} not found", 'WARNING')
    
    def get_available_clients(self):
        """
        获取所有可用客户端的列表
        Returns:
            list: 客户端ID列表
        """
        if self.config.tcp_enabled and is_tcp_worker(self.worker):
            connected_clients = self.worker.get_client_list()
            historical_clients = [
                client_id for client_id in self.client_time_series.keys()
                if client_id in connected_clients
            ]
            clients = list(dict.fromkeys(connected_clients + historical_clients))
            master_cid = getattr(self, "master_client_id", None)
            if not master_cid and getattr(self, "worker", None) is not None:
                master_cid = getattr(self.worker, "master_client_id", None)
            if master_cid:
                clients = [cid for cid in clients if cid != master_cid]
            return clients

        return list(self.client_time_series.keys())

    @staticmethod
    def _extract_client_ip(client_id: str) -> str:
        """Parse IP from ids like client_1_192.168.0.10:54321"""
        if not client_id or client_id == "system":
            return ""
        if client_id == "serial_client":
            return "serial"
        # Prefer trailing host:port
        if "_" in client_id:
            tail = client_id.split("_")[-1]
            if ":" in tail:
                return tail.split(":")[0]
            # dotted IP without port
            parts = tail.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return tail
        return client_id

    def _remember_probe(self, client_id: str, product_id=None) -> str:
        """Remember probe IP/index (and optional product_id). Returns IP or ''."""
        ip = self._extract_client_ip(client_id)
        if not ip or ip == "serial":
            return ip or ""

        if not hasattr(self, "_probe_ip_index") or self._probe_ip_index is None:
            self._probe_ip_index = {}
        if not hasattr(self, "_probe_registry") or self._probe_registry is None:
            self._probe_registry = {}

        if ip not in self._probe_ip_index:
            ips = sorted(set(list(self._probe_ip_index.keys()) + [ip]))
            self._probe_ip_index = {k: i + 1 for i, k in enumerate(ips)}

        entry = self._probe_registry.get(ip, {})
        entry["client_id"] = client_id
        if product_id is not None:
            try:
                pid = int(product_id)
                entry["product_id"] = pid
            except (TypeError, ValueError):
                pass
        self._probe_registry[ip] = entry
        return ip

    def _probe_client_is_live(self, client_id: str) -> bool:
        return (
            client_id in (getattr(self, "client_data", None) or {})
            or client_id in (getattr(self, "client_latest_packets", None) or {})
        )

    def _client_has_spectrum(self, client_id: str) -> bool:
        """是否已收到至少一帧能谱（E101 瞬间不用配置里的 product_id 当显示号）。"""
        if client_id in (getattr(self, "client_latest_packets", None) or {}):
            return True
        dm = getattr(self, "diagnostics_manager", None)
        if dm is not None:
            return float((getattr(dm, "last_packet_time", None) or {}).get(client_id, 0) or 0) > 0
        return False

    def _display_num_from_connected_probe_ips(self, ip: str) -> Optional[int]:
        if not ip or ip == "serial":
            return None
        if not hasattr(self, "get_online_probe_client_ids"):
            return None
        probe_ips = []
        for cid in self.get_online_probe_client_ids() or []:
            p_ip = self._extract_client_ip(cid)
            if p_ip and p_ip != "serial":
                probe_ips.append(p_ip)
        probe_ips = sorted(set(probe_ips))
        if ip in probe_ips:
            return probe_ips.index(ip) + 1
        return None

    def _resolve_probe_display_num(self, client_id: str) -> Optional[int]:
        """
        值班显示编号：在线时 product_id(唯一) 或 IP 序；离线沿用冻结的 display_num，
        不再单独用 product_id 造成「在线 1 号 / 离线 4 号」。
        """
        ip = self._extract_client_ip(client_id)
        live = self._probe_client_is_live(client_id)
        registry = getattr(self, "_probe_registry", None) or {}
        has_spec = self._client_has_spectrum(client_id)
        tcp_up_no_spec = (
            not has_spec
            and hasattr(self, "get_online_probe_client_ids")
            and client_id in (self.get_online_probe_client_ids() or [])
        )

        if ip and not live and not tcp_up_no_spec:
            try:
                frozen = registry.get(ip, {}).get("display_num")
                if frozen is not None:
                    return int(frozen)
            except (TypeError, ValueError):
                pass

        pid = self._resolve_product_id(client_id) if has_spec else None
        num = None
        if (
            has_spec
            and pid is not None
            and 1 <= pid <= 99
            and self._product_id_is_unique(pid)
        ):
            num = int(pid)
        elif ip:
            num = self._display_num_from_connected_probe_ips(ip)
        if num is None and ip and ip in (getattr(self, "_probe_ip_index", None) or {}):
            num = int(self._probe_ip_index[ip])

        if num is not None and ip:
            entry = dict(registry.get(ip, {}))
            entry["display_num"] = num
            if client_id:
                entry["client_id"] = client_id
            self._probe_registry[ip] = entry
        return num

    def _freeze_probe_display_num(self, client_id: str) -> None:
        """断线前冻结与本机一致的显示号，供 E102 等故障文案使用。"""
        if not client_id:
            return
        self._resolve_probe_display_num(client_id)

    def _resolve_product_id(self, client_id: str):
        data = self.client_data.get(client_id) or {}
        try:
            return int(data.get("product_id"))
        except (TypeError, ValueError):
            pass
        pkt = self.client_latest_packets.get(client_id)
        if pkt is not None:
            try:
                return int(getattr(pkt, "product_id", None))
            except (TypeError, ValueError):
                pass
        ip = self._extract_client_ip(client_id)
        if ip:
            pid = (getattr(self, "_probe_registry", {}) or {}).get(ip, {}).get("product_id")
            if pid is not None:
                try:
                    return int(pid)
                except (TypeError, ValueError):
                    pass
        return None

    def _product_id_is_unique(self, pid: int, online_ips=None) -> bool:
        """True only when this product_id maps to at most one *online* probe IP."""
        if online_ips is None:
            online_ips = set()
            for cid in (getattr(self, "client_data", None) or {}):
                ip = self._extract_client_ip(cid)
                if ip and ip != "serial":
                    online_ips.add(ip)
            if hasattr(self, "worker") and getattr(self, "config", None) and self.config.tcp_enabled:
                for cid in (getattr(self.worker, "client_infos", None) or {}):
                    ip = self._extract_client_ip(cid)
                    if ip and ip != "serial":
                        online_ips.add(ip)
        ips = set()
        for ip, info in (getattr(self, "_probe_registry", {}) or {}).items():
            if online_ips and ip not in online_ips:
                continue
            try:
                if int(info.get("product_id")) == pid:
                    ips.add(ip)
            except (TypeError, ValueError):
                continue
        for cid, data in (getattr(self, "client_data", None) or {}).items():
            try:
                if int(data.get("product_id")) == pid:
                    ip = self._extract_client_ip(cid)
                    if ip and (not online_ips or ip in online_ips):
                        ips.add(ip)
            except (TypeError, ValueError):
                continue
        ips.discard("")
        return len(ips) <= 1

    def get_probe_label(self, client_id: str) -> str:
        """
        Human label for a detector: '1号' / 'Probe 1' / ...
        - Prefer product_id only when it uniquely identifies one online probe.
        - Otherwise use stable IP order among online probes.
        - Offline faults reuse frozen display_num (same as when online).
        """
        if not client_id or client_id == "system":
            return ""

        if self._probe_client_is_live(client_id):
            self._remember_probe(client_id, self._resolve_product_id(client_id))

        num = self._resolve_probe_display_num(client_id)
        if num is not None:
            from core.translation import _t
            return _t("probe_num", n=num)
        return ""

    def forget_probe_ip(self, ip: str):
        """Remove one IP from probe numbering tables."""
        if not ip:
            return
        registry = getattr(self, "_probe_registry", None)
        if registry is not None:
            registry.pop(ip, None)
        index = getattr(self, "_probe_ip_index", None)
        if index is not None and ip in index:
            index.pop(ip, None)
            ips = sorted(index.keys())
            self._probe_ip_index = {k: i + 1 for i, k in enumerate(ips)}

    def prune_disconnected_probe_labels(self, connected_client_ids):
        """Drop offline IPs from probe numbering so replacements are not labeled as ghost N号."""
        connected_ips = set()
        for cid in connected_client_ids or []:
            ip = self._extract_client_ip(cid)
            if ip and ip != "serial":
                connected_ips.add(ip)
        if not connected_ips:
            return

        registry = getattr(self, "_probe_registry", None) or {}
        for ip in list(registry.keys()):
            if ip not in connected_ips:
                registry.pop(ip, None)
        self._probe_registry = registry

        # 只保留在线 IP，并按 IP 重排 1..N（不再保留幽灵槽位）
        ips = sorted(connected_ips)
        self._probe_ip_index = {k: i + 1 for i, k in enumerate(ips)}

    def probe_online_and_target(self):
        """(online, target) used by health card and E103 — same count, never diverge."""
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        online = 0
        if hasattr(self, "get_online_probe_client_ids"):
            online = len(self.get_online_probe_client_ids())
        pkt = getattr(self, "latest_master_summary", None)
        cfg_n = int(getattr(pkt, "probe_count_cfg", 0) or 0) if pkt is not None else 0
        if expected > 0:
            target = expected
        else:
            target = max(online, cfg_n, 1)
        return online, target

    def _probe_count_startup_grace_active(self) -> bool:
        """开采集后宽限内不报 E103 / 首页「启动自检」（第二路 K2 常晚连）。"""
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not getattr(dm, "is_acquiring", False):
            return False
        start = getattr(dm, "acquisition_start_time", None)
        if not start:
            return False
        grace = float(getattr(dm, "PROBE_COUNT_STARTUP_GRACE_SEC", 45.0) or 0.0)
        if grace <= 0:
            return False
        if (time.time() - float(start)) >= grace:
            return False
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        if expected > 0 and self._probes_with_spectrum_count() >= expected:
            return False
        return True

    def _probes_with_spectrum_count(self) -> int:
        """E103 只统计已收到能谱的探头，不把「刚连上 TCP」算在线。"""
        ids = self.get_online_probe_client_ids() if hasattr(self, "get_online_probe_client_ids") else []
        last_pkt = {}
        dm = getattr(self, "diagnostics_manager", None)
        if dm is not None:
            last_pkt = getattr(dm, "last_packet_time", None) or {}
        return sum(1 for cid in ids if float(last_pkt.get(cid, 0) or 0) > 0.0)

    def _sync_probe_count_fault(self):
        """E103 when online probes < expected (missing one or all)."""
        from core.diagnostics import FaultCode
        dm = getattr(self, "diagnostics_manager", None)
        if dm is None or not hasattr(dm, "add_fault"):
            return
        if not getattr(dm, "is_acquiring", False):
            dm.remove_fault("system", FaultCode.E103)
            return
        # 冷启动从未接设备：不算探头数量不足
        never = False
        try:
            never = bool(self._master_never_seen())
        except Exception:
            never = False
        n_clients = 0
        try:
            if hasattr(self, "_tcp_client_count"):
                n_clients = int(self._tcp_client_count())
            elif hasattr(self, "worker") and self.worker is not None:
                n_clients = len(getattr(self.worker, "client_sockets", None) or {})
        except Exception:
            n_clients = 0
        if never and n_clients == 0:
            dm.remove_fault("system", FaultCode.E103)
            return
        if self._probe_count_startup_grace_active():
            dm.remove_fault("system", FaultCode.E103)
            return
        if float(getattr(self, "_tcp_reinit_grace_until", 0) or 0) > time.time():
            dm.remove_fault("system", FaultCode.E103)
            return
        try:
            expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
        except (TypeError, ValueError):
            expected = 0
        # E103 只对照已设置的期望路数；未设置时不要用合成 target=1 误报
        if expected <= 0:
            dm.remove_fault("system", FaultCode.E103)
            return
        online = self._probes_with_spectrum_count()
        target = expected
        if target > 0 and online < target:
            dm.add_fault("system", FaultCode.E103)
        else:
            dm.remove_fault("system", FaultCode.E103)

    def format_fault_operator_message(self, client_id: str, code: str) -> str:
        """Build operator-facing fault text with correct probe number (no IP, keep short)."""
        from core.translation import _t
        label = self._fault_device_label(client_id)
        if str(code) == "E103":
            try:
                expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
            except (TypeError, ValueError):
                expected = 0
            online = (
                self._probes_with_spectrum_count()
                if hasattr(self, "_probes_with_spectrum_count")
                else 0
            )
            if expected <= 0 and hasattr(self, "probe_online_and_target"):
                online, expected = self.probe_online_and_target()
            body = _t("fault_op_E103", online=online, expected=expected)
        else:
            body = _t("fault_op_" + str(code))
        # 兼容旧 translation：清掉未替换占位符（写成拼接，避免源码里出现整串占位符）
        _ph = "{" + "probe" + "}"
        if _ph in body:
            body = body.replace(_ph, "").strip()
        if body == ("fault_op_" + str(code)):
            from core.diagnostics import FaultCode
            _, _, _, op = FaultCode.get_info(code)
            body = op.replace(_ph, "").strip() if op else body

        if label:
            return (label + " " + body).strip()
        return body

    def _fault_device_label(self, client_id: str) -> str:
        from core.translation import _t
        if client_id == "master":
            return "主控" if _t("master_online") == "在线" else "Master"
        if not client_id or client_id == "system":
            return ""
        return self.get_probe_label(client_id)

    def format_fault_home_message(self, client_id: str, code: str) -> str:
        """Homepage / control room: phenomenon + short action, never the E/M code."""
        from core.translation import _t
        from core.diagnostics import FaultCode
        code = str(code)
        label = "" if client_id in ("master", "system") else self._fault_device_label(client_id)
        if code == "E103":
            try:
                expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
            except (TypeError, ValueError):
                expected = 0
            online = (
                self._probes_with_spectrum_count()
                if hasattr(self, "_probes_with_spectrum_count")
                else 0
            )
            if expected <= 0 and hasattr(self, "probe_online_and_target"):
                online, expected = self.probe_online_and_target()
            missing = max(0, int(expected) - int(online))
            if online <= 0:
                body = _t("fault_home_E103_none", online=online, expected=expected)
            else:
                body = _t("fault_home_E103", missing=missing, online=online, expected=expected)
        else:
            body = _t("fault_home_" + code)
            if body == ("fault_home_" + code):
                name, _, _, _ = FaultCode.get_info(code)
                body = name or _t("fault_home_unknown")
        if label:
            return (label + " " + body).strip()
        return body

    def format_fault_diag_message(self, client_id: str, code: str) -> str:
        """Diagnostic page: keep the code for maintenance tickets."""
        from core.diagnostics import FaultCode
        code = str(code)
        name, _, _, _ = FaultCode.get_info(code)
        extra = ""
        if code == "E103":
            try:
                expected = int(getattr(self.config, "expected_probe_count", 0) or 0)
            except (TypeError, ValueError):
                expected = 0
            online = (
                self._probes_with_spectrum_count()
                if hasattr(self, "_probes_with_spectrum_count")
                else 0
            )
            if expected <= 0 and hasattr(self, "probe_online_and_target"):
                online, expected = self.probe_online_and_target()
            extra = "（%s/%s）" % (online, expected)
        return ("%s %s%s" % (code, name, extra)).strip()
    
    def update_client_selection_combo(self):
        """
        更新客户端选择下拉菜单
        """
        if not hasattr(self, 'client_selection_combo'):
            return
            
        # 阻止信号，避免触发on_client_selection_changed
        self.client_selection_combo.blockSignals(True)
        
        try:
            # 保存当前选中的客户端ID
            current_client_id = None
            current_index = self.client_selection_combo.currentIndex()
            if current_index >= 0:
                current_client_id = self.client_selection_combo.itemData(current_index)
            
            # 清空下拉菜单
            self.client_selection_combo.clear()
            
            # 添加"自动"选项
            self.client_selection_combo.addItem("Auto (First Connected)")
            
            # 添加所有可用客户端
            available_clients = self.get_available_clients()
            for client_id in available_clients:
                probe = self.get_probe_label(client_id)
                ip = self._extract_client_ip(client_id)
                if probe and ip:
                    display_name = f"{probe} ({ip})"
                elif probe:
                    display_name = probe
                else:
                    display_name = client_id
                
                # 正确设置itemData
                self.client_selection_combo.addItem(display_name)
                index = self.client_selection_combo.count() - 1
                self.client_selection_combo.setItemData(index, client_id)
            
            # 恢复选中状态
            if self.primary_client_id:
                # 查找主要客户端对应的索引
                found = False
                for i in range(self.client_selection_combo.count()):
                    if self.client_selection_combo.itemData(i) == self.primary_client_id:
                        self.client_selection_combo.setCurrentIndex(i)
                        found = True
                        break
                if not found and self.client_selection_combo.count() > 0:
                    # 如果主要客户端不在列表中，选择"自动"选项
                    self.client_selection_combo.setCurrentIndex(0)
            else:
                # 没有主要客户端，选择"自动"选项
                if self.client_selection_combo.count() > 0:
                    self.client_selection_combo.setCurrentIndex(0)
            
            # 启用下拉菜单（如果有客户端）
            self.client_selection_combo.setEnabled(len(available_clients) > 0)
            pinned = getattr(self, "_pinned_product_id_client_id", None)
            if pinned and (pinned not in available_clients or not self._is_settings_probe_client(pinned)):
                self._reassign_pinned_product_id_client()
        finally:
            # 恢复信号
            self.client_selection_combo.blockSignals(False)
        if hasattr(self, "_refresh_product_id_lock_ui"):
            self._refresh_product_id_lock_ui()
    
    def _skip_probe_radiation_log(self, client_id: str) -> bool:
        """通道机有主控时，操作员记录以主控硬报为准，不写探头辐射位。"""
        if not getattr(self.config, "tcp_enabled", False):
            return False
        master_cid = getattr(self, "master_client_id", None)
        if client_id and master_cid and client_id == master_cid:
            return True
        if master_cid:
            return True
        if hasattr(self, "is_master_online") and self.is_master_online():
            return True
        return False
    
    def log_alarm_event(self, packet: SpectrumPacket, client_id: str, alarm_status: bool):
        """
        记录报警事件到报警日志。
        串口模式：以探头报警位为准。
        TCP+主控：不写探头辐射位（由主控通道硬报统一记）。
        """
        try:
            if self._skip_probe_radiation_log(client_id):
                return
            alarm_logger = get_alarm_logger()
            
            if client_id is None:
                client_id = "serial_device"
            
            alarm_logger.log_alarm_event(
                client_id=client_id,
                alarm_status=alarm_status,
                count_rate=packet.counter,
                temperature=packet.temperature / 100.0,
                hv=packet.HV,
                product_id=packet.product_id,
                sensitivity=packet.sen_coef,
                alarm_type="Radiation",
                message=""
            )
            
        except Exception as e:
            self.log(f"记录报警事件失败: {e}", 'ERROR')

    def finalize_client_alarm_on_disconnect(self, client_id: str):
        """客户端断开时结算其报警状态。

        若该客户端仍处于报警中（“报警结束”边沿尚未到达就断线），补记一条
        “报警结束”并清理记录器内部状态；否则直接清理，避免 active_alarms 卡在
        True 使得下次同一 client_id 的报警无法被记录。
        """
        try:
            alarm_logger = get_alarm_logger()
            logger_client_id = client_id if client_id is not None else "serial_device"

            # 未处于报警中则无需补记，直接清理内部状态即可
            if not alarm_logger.get_active_alarms().get(logger_client_id, False):
                alarm_logger.reset_client_state(logger_client_id)
                return

            # 仍在报警中：用最后一包数据补记“报警结束”
            packet = self.client_latest_packets.get(client_id)
            if packet is not None:
                self.log_alarm_event(packet, client_id, False)
            # 主控在线时 log 会被 skip，必须清边沿，否则 ACTIVE 卡死
            if alarm_logger.get_active_alarms().get(logger_client_id, False):
                alarm_logger.reset_client_state(logger_client_id)
        except Exception as e:
            self.log(f"断线结算报警状态失败: {e}", 'ERROR')

    def on_client_selection_changed(self, text):
        """
        客户端选择改变时的处理
        """
        if not hasattr(self, 'client_selection_combo'):
            return
        
        current_index = self.client_selection_combo.currentIndex()
        
        if current_index == 0:
            # 选择了"自动"选项
            if self.client_time_series:
                # 选择第一个客户端
                first_client_id = list(self.client_time_series.keys())[0]
                if first_client_id != self.primary_client_id:
                    self.set_primary_client(first_client_id)
        else:
            # 选择了具体客户端
            client_id = self.client_selection_combo.itemData(current_index)
            if client_id:
                self._pinned_product_id_client_id = client_id
                self._stable_default_probe_client_id = client_id
                self._product_id_lock_ui_sig = None
            if client_id and client_id != self.primary_client_id:
                self.set_primary_client(client_id)
                self.log(f"Manually selected client: {client_id}", 'INFO')
            elif client_id and hasattr(self, "load_probe_panel_settings"):
                self.load_probe_panel_settings(client_id)
    
    def manual_reconnect_serial(self):
        """
        手动重新连接串口
        用户点击Reconnect按钮时调用
        优化版本：减少延迟，快速恢复通信
        """
        if self.config.tcp_enabled:
            self.log("Cannot reconnect in TCP mode", 'WARNING')
            return
        
        if not hasattr(self, 'serial_port_combo'):
            self.log("Serial port combo not found", 'ERROR')
            return
        
        # 获取当前选中的串口和波特率
        port = self.serial_port_combo.currentText()
        baudrate_text = self.baudrate_combo.currentText()
        
        if port == "No serial devices found" or not port:
            self.log("No valid serial port selected", 'ERROR')
            return
        
        try:
            baudrate = int(baudrate_text)
        except ValueError:
            self.log(f"Invalid baudrate: {baudrate_text}", 'ERROR')
            return
        
        self.log(f"Manual reconnection to {port} at {baudrate} baud...", 'INFO')
        
        # 记录当前采集状态
        was_acquiring = self.is_acquiring
        
        # 如果正在采集，只停止读取数据，不停止定时器
        if was_acquiring:
            self.log("Pausing data acquisition for reconnection...", 'INFO')
            if self.worker:
                self.worker.stop_reading()
            # 不调用stop_acquisition()，避免重置所有数据
        
        # 断开当前连接（快速关闭）
        if isinstance(self.worker, SerialPacketWorker):
            self.log("Disconnecting current serial connection...", 'INFO')
            self.worker.disconnect_serial()
        
        # 尝试重新连接（优化连接参数）
        if isinstance(self.worker, SerialPacketWorker):
            self.log(f"Connecting to {port}...", 'INFO')
            
            # 使用优化的连接参数：减少超时时间，减少重试次数
            connected = False
            try:
                # 直接尝试连接，不使用重试机制
                if self.worker.ser and self.worker.ser.is_open:
                    self.worker.ser.close()
                
                # 使用较短的超时时间
                self.worker.ser = serial.Serial(port, baudrate, timeout=0.5, write_timeout=0.5)
                time.sleep(0.05)  # 很短的等待时间
                connected = True
            except Exception as e:
                self.log(f"Direct connection failed: {str(e)}", 'WARNING')
                # 如果直接连接失败，使用原来的重试机制
                connected = self.worker.connect_serial(port, baudrate)
            
            if connected:
                self.log(f"Successfully reconnected to {port}", 'INFO')
                # 更新配置
                self.config.update_settings(device=port, baudrate=baudrate)
                
                # 如果之前正在采集数据，快速恢复采集
                if was_acquiring:
                    self.log("Resuming data acquisition...", 'INFO')
                    # 直接启动读取，不延迟
                    if self.worker:
                        self.worker.start_reading()
                    # 确保定时器在运行
                    if not self.read_timer.isActive():
                        self._start_read_timer()
                    
                    # 更新状态
                    self.is_acquiring = True
                    self.set_status_label('Running ...', True)
                    self.log("Acquisition resumed after reconnection", 'INFO')
            else:
                self.log(f"Failed to reconnect to {port}", 'ERROR')
                # 如果之前正在采集，恢复采集状态
                if was_acquiring:
                    self.is_acquiring = True
                    self.set_status_label('Connection lost', False)
    
    def refresh_serial_ports(self):
        """
        手动刷新串口设备列表
        用户点击刷新按钮时调用
        """
        self.log("Manually refreshing serial port list...", 'INFO')
        self.update_serial_port_combo()
        self.log("Serial port list refreshed", 'INFO')
    
    def update_serial_port_combo(self):
        """
        更新串口设备下拉列表
        当USB接口更换后，调用此方法更新下拉列表中的可用设备
        """
        if not hasattr(self, 'serial_port_combo'):
            return
        
        # 阻止信号，避免触发on_serial_port_changed
        self.serial_port_combo.blockSignals(True)
        
        try:
            # 保存当前选中的设备
            current_port = self.serial_port_combo.currentText()
            
            # 搜索可用的串口设备
            available_ports = search_serial_devices()
            
            # 清空下拉列表
            self.serial_port_combo.clear()
            
            # 添加可用的设备
            if available_ports:
                self.serial_port_combo.addItems(available_ports)
                
                # 尝试恢复之前选中的设备
                if current_port in available_ports:
                    self.serial_port_combo.setCurrentText(current_port)
                elif available_ports:
                    # 如果之前的设备不在列表中，选择第一个可用的设备
                    self.serial_port_combo.setCurrentIndex(0)
                    # 更新配置
                    new_port = self.serial_port_combo.currentText()
                    if new_port != self.config.device:
                        self.config.update_settings(device=new_port)
                        self.log(f"Serial port updated to: {new_port}", 'INFO')
            else:
                # 没有可用的设备
                self.serial_port_combo.addItem("No serial devices found")
            
            # 启用或禁用下拉列表
            self.serial_port_combo.setEnabled(len(available_ports) > 0)
        finally:
            # 恢复信号
            self.serial_port_combo.blockSignals(False)
    
    def _get_control_code_description(self, control_code):
        """获取控制码的描述"""
        control_code_descriptions = {
            0x05: "信号输入/输出控制",
            0x06: "单继电器控制",
            0x07: "高压设置",
            0x08: "阈值设置",
            0x09: "工作模式控制",
            0x0A: "重置谱数据",
            0x0B: "增益稳定器控制",
            0x0C: "灵敏度系数设置",
            0x0D: "获取产品ID",
            0x0E: "设置产品ID",
            0x0F: "获取灵敏度系数",
            0x10: "多LED控制",
            0x11: "多继电器控制",
            0x12: "获取继电器状态",
            0x13: "获取报警状态",
            0x14: "恢复默认参数",
            0x15: "通道报警人工复位",
            0x16: "消警模式设置/读取",
            0x19: "传感器模式设置/读取",
            0xF0: "错误命令"
        }
        return control_code_descriptions.get(control_code, f"未知命令 (0x{control_code:02X})")

    def reset_factory_defaults(self, all_probes: bool = False):
        """Send probe command 0x14 (restore HV/trigger/sen_coef defaults)."""
        from core.translation import _t
        from PyQt5.QtWidgets import QMessageBox

        target_label = _t("reset_target_all") if all_probes else _t("reset_target_current")
        reply = QMessageBox.question(
            self if isinstance(self, QWidget) else None,
            _t("msg_reset_defaults_title"),
            _t("msg_reset_defaults_text", target=target_label),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False

        if not self.worker:
            self.log(_t("msg_reset_defaults_fail"), "ERROR")
            return False

        ok = False
        if self.config.tcp_enabled and is_tcp_worker(self.worker):
            if all_probes:
                n = self.worker.reset_factory_defaults_broadcast_probes()
                ok = n > 0
                target_label = f"{_t('reset_target_all')} ({n})"
            else:
                cid = self.primary_client_id
                if cid and cid == getattr(self.worker, "master_client_id", None):
                    cid = None
                if not cid:
                    probes = self.get_online_probe_client_ids()
                    cid = probes[0] if probes else None
                if not cid:
                    self.log(_t("msg_reset_defaults_fail"), "ERROR")
                    QMessageBox.warning(self, _t("msg_reset_defaults_title"), _t("msg_reset_defaults_fail"))
                    return False
                ok = self.worker.send_command_to_client(cid, "reset_factory_defaults", None)
                target_label = cid
        else:
            if hasattr(self.worker, "reset_factory_defaults"):
                ok = bool(self.worker.reset_factory_defaults())
            else:
                ok = False

        if ok:
            self.log(_t("msg_reset_defaults_ok", target=target_label), "INFO")
            QMessageBox.information(self, _t("msg_reset_defaults_title"),
                                    _t("msg_reset_defaults_ok", target=target_label))
        else:
            self.log(_t("msg_reset_defaults_fail"), "ERROR")
            QMessageBox.warning(self, _t("msg_reset_defaults_title"), _t("msg_reset_defaults_fail"))
        return ok
