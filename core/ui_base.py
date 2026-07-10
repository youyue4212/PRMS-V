import sys
import os
import glob
import time
import serial
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFileDialog, QCheckBox,QLineEdit,
                             QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QTextEdit, QFormLayout, QGridLayout,QSizePolicy,QStyle,
                             QTabWidget, QDockWidget, QAction, QToolBar, QStatusBar, QMessageBox)
from PyQt5.QtCore import QThread, QTimer, QMutex, pyqtSignal, Qt, QObject, QEvent
from PyQt5.QtGui import QFont, QIcon
from dataclasses import dataclass
from typing import Optional
import struct
import subprocess
import pandas as pd
import numpy as np
import pyqtgraph as pg


from core.config import ConfigManager
from core import algorithm as alg

from core.detector import CmdFeedback, SpectrumPacket, search_serial_devices, SerialPacketWorker, DevMessage
from core.tcp_detector import TcpPacketWorker, ClientInfo
from core.raw_logger import RawLogger
from core import logger 
from core.alarm_logger import get_alarm_logger  # 导入报警记录器

log_inst=logger.get_logger()


FILTER_ENABLED =  True
FILTER_WIN_SIZE = 4
FILTER_NUM_SIGMA = 2

MAX_SPECTRUM_STORED=100





class FocusEventFilter(QObject):
    """监听输入框焦点事件，手动触发虚拟键盘"""
    def __init__(self):
        super().__init__()
        self.last_trigger_time = 0
        self.platform = sys.platform
        self.keyboard_process = None  # 跟踪键盘进程
        self.keyboard_enabled = False  # 默认禁用，避免导致树莓派注销
        self.current_focused_obj = None  # 当前获得焦点的输入控件
        self.debug_keyboard = str(os.environ.get('KEYBOARD_DEBUG', '')).strip() == '1'
        # 软件键盘模式时强制启用触发
        if str(os.environ.get('USE_SOFTWARE_KEYBOARD', '')).strip() == '1':
            self.keyboard_enabled = True
            # 关闭系统屏幕键盘，避免与内置键盘冲突
            try:
                subprocess.run(['gsettings', 'set', 'org.gnome.desktop.a11y.applications', 'screen-keyboard-enabled', 'false'],
                               stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    def eventFilter(self, obj, event):
        # 调试：记录所有事件类型
        if self.debug_keyboard and event.type() == QEvent.FocusIn:
            log_inst.info(f"DEBUG: FocusIn event detected on {type(obj).__name__}")
        
        # 检查是否使用软件键盘方案 - 最优先检查
        use_software_keyboard = os.environ.get('USE_SOFTWARE_KEYBOARD')
        if self.debug_keyboard:
            log_inst.info(f"DEBUG eventFilter: USE_SOFTWARE_KEYBOARD={use_software_keyboard}, repr={repr(use_software_keyboard)}")
        use_software_keyboard_str = str(use_software_keyboard).strip() if use_software_keyboard else ''
        if use_software_keyboard_str == '1':
            # 软件键盘模式，使用内置键盘，不触发外部OSK
            if event.type() == event.FocusIn and isinstance(obj, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit)):
                current_time = time.time()
                if current_time - self.last_trigger_time >= 0.5:
                    self.last_trigger_time = current_time
                    try:
                        from core.software_keyboard import get_keyboard_manager
                        km = get_keyboard_manager()
                        if current_time - getattr(km, "last_closed_time", 0) < 0.5:
                            return super().eventFilter(obj, event)
                        # 若聚焦在QLineEdit，但其父是SpinBox，则优先绑定到SpinBox
                        target_obj = obj
                        if isinstance(obj, QLineEdit):
                            parent = obj.parent()
                            while parent is not None:
                                if isinstance(parent, (QSpinBox, QDoubleSpinBox)):
                                    target_obj = parent
                                    break
                                parent = parent.parent()
                        if km.is_visible() and getattr(km, "current_input", None) is target_obj:
                            return super().eventFilter(obj, event)
                        log_inst.debug("Software keyboard mode - showing internal keyboard")
                        km.show_keyboard_for_input(target_obj, obj.window())
                    except Exception as e:
                        log_inst.error(f"Failed to show internal software keyboard: {e}")
            return super().eventFilter(obj, event)
        
        if not self.keyboard_enabled:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.FocusIn:
            if isinstance(obj, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit)):
                
                # 保存当前获得焦点的对象
                self.current_focused_obj = obj
                # 添加防抖动逻辑，防止短时间内重复触发导致卡死
                current_time = time.time()
                if current_time - self.last_trigger_time < 1.0:
                    return super().eventFilter(obj, event)
                self.last_trigger_time = current_time

                try:
                    log_inst.info("Input focus detected, attempting to show virtual keyboard...")
                    
                    if self.platform == "win32":
                        # Windows 平台：使用 Windows 屏幕键盘
                        self.show_windows_keyboard()
                    elif self.platform == "linux" or self.platform == "linux2":
                        # Linux 平台：使用 GNOME OSK
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

class UIBase():
    def __init__(self):
        self.focus_filter = FocusEventFilter()
        QApplication.instance().installEventFilter(self.focus_filter)

        self.config = ConfigManager()
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
        
        # Create worker based on configuration
        self.worker = None
        self.worker_thread = QThread()
        
        # Initialize worker based on TCP enabled setting
        self.initialize_worker()
        
        if self.worker:
            self.worker.moveToThread(self.worker_thread)




        
        self.read_timer = QTimer()
        if self.worker:
            # Connect appropriate read loop based on worker type
            if isinstance(self.worker, SerialPacketWorker):
                self.read_timer.timeout.connect(self.worker.read_serial_loop)
            elif isinstance(self.worker, TcpPacketWorker):
                self.read_timer.timeout.connect(self.worker.read_tcp_loop)
        self.read_timer.setInterval(10)

        # 绘图节流：数据仍每包累积，但绘图固定 ~10Hz 刷新，
        # 避免"每包全量重绘 3 张图 + 重建控件"导致的卡顿。
        self._plot_dirty = False
        self._last_client_ids = None
        self._spectrogram_ranges_set = False
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self._on_plot_timer)
        self.plot_timer.start(100)  # 10 Hz

        self.packet_counts = {'cmd': 0, 'spectrum': 0, 'errors': 0,'dev_msg':0}
        self.relay_states = [False, False]
        self.is_acquiring = False
        
        # Multi-client time series data storage
        self.client_time_series = {}  # {client_id: [(timestamp, counter, temperature, HV, spec_sum), ...]}
        self.client_spectrum_data = {}  # {client_id: spectrum_array} - Store spectrum data for each client
        self.client_latest_packets = {}  # {client_id: latest SpectrumPacket} - used for immediate display switching
        self.primary_client_id = None  # The client whose data is displayed in the chart
        
        self.spectrum_data = np.zeros(self.config.adc_channels)  # Current displayed spectrum data
        self.temperature_data = []
        self.hv_data = []
        self.timestamps = []
        
        self.channels = np.arange(self.config.adc_channels+ 1)

        self.gain_stabilizer_flag = 2
        # 1 enabled, 0: disabled, 2 not initialized or unknown
        self.gain_stabilizer_pending = False  # Flag to indicate we're waiting for device confirmation
        
        self.worker_thread.start()
        
        # Setup UI connections
        self.setup_ui()

        self.data_updated_callback =None
        self.alarm_status_callback = None
        
        # Auto-save configuration - DEFAULT ENABLED as requested by user
        self.auto_save_enabled = True  # Changed from False to True
        self.auto_save_interval = 300  # 5 minutes in seconds
        self.auto_save_path = ""
        self.auto_save_timer = QTimer()
        self.auto_save_timer.timeout.connect(self.auto_save_data)
        self.last_auto_save_time = 0
        self.auto_save_counter = 0
        
        # Start auto-save timer if enabled
        if self.auto_save_enabled:
            self.auto_save_timer.start(self.auto_save_interval * 1000)
    
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
        # 创建一个QWidget容器
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建PlotWidget - 更简单，兼容性更好
        try:
            self.cps_widget = pg.PlotWidget()
        except Exception as e:
            # 如果创建失败，尝试不同的方法
            print(f"Error creating PlotWidget: {e}")
            # 创建一个普通的QWidget作为后备
            self.cps_widget = QWidget()
            layout.addWidget(QLabel("Chart initialization failed"))
            return container
        
        # 设置图表样式
        self.cps_widget.setBackground('#2a2a2a')
        self.cps_widget.setTitle("Count Rate vs Time", color='#ffffff', size='12pt')
        self.cps_widget.setLabel('left', 'Counts / sec', color='#ffffff')
        self.cps_widget.setLabel('bottom', 'Time (s)', color='#ffffff')
        
        # 设置轴颜色
        self.cps_widget.getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
        self.cps_widget.getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
        self.cps_widget.getAxis('right').setPen(pg.mkPen(color='#666666', width=1))
        self.cps_widget.getAxis('top').setPen(pg.mkPen(color='#666666', width=1))
        
        # 设置轴文本颜色
        self.cps_widget.getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        self.cps_widget.getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
        
        # 创建曲线
        self.curve_cps = self.cps_widget.plot([], [], pen=pg.mkPen(color='#1f77b4', width=2), name='Count Rate')
        
        # 添加图例
        self.cps_widget.addLegend()
        
        # 启用自动范围
        self.cps_widget.enableAutoRange('y', True)
        
        # 确保曲线正确初始化
        self.curve_cps.setData([], [])
        
        # 添加到布局
        layout.addWidget(self.cps_widget)
        
        return container


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
        
        # 设置图表样式
        self.spec_widget.setBackground('#2a2a2a')
        self.spec_widget.setTitle(f"Spectrum ({self.config.adc_channels} Channels)", color='#ffffff', size='12pt')
        self.spec_widget.setLabel('left', 'Counts', color='#ffffff')
        self.spec_widget.setLabel('bottom', 'Channel', color='#ffffff')
        
        # 设置轴颜色
        self.spec_widget.getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
        self.spec_widget.getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
        self.spec_widget.getAxis('right').setPen(pg.mkPen(color='#666666', width=1))
        self.spec_widget.getAxis('top').setPen(pg.mkPen(color='#666666', width=1))
        
        # 设置轴文本颜色
        self.spec_widget.getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        self.spec_widget.getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
        
        # 创建曲线 - 使用stepMode="center"显示阶梯状能谱
        self.curve_spectrum = self.spec_widget.plot([], [], stepMode="center", fillLevel=0, 
                                                    brush=(31, 119, 180, 100), pen=pg.mkPen(color='#1f77b4', width=2), name='Spectrum')
        
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
        
        self.plot_spectrogram = widget.addPlot(
            row=0, col=0, title="Spectrogram (ADC Channels vs Time)"
        )
        self.plot_spectrogram.showAxis('right', True)
        self.plot_spectrogram.showAxis('top', True)
        self.plot_spectrogram.getAxis('right').setStyle(showValues=False)
        self.plot_spectrogram.getAxis('top').setStyle(showValues=False)
        self.plot_spectrogram.setLabel('bottom', 'Time (s)')
        self.plot_spectrogram.setLabel('left', 'ADC Channel')
        
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
        self.colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=colormap,
            label='Counts'
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

      
        
    def setup_ui(self):
        # Connect signals if worker exists
        if self.worker:
            self.worker.cmd_feedback_received.connect(self.on_cmd_feedback_received)
            self.worker.dev_message_received.connect(self.on_dev_message_received)
            self.worker.spectrum_packet_received.connect(self.on_spectrum_packet_received)
            self.worker.connection_status_changed.connect(self.on_connection_status_changed)
            self.worker.error_occurred.connect(self.on_error_occurred)
            self.worker.has_log.connect(self.on_has_log)
            #self.worker.buffer_status_changed.connect(self.on_buffer_status_changed)
            self.worker.command_sent.connect(self.on_command_sent)
            if isinstance(self.worker, TcpPacketWorker):
                self.worker.client_connected.connect(self.on_tcp_client_connected)
                self.worker.client_disconnected.connect(self.on_tcp_client_disconnected)
        else:
            self.log("Warning: Worker not initialized in setup_ui", 'WARNING')
        


    def toggle_raw_packet_logging(self, state):
        enabled = state == Qt.Checked
        self.log_raw_packet_enabled= enabled
        self.log_path_input.setEnabled(enabled)
        self.select_path_btn.setEnabled(enabled)
        self.log(f"Raw packet logging {'enabled' if enabled else 'disabled'}")
        if self.raw_logger:
            self.raw_logger.set_enabled(self.log_raw_packet_enabled)

    def select_log_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder to log raw packets ")
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

    def add_widgets_to_setting_layout(self, settings_layout):
       # Settings placeholder
        
        # Group 1: Communication Settings
        comm_group = QGroupBox("Communication Settings")
        comm_layout = QGridLayout(comm_group)
        
        # TCP/IP Enable Checkbox
        self.tcp_enable_checkbox = QCheckBox("Enable TCP/IP Server Mode")
        self.tcp_enable_checkbox.setChecked(self.config.tcp_enabled)
        self.tcp_enable_checkbox.stateChanged.connect(self.on_tcp_enable_changed)
        comm_layout.addWidget(self.tcp_enable_checkbox, 0, 0, 1, 4)
        
        # Server Settings (always shown when TCP is enabled)
        comm_layout.addWidget(QLabel("Server Host:"), 1, 0)
        self.tcp_host_input = QLineEdit(self.config.tcp_host)
        self.tcp_host_input.setPlaceholderText("0.0.0.0 for all interfaces")
        self.tcp_host_input.textChanged.connect(self.on_tcp_host_changed)
        comm_layout.addWidget(self.tcp_host_input, 1, 1)
        
        comm_layout.addWidget(QLabel("Server Port:"), 1, 2)
        self.tcp_port_spin = QSpinBox()
        self.tcp_port_spin.setRange(1, 65535)
        self.tcp_port_spin.setValue(self.config.tcp_port)
        self.tcp_port_spin.valueChanged.connect(self.on_tcp_port_changed)
        comm_layout.addWidget(self.tcp_port_spin, 1, 3)
        
        # Serial Settings (only shown when TCP is disabled)
        self.serial_port_label = QLabel("Serial Port:")
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.addItems(search_serial_devices())
        self.serial_port_combo.setCurrentText(self.config.device)
        self.serial_port_combo.currentTextChanged.connect(self.on_serial_port_changed)
        
        # Add refresh button next to serial port combo
        self.refresh_serial_btn = QPushButton("Refresh")
        self.refresh_serial_btn.setToolTip("Refresh available serial ports")
        self.refresh_serial_btn.clicked.connect(self.refresh_serial_ports)
        
        self.baudrate_label = QLabel("Baudrate:")
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baudrate_combo.setCurrentText(str(self.config.baudrate))
        self.baudrate_combo.currentTextChanged.connect(self.on_baudrate_changed)
        
        # Add serial settings to layout
        comm_layout.addWidget(self.serial_port_label, 2, 0)
        comm_layout.addWidget(self.serial_port_combo, 2, 1)
        comm_layout.addWidget(self.refresh_serial_btn, 2, 2)
        
        # Add manual reconnect button
        self.reconnect_serial_btn = QPushButton("Reconnect")
        self.reconnect_serial_btn.setToolTip("Manually reconnect to selected serial port")
        self.reconnect_serial_btn.clicked.connect(self.manual_reconnect_serial)
        comm_layout.addWidget(self.reconnect_serial_btn, 2, 3)
        
        comm_layout.addWidget(self.baudrate_label, 3, 0)
        comm_layout.addWidget(self.baudrate_combo, 3, 1)
        
        # Client Selection for multi-client mode - MOVED HERE as requested by user
        self.client_selection_label = QLabel("Display Client:")
        self.client_selection_combo = QComboBox()
        self.client_selection_combo.addItem("Auto (First Connected)")
        self.client_selection_combo.currentTextChanged.connect(self.on_client_selection_changed)
        self.client_selection_combo.setEnabled(False)  # Initially disabled until clients are available
        
        comm_layout.addWidget(self.client_selection_label, 4, 0, 1, 1)
        comm_layout.addWidget(self.client_selection_combo, 4, 1, 1, 3)
        
        # Update visibility based on current settings
        self.update_comm_settings_visibility()
        
        settings_layout.addWidget(comm_group)
  
        # Group 2: Detector Settings
        det_group = QGroupBox("Detector Settings")
        det_layout = QGridLayout(det_group)
        
        self.hv_spin = QDoubleSpinBox()
        self.hv_spin.setDecimals(2)
        self.hv_spin.setRange(0, 1500)  # 根据参考代码修改范围
        self.hv_spin.setValue(self.config.hv)
        self.hv_spin.editingFinished.connect(self.persist_hv_setting)
        
        hv_set_btn = QPushButton("Set HV")
        hv_set_btn.clicked.connect(self.set_high_voltage)
        
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 2200)
        self.threshold_spin.setValue(self.config.threshold)
        self.threshold_spin.editingFinished.connect(self.persist_threshold_setting)
        
        trig_set_btn = QPushButton("Set Threshold")
        trig_set_btn.clicked.connect(self.set_threshold)
        
        det_layout.addWidget(QLabel("Bias Voltage (V):"), 0, 0)
        det_layout.addWidget(self.hv_spin, 0, 1)
        det_layout.addWidget(hv_set_btn, 0, 2)
        det_layout.addWidget(QLabel("Threshold (mV):"), 1, 0)
        det_layout.addWidget(self.threshold_spin, 1, 1)
        det_layout.addWidget(trig_set_btn, 1, 2)
        
        settings_layout.addWidget(det_group)
        
        # Group 3: Control
        ctrl_group = QGroupBox("Control")
        ctrl_layout = QGridLayout(ctrl_group)

        # 根据参考代码，只保留Gain Stabilizer
        self.gain_stabilizer_btn = QPushButton("Turn On")
        self.gain_stabilizer_label = QLabel("[OFF]")
        self.gain_stabilizer_btn.clicked.connect(lambda: self.toggle_gain_stabilizer())
        ctrl_layout.addWidget(QLabel("Gain Stabilizer:"), 0, 0, 1, 1)
        ctrl_layout.addWidget(self.gain_stabilizer_label, 0, 1)
        ctrl_layout.addWidget(self.gain_stabilizer_btn, 0, 2)

        settings_layout.addWidget(ctrl_group)

        # --- Virtual Keyboard Group ---
        keyboard_group = QGroupBox("Virtual Keyboard")
        keyboard_layout = QGridLayout(keyboard_group)
        
        self.keyboard_enable_checkbox = QCheckBox("Enable virtual keyboard auto-trigger")
        self.keyboard_enable_checkbox.setChecked(False)
        self.keyboard_enable_checkbox.stateChanged.connect(self.toggle_virtual_keyboard)
        keyboard_layout.addWidget(self.keyboard_enable_checkbox, 0, 0, 1, 2)
        
        self.keyboard_status_label = QLabel("Status: Disabled")
        keyboard_layout.addWidget(self.keyboard_status_label, 1, 0, 1, 2)
        
        settings_layout.addWidget(keyboard_group)

        # --- Device Control and Status Group (根据参考代码添加) ---
        device_group = QGroupBox("Device Control and Status")
        device_layout = QGridLayout(device_group)
        
        # Product ID (只显示，不设置)
        self.product_id_label = QLabel("--")
        device_layout.addWidget(QLabel("Product ID:"), 0, 0)
        device_layout.addWidget(self.product_id_label, 0, 1, 1, 4)
        
        # Sensitivity Coefficient (报警灵敏度系数)
        self.sensitivity_label = QLabel("--")
        self.sensitivity_spin = QSpinBox()
        self.sensitivity_spin.setRange(1, 100)
        self.sensitivity_spin.setValue(self.config.sensitivity)
        self.sensitivity_spin.editingFinished.connect(self.persist_sensitivity_setting)
        self.sensitivity_set_btn = QPushButton("Set")
        self.sensitivity_set_btn.clicked.connect(self.set_sensitivity_coefficient)
        self.sensitivity_read_btn = QPushButton("Read")
        self.sensitivity_read_btn.clicked.connect(self.read_sensitivity_coefficient)
        
        device_layout.addWidget(QLabel("Sensitivity:"), 1, 0)
        device_layout.addWidget(self.sensitivity_label, 1, 1)
        device_layout.addWidget(self.sensitivity_spin, 1, 2)
        device_layout.addWidget(self.sensitivity_set_btn, 1, 3)
        device_layout.addWidget(self.sensitivity_read_btn, 1, 4)
        
        # Relay Control (继电器设置)
        self.relay0_checkbox = QCheckBox("Relay 0")
        self.relay0_checkbox.stateChanged.connect(lambda state: self.control_single_relay(0, state == Qt.Checked))
        self.relay1_checkbox = QCheckBox("Relay 1")
        self.relay1_checkbox.stateChanged.connect(lambda state: self.control_single_relay(1, state == Qt.Checked))
        self.relay2_checkbox = QCheckBox("Relay 2")
        self.relay2_checkbox.stateChanged.connect(lambda state: self.control_single_relay(2, state == Qt.Checked))
        
        self.relay_status_label = QLabel("Relay Status: --")
        self.relay_read_btn = QPushButton("Read Status")
        self.relay_read_btn.clicked.connect(self.read_relay_status)
        
        # 创建一个水平布局来均匀放置三个继电器复选框
        relay_checkbox_layout = QHBoxLayout()
        relay_checkbox_layout.addWidget(self.relay0_checkbox)
        relay_checkbox_layout.addWidget(self.relay1_checkbox)
        relay_checkbox_layout.addWidget(self.relay2_checkbox)
        relay_checkbox_layout.addStretch()  # 添加弹性空间
        
        device_layout.addWidget(QLabel("Relay Control:"), 2, 0)
        # 将水平布局添加到网格布局中，跨3列
        device_layout.addLayout(relay_checkbox_layout, 2, 1, 1, 3)
        device_layout.addWidget(self.relay_read_btn, 2, 4)
        device_layout.addWidget(self.relay_status_label, 3, 0, 1, 5)
        
        # Alarm Status (报警状态)
        self.alarm_status_label = QLabel("--")
        self.alarm_read_btn = QPushButton("Read Alarm")
        self.alarm_read_btn.clicked.connect(self.read_alarm_status)
        
        device_layout.addWidget(QLabel("Alarm Status:"), 4, 0)
        device_layout.addWidget(self.alarm_status_label, 4, 1, 1, 3)
        device_layout.addWidget(self.alarm_read_btn, 4, 4)
        
        # Counter Display
        self.counter_label = QLabel("--")
        device_layout.addWidget(QLabel("Counter:"), 5, 0)
        device_layout.addWidget(self.counter_label, 5, 1, 1, 4)
        
        settings_layout.addWidget(device_group)


        # --- Telemetry Logging Group ---
        log_group = QGroupBox("Raw packet logging")
        log_to_file_layout = QVBoxLayout(log_group)

        self.telemetry_checkbox = QCheckBox("Enable logging to file")
        self.telemetry_checkbox.setChecked(False)
        self.telemetry_checkbox.stateChanged.connect(self.toggle_raw_packet_logging)

        self.log_path_input = QLineEdit()
        self.log_path_input.setPlaceholderText("Select log file path...")
        self.log_path_input.setEnabled(False)

        self.select_path_btn = QPushButton("Browse...")
        self.select_path_btn.setEnabled(False)
        self.select_path_btn.clicked.connect(self.select_log_path)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.log_path_input)
        path_layout.addWidget(self.select_path_btn)

        log_to_file_layout.addWidget(self.telemetry_checkbox)
        log_to_file_layout.addLayout(path_layout)

        settings_layout.addWidget(log_group)

        # Storage for telemetry config
        self.log_raw_packet_enabled= False
        self.log_file_path = ""

        # --- Auto-Save Group ---
        auto_save_group = QGroupBox("Data Auto-Save")
        auto_save_layout = QGridLayout(auto_save_group)
        
        # Auto-save enable checkbox - DEFAULT CHECKED as requested by user
        self.auto_save_checkbox = QCheckBox("Enable data auto-save")
        self.auto_save_checkbox.setChecked(True)  # Default checked
        self.auto_save_checkbox.stateChanged.connect(self.toggle_auto_save)
        auto_save_layout.addWidget(self.auto_save_checkbox, 0, 0, 1, 4)
        
        # Auto-save interval
        auto_save_layout.addWidget(QLabel("Save interval (seconds):"), 1, 0)
        self.auto_save_interval_spin = QSpinBox()
        self.auto_save_interval_spin.setRange(60, 86400)  # 1 minute to 1 day (24 hours)
        self.auto_save_interval_spin.setValue(self.auto_save_interval)
        self.auto_save_interval_spin.setSingleStep(300)  # 5 minute steps for better usability
        self.auto_save_interval_spin.valueChanged.connect(self.set_auto_save_interval)
        auto_save_layout.addWidget(self.auto_save_interval_spin, 1, 1)
        
        # Add time unit conversion helper
        self.auto_save_interval_label = QLabel("(5 minutes)")
        auto_save_layout.addWidget(self.auto_save_interval_label, 1, 2)
        
        # Auto-save path
        auto_save_layout.addWidget(QLabel("Save path:"), 2, 0)
        self.auto_save_path_input = QLineEdit()
        self.auto_save_path_input.setPlaceholderText("Default: ~/Raysen/AutoSave/")
        self.auto_save_path_input.setText(self.auto_save_path)
        self.auto_save_path_input.setEnabled(False)
        auto_save_layout.addWidget(self.auto_save_path_input, 2, 1, 1, 2)
        
        self.auto_save_path_btn = QPushButton("Browse...")
        self.auto_save_path_btn.clicked.connect(self.select_auto_save_path)
        self.auto_save_path_btn.setEnabled(False)
        auto_save_layout.addWidget(self.auto_save_path_btn, 2, 3)
        
        # Enable path controls since auto-save is enabled by default
        self.auto_save_path_input.setEnabled(True)
        self.auto_save_path_btn.setEnabled(True)
        
        # Auto-save counter display
        self.auto_save_counter_label = QLabel("Auto-saves: 0")
        auto_save_layout.addWidget(self.auto_save_counter_label, 3, 0, 1, 4)
        
        # Enable/disable path controls based on auto-save state
        self.auto_save_path_input.setEnabled(self.auto_save_enabled)
        self.auto_save_path_btn.setEnabled(self.auto_save_enabled)
        
        settings_layout.addWidget(auto_save_group)

        settings_layout.addStretch()



    def log(self, message, dtype='INFO'):
        if dtype=='ERROR':
            log_inst.error(message)
        if dtype=='WARN':
            log_inst.warning(message)
        else: 
            log_inst.info(message)

    def update_control_labels(self):
        if self.gain_stabilizer_flag == 1:
            self.gain_stabilizer_btn.setText("Turn OFF")
            self.gain_stabilizer_label.setText("[ON]")
            self.gain_stabilizer_label.setStyleSheet('background-color:#b8e994; color:#000000;')
        else:
            self.gain_stabilizer_btn.setText("Turn ON")
            self.gain_stabilizer_label.setText("[OFF]")
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
            self.auto_save_counter_label.setText(f"Auto-saves: {self.auto_save_counter}")
    
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
            # Use TCP worker
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
            if isinstance(self.worker, TcpPacketWorker):
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
                self.initialize_worker()
                if self.worker:
                    self.worker.moveToThread(self.worker_thread)
                return False
        else:
            # Serial mode
            if isinstance(self.worker, SerialPacketWorker):
                if not self.worker.is_serial_ready():
                    return self.worker.connect_serial(self.config.device, self.config.baudrate)
                return True
            else:
                # Worker type mismatch, reinitialize
                self.initialize_worker()
                if self.worker:
                    self.worker.moveToThread(self.worker_thread)
                return False
    
    def ensure_serial_ready(self):
        """Backward compatibility method"""
        return self.ensure_connection_ready()


    
    def start_acquisition(self):
        if self.ensure_connection_ready():
            # 优化：先启动定时器，再开始读取，减少卡顿
            self.read_timer.start()
            
            # 延迟启动数据读取，让UI先响应
            QTimer.singleShot(100, lambda: self._delayed_start_reading())
            
            self.is_acquiring = True
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
        if self.worker:
            self.worker.start_reading()
            self.set_status_label('Running ...', True)
            self.log("Acquisition started", 'INFO')

    
    def stop_acquisition(self):
        if self.is_acquiring:
            self.worker.stop_reading()
            self.read_timer.stop()
            self.is_acquiring = False
            
            # 停止时清零数据，但保持连接
            self.reset_plots()
            
            # 重置当前状态数据
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.client_data = {}
            self.client_time_series = {}
            self.client_spectrum_data = {}
            self.client_latest_packets = {}
            self.primary_client_id = None
            self.total_count_rate = 0
            
            # 如果有数据更新回调，通知UI清零
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, {})
            
            self.set_status_label('Stopped.', False)

            if self.raw_logger:
                self.raw_logger.stop()


    
    def save_data(self, auto_save=False, auto_save_path=""):
        # 检查权限 - 注意：这里不能直接调用check_permission_before_action，因为UIBase没有这个方法
        # 权限检查应该在MainWindow的save_data方法中完成
        # 这里只处理保存数据的逻辑
        
        # 自动保存时跳过数据检查，即使数据为0也要保存
        if not auto_save and np.sum(self.spectrum_data)==0:
            QMessageBox.warning(self, "No Data", "No spectrum data available to save.")
            return
        
        # Check if we're in TCP mode or serial mode
        is_tcp_mode = self.config.tcp_enabled
        
        if is_tcp_mode:
            # TCP mode: save data for specific client
            client_id_to_save = self.primary_client_id
            
            # If no primary client is selected but we have clients, use the first one
            if not client_id_to_save and self.client_time_series:
                clients = list(self.client_time_series.keys())
                if len(clients) == 1:
                    client_id_to_save = clients[0]
                else:
                    # TODO: In the future, we could add a dialog to let user choose which client to save
                    # For now, save the first client
                    client_id_to_save = clients[0]
                    if not auto_save:
                        self.log(f"No primary client selected, saving data from first client: {client_id_to_save}", 'INFO')
            
            if not client_id_to_save:
                if not auto_save:
                    QMessageBox.warning(self, "No Client Data", "No client data available to save.")
                return
            
            # Create filename with client ID for TCP mode
            client_identifier = client_id_to_save
            if "_" in client_id_to_save:
                parts = client_id_to_save.split("_")
                if len(parts) >= 3:
                    # Extract IP and port
                    ip_port = parts[2]
                    # Replace colons with underscores for filename safety
                    ip_port_safe = ip_port.replace(":", "_")
                    client_identifier = f"client_{ip_port_safe}"
            
            default_filename = f"rayzen_spectrometer_data_{client_identifier}.xlsx"
            dialog_title = f"Save Data for {client_id_to_save}"
            
        else:
            # Serial mode: save all data (only one "client")
            client_id_to_save = "serial_device"
            default_filename = "rayzen_spectrometer_data.xlsx"
            dialog_title = "Save Data"
        
        if auto_save:
            # Auto-save mode: use provided path or generate default
            if auto_save_path:
                filename = auto_save_path
            else:
                # Generate auto-save filename with timestamp
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                if is_tcp_mode:
                    filename = f"rayzen_spectrometer_data_{client_identifier}_auto_{timestamp}.xlsx"
                else:
                    filename = f"rayzen_spectrometer_data_auto_{timestamp}.xlsx"
        else:
            # Manual save: show file dialog
            filename, _ = QFileDialog.getSaveFileName(
                    self,
                    dialog_title,
                    default_filename,
                    "Excel Files (*.xlsx);;All Files (*)"
                )
        
        if filename:
            try:
                if is_tcp_mode:
                    # TCP mode: save data for specific client
                    spectrum_data_to_save = self.client_spectrum_data.get(client_id_to_save, np.zeros(self.config.adc_channels))
                    time_series_data = self.client_time_series.get(client_id_to_save, [])
                    client_info = self.client_data.get(client_id_to_save, {})
                else:
                    # Serial mode: save all available data
                    # 保存原始累加能谱（不做显示层的 hampel 滤波），与 TCP 模式保持一致。
                    # 直接取原始累加数组 client_spectrum_data，避免依赖显示副本的刷新时机。
                    raw_client_id = self.primary_client_id
                    if raw_client_id and raw_client_id in self.client_spectrum_data:
                        spectrum_data_to_save = self.client_spectrum_data[raw_client_id]
                    elif self.client_spectrum_data:
                        spectrum_data_to_save = next(iter(self.client_spectrum_data.values()))
                    else:
                        spectrum_data_to_save = self.spectrum_data
                    
                    # Combine all time series data (in serial mode, there should be only one "client")
                    time_series_data = []
                    for client_id, data_list in self.client_time_series.items():
                        time_series_data.extend(data_list)
                    
                    # Get device info from the latest packet or client_data
                    # For serial mode, try to get from client_data or use default
                    client_info = {
                        'product_id': '--',
                        'sensitivity': '--',
                        'last_update': time.time()
                    }
                    
                    # Try to get device info from client_data if available
                    if self.client_data:
                        # Get the first client's data (should be the only one in serial mode)
                        first_client_id = list(self.client_data.keys())[0] if self.client_data else None
                        if first_client_id and first_client_id in self.client_data:
                            client_data = self.client_data[first_client_id]
                            client_info['product_id'] = client_data.get('product_id', '--')
                            client_info['sensitivity'] = client_data.get('sensitivity', '--')
                            client_info['last_update'] = client_data.get('last_update', time.time())
                
                # Save spectrum data
                df_spectrum = pd.DataFrame({
                    'Spectrum': spectrum_data_to_save
                })

                # Save time series data
                if time_series_data:
                    timestamps, counters, temperatures, hvs, spec_counts = zip(*time_series_data)
                    df_time_series = pd.DataFrame({
                        'Timestamp': timestamps, 
                        'Counter': counters,
                        'Temperature': temperatures,
                        'HV': hvs,
                        'Spectrum_Counts': spec_counts
                    })
                else:
                    df_time_series = pd.DataFrame(columns=['Timestamp', 'Counter', 'Temperature', 'HV', 'Spectrum_Counts'])
                
                # Save client/device information
                df_client_info = pd.DataFrame({
                    'Mode': ['TCP' if is_tcp_mode else 'Serial'],
                    'Client_ID': [client_id_to_save],
                    'Product_ID': [client_info.get('product_id', '--')],
                    'Sensitivity': [client_info.get('sensitivity', '--')],
                    'Last_Update': [time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(client_info.get('last_update', time.time())))]
                })
                
                with pd.ExcelWriter(filename) as writer:
                    df_spectrum.to_excel(writer, sheet_name='Spectrum', index=False)
                    df_time_series.to_excel(writer, sheet_name='TimeSeries', index=False)
                    df_client_info.to_excel(writer, sheet_name='DeviceInfo', index=False)
                
                if auto_save:
                    self.log(f"Data auto-saved to {filename} (auto-save #{self.auto_save_counter})", 'INFO')
                    self.auto_save_counter += 1
                else:
                    if is_tcp_mode:
                        self.log(f"Data saved to {filename} for client {client_id_to_save}", 'INFO')
                        self.log_output.append(f"<span style='color: green;'>Data saved to {filename} for client {client_id_to_save}</span>")
                    else:
                        self.log(f"Data saved to {filename}", 'INFO')
                        self.log_output.append(f"<span style='color: green;'>Data saved to {filename}</span>")
            except Exception as e:
                self.log(f"Save error: {str(e)}", 'ERROR')
                if not auto_save:
                    self.log_output.append(f"<span style='color: red;'>Save error: {str(e)}</span>")
    
    def auto_save_data(self):
        """自动保存数据"""
        if not self.auto_save_enabled:
            self.log("Auto-save is disabled, skipping", 'DEBUG')
            return
        
        current_time = time.time()
        time_since_last_save = current_time - self.last_auto_save_time
        
        self.log(f"Auto-save check: current_time={current_time}, last_auto_save_time={self.last_auto_save_time}, "
                f"interval={self.auto_save_interval}, time_since_last_save={time_since_last_save:.1f}s", 'DEBUG')
        
        if time_since_last_save >= self.auto_save_interval:
            try:
                self.log(f"Auto-save triggered! Time since last save: {time_since_last_save:.1f}s", 'INFO')
                
                # 生成自动保存文件名
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                if self.auto_save_path:
                    save_dir = self.auto_save_path
                    self.log(f"Using custom save path: {save_dir}", 'DEBUG')
                else:
                    # 默认保存到用户目录下的Raysen/AutoSave目录
                    home_dir = os.path.expanduser("~")
                    save_dir = os.path.join(home_dir, "Raysen", "AutoSave")
                    self.log(f"Using default save path: {save_dir}", 'DEBUG')
                    os.makedirs(save_dir, exist_ok=True)
                
                auto_save_filename = os.path.join(save_dir, f"data_auto_{timestamp}.xlsx")
                self.log(f"Auto-save filename: {auto_save_filename}", 'INFO')
                
                # 调用保存方法（自动保存模式）
                self.save_data(auto_save=True, auto_save_path=auto_save_filename)
                self.last_auto_save_time = current_time
                
                # 更新计数器标签
                self.update_auto_save_counter_label()
                
                self.log(f"Auto-save completed successfully! Counter: {self.auto_save_counter}", 'INFO')
                
            except Exception as e:
                self.log(f"Auto-save failed: {e}", 'ERROR')
                import traceback
                self.log(f"Auto-save traceback: {traceback.format_exc()}", 'ERROR')
        else:
            self.log(f"Auto-save not triggered yet. Need {self.auto_save_interval - time_since_last_save:.1f} more seconds", 'DEBUG')
    
    def toggle_virtual_keyboard(self, state):
        """切换虚拟键盘自动触发开关"""
        enabled = state == Qt.Checked
        self.focus_filter.keyboard_enabled = enabled
        
        # 更新状态标签
        if hasattr(self, 'keyboard_status_label'):
            if enabled:
                self.keyboard_status_label.setText("Status: Enabled")
                self.keyboard_status_label.setStyleSheet("color: green;")
                self.log("Virtual keyboard auto-trigger enabled", 'INFO')
            else:
                self.keyboard_status_label.setText("Status: Disabled")
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
    
    def format_time_interval(self, seconds):
        """格式化时间间隔为可读格式"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:  # 小于1小时
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return f"{minutes}分{remaining_seconds}秒"
            else:
                return f"{minutes}分钟"
        elif seconds < 86400:  # 小于1天
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return f"{hours}小时{remaining_minutes}分"
            else:
                return f"{hours}小时"
        else:  # 1天或以上
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours > 0:
                return f"{days}天{remaining_hours}小时"
            else:
                return f"{days}天"
    
    def select_auto_save_path(self):
        """选择自动保存路径"""
        path = QFileDialog.getExistingDirectory(self, "Select folder for auto-save")
        if path:
            self.auto_save_path = path
            self.auto_save_path_input.setText(path)
            self.log(f"Auto-save path set to: {path}", 'INFO')
        
    def show_about(self):
        QMessageBox.about(self, "About", "Gamma-ray Spectrometer Data Acquisition Software\nVersion 1.0\n© 2025")
    
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
        
        if storage_client_id not in self.client_time_series:
            self.client_time_series[storage_client_id] = []
            # Initialize spectrum data with correct shape from packet
            self.client_spectrum_data[storage_client_id] = np.zeros(packet.adc_channels)
            # Set as primary client if not set yet
            if self.primary_client_id is None:
                self.primary_client_id = storage_client_id
                self.log(f"Set {storage_client_id} as primary client for chart display", 'INFO')
        
        self.client_time_series[storage_client_id].append([packet.timestamp, packet.counter, packet.temperature, packet.HV, np.sum(spectrum)])
        
        # Ensure spectrum data array has correct shape
        if self.client_spectrum_data[storage_client_id].shape != spectrum.shape:
            self.client_spectrum_data[storage_client_id] = np.zeros_like(spectrum)
        
        # Accumulate spectrum data for this client
        self.client_spectrum_data[storage_client_id] += spectrum
        
        # Limit the size of time series data for each client
        if len(self.client_time_series[storage_client_id]) > 1000:  # Keep last 1000 data points
            self.client_time_series[storage_client_id] = self.client_time_series[storage_client_id][-1000:]

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

        # 只置脏标志；实际重绘由 plot_timer（~10Hz）统一执行，避免每包全量重绘
        self._plot_dirty = True

    def _on_plot_timer(self):
        """绘图节流定时器：有新数据时才刷新图表，固定 ~10Hz。"""
        if self._plot_dirty:
            self._plot_dirty = False
            self.update_data()




    
    def update_data(self):
        # Use data from primary client for chart display
        time_series_data = []
        if self.primary_client_id and self.primary_client_id in self.client_time_series:
            time_series_data = self.client_time_series[self.primary_client_id]
        elif self.client_time_series:
            # If no primary client set but we have data, use the first client
            first_client_id = list(self.client_time_series.keys())[0]
            self.primary_client_id = first_client_id
            time_series_data = self.client_time_series[first_client_id]
            self.log(f"Auto-selected {first_client_id} as primary client", 'INFO')
        
        if time_series_data:
            timestamps, counters, temperatures, hvs, spec_counts = zip(*time_series_data)
            if len(timestamps)>=1:
                _times = np.array(timestamps)/1000.
                times= _times-_times[0]
                
                # 根据用户说明：数据包中的counter字段已经是每秒计数（counts/sec）
                # 所以直接使用counter值作为计数率，而不是计算差值
                rates = np.array(counters, dtype=np.float64)
                
                # 显示计数率曲线（只显示主要客户端的数据）
                self.curve_cps.setData(times, rates)

                # 更新当前状态（使用最后一个数据包的值）
                self.current_stat ={'hv':hvs[-1],
                                    'rates': rates[-1],
                                    'temp':temperatures[-1]/100
                                    }
                
                # 不再计算总计数率，根据用户要求移除
                # self.calculate_total_count_rate()
                
                if self.data_updated_callback is not None:
                    # 不再传递总计数率
                    self.data_updated_callback(self.current_stat, 0, self.client_data)

            
            if FILTER_ENABLED:
                self.spectrum_data = alg.hampel_filter(self.spectrum_data, FILTER_WIN_SIZE, FILTER_NUM_SIGMA)

            # Update channels array to match spectrum data shape
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
        self.packet_counts['errors'] += 1
        #self.error_label.setText(f"Errors: {self.packet_counts['errors']}")
        self.log(f"ERROR: {error_message}")
    
    
    def on_command_sent(self, message: str):
        self.log_output.append(f"<span style='color: blue;'>{message}</span>")

    def on_tcp_client_connected(self, client_id: str):
        self.log(f"TCP client connected: {client_id}", 'INFO')
        if self.primary_client_id is None:
            self.primary_client_id = client_id
            self.apply_primary_client_snapshot()
        self.update_client_selection_combo()

    def on_tcp_client_disconnected(self, client_id: str):
        self.log(f"TCP client disconnected: {client_id}", 'INFO')
        self.remove_client_display_data(client_id)

        if self.primary_client_id == client_id:
            available_clients = self.get_available_clients()
            self.primary_client_id = available_clients[0] if available_clients else None
            self.apply_primary_client_snapshot()

        self.update_client_selection_combo()

    def remove_client_display_data(self, client_id: str):
        # 断线前先结算该客户端的报警状态：若仍在报警中，补记一条“报警结束”，
        # 并清理记录器内部状态，避免“报警结束”边沿丢失导致下次报警被漏记。
        self.finalize_client_alarm_on_disconnect(client_id)

        self.client_time_series.pop(client_id, None)
        self.client_spectrum_data.pop(client_id, None)
        self.client_latest_packets.pop(client_id, None)
        self.client_data.pop(client_id, None)

        if not self.client_time_series and not self.client_spectrum_data:
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

    def persist_hv_setting(self):
        try:
            voltage = self._read_spinbox_value(self.hv_spin, self.hv_spin.value())
            self.hv_spin.setValue(float(voltage))
            self.config.update_settings(hv=voltage)
            self.config.save_settings()
        except Exception:
            pass

    def persist_threshold_setting(self):
        try:
            level = self._read_spinbox_value(self.threshold_spin, self.threshold_spin.value())
            self.threshold_spin.setValue(int(level))
            self.config.update_settings(threshold=level)
            self.config.save_settings()
        except Exception:
            pass

    def persist_sensitivity_setting(self):
        try:
            coefficient = self._read_spinbox_value(self.sensitivity_spin, self.sensitivity_spin.value())
            self.sensitivity_spin.setValue(int(coefficient))
            self.config.update_settings(sensitivity=int(coefficient))
            self.config.save_settings()
        except Exception:
            pass
    
    def set_high_voltage(self):
        try:
            voltage = self._read_spinbox_value(self.hv_spin, self.hv_spin.value())
            self.hv_spin.setValue(float(voltage))
            self.config.update_settings(hv=voltage)
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
            self.config.update_settings(threshold=level)
            self.config.save_settings()
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
            # Stop current worker
            self.worker.stop_reading()
            self.read_timer.stop()
            
            # Disconnect based on worker type
            if isinstance(self.worker, SerialPacketWorker):
                self.worker.disconnect_serial()
            elif isinstance(self.worker, TcpPacketWorker):
                self.worker.disconnect_tcp()

            self.reset_plots()
            self.client_data = {}
            self.current_stat = {'hv': 0, 'rates': 0, 'temp': 0}
            self.total_count_rate = 0
            if self.data_updated_callback is not None:
                self.data_updated_callback(self.current_stat, 0, {})
            
            # Reinitialize worker
            self.initialize_worker()
            if self.worker:
                self.worker.moveToThread(self.worker_thread)
                # Reconnect signals
                self.setup_ui()
                
                # Reconnect read_timer timeout signal based on new worker type
                self.read_timer.timeout.disconnect()
                if isinstance(self.worker, SerialPacketWorker):
                    self.read_timer.timeout.connect(self.worker.read_serial_loop)
                elif isinstance(self.worker, TcpPacketWorker):
                    self.read_timer.timeout.connect(self.worker.read_tcp_loop)
        
        self.log(f"TCP/IP server mode {'enabled' if enabled else 'disabled'}", 'INFO')
    
    def on_tcp_host_changed(self, host):
        self.config.update_settings(tcp_host=host)
    
    def on_tcp_port_changed(self, port):
        self.config.update_settings(tcp_port=port)
    
    def on_serial_port_changed(self, port):
        """串口设备改变时的处理"""
        old_port = self.config.device
        self.config.update_settings(device=port)
        
        # 如果串口设备改变，并且当前是串口模式，尝试重新连接
        if not self.config.tcp_enabled and port != old_port:
            self.log(f"Serial port changed from {old_port} to {port}, attempting to reconnect...", 'INFO')
            
            # 停止当前的数据采集
            if self.is_acquiring:
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
                    if self.is_acquiring:
                        self.start_acquisition()
                else:
                    self.log(f"Failed to reconnect to {port}", 'ERROR')
    
    def on_baudrate_changed(self, baudrate_text):
        try:
            baudrate = int(baudrate_text)
            self.config.update_settings(baudrate=baudrate)
        except ValueError:
            self.log(f"Invalid baudrate: {baudrate_text}", 'ERROR')
    
    def update_comm_settings_visibility(self):
        """Update visibility of communication settings based on current configuration"""
        tcp_enabled = self.config.tcp_enabled
        
        # Show/hide TCP-specific settings
        self.tcp_host_input.setVisible(tcp_enabled)
        self.tcp_port_spin.setVisible(tcp_enabled)
        
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
        self.worker.stop_reading()
        self.read_timer.stop()
        
        # Disconnect based on worker type
        if isinstance(self.worker, SerialPacketWorker):
            self.worker.disconnect_serial()
        elif isinstance(self.worker, TcpPacketWorker):
            self.worker.disconnect_tcp()
        
        self.worker_thread.quit()
        self.worker_thread.wait()
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
    def set_product_id(self):
        if self.ensure_serial_ready():
            product_id = self.product_id_spin.value()
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
    
    def read_product_id(self):
        if self.ensure_serial_ready():
            success = self.worker.read_product_id(True)
            if success:
                self.log("Read product ID command sent")
            else:
                self.log("Failed to send read product ID command", "ERROR")
    
    def set_sensitivity_coefficient(self):
        coefficient = self._read_spinbox_value(self.sensitivity_spin, self.sensitivity_spin.value())
        try:
            self.sensitivity_spin.setValue(int(coefficient))
            self.config.update_settings(sensitivity=int(coefficient))
            self.config.save_settings()
        except Exception:
            pass
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'set_sensitivity_coefficient', coefficient)
                    if success:
                        self.log(f"Set sensitivity coefficient command sent to client {self.primary_client_id}: {coefficient}")
                    else:
                        self.log(f"Failed to send sensitivity coefficient command to client {self.primary_client_id}", 'ERROR')
                else:
                    success = self.worker.set_sensitivity_coefficient(coefficient)
                    if success:
                        self.log(f"Set sensitivity coefficient command sent: {coefficient}")
                    else:
                        self.log("Failed to send set sensitivity coefficient command", "ERROR")
            else:
                success = self.worker.set_sensitivity_coefficient(coefficient)
                if success:
                    self.log(f"Set sensitivity coefficient command sent: {coefficient}")
                else:
                    self.log("Failed to send set sensitivity coefficient command", "ERROR")
        else:
            self.log("Connection not ready, sensitivity saved locally only", 'WARNING')
    
    def read_sensitivity_coefficient(self):
        if self.ensure_serial_ready():
            success = self.worker.read_sensitivity_coefficient(True)
            if success:
                self.log("Read sensitivity coefficient command sent")
            else:
                self.log("Failed to send read sensitivity coefficient command", "ERROR")
    
    def control_single_relay(self, relay_num: int, state: bool):
        if self.ensure_serial_ready():
            # 如果TCP模式且有多客户端，发送到当前选中客户端
            if self.config.tcp_enabled and self.primary_client_id:
                # TCP模式下，需要将命令发送到特定客户端
                if hasattr(self.worker, 'send_command_to_client'):
                    success = self.worker.send_command_to_client(self.primary_client_id, 'control_single_relay', (relay_num, state))
                    if success:
                        self.log(f"Control relay {relay_num} command sent to client {self.primary_client_id}: {'ON' if state else 'OFF'}")
                    else:
                        self.log(f"Failed to send relay command to client {self.primary_client_id}", 'ERROR')
                else:
                    success = self.worker.control_single_relay(relay_num, state)
                    if success:
                        self.log(f"Control relay {relay_num} command sent: {'ON' if state else 'OFF'}")
                    else:
                        self.log(f"Failed to send control relay {relay_num} command", "ERROR")
            else:
                success = self.worker.control_single_relay(relay_num, state)
                if success:
                    self.log(f"Control relay {relay_num} command sent: {'ON' if state else 'OFF'}")
                else:
                    self.log(f"Failed to send control relay {relay_num} command", "ERROR")
    
    def read_relay_status(self):
        if self.ensure_serial_ready():
            success = self.worker.read_relay_status(True)
            if success:
                self.log("Read relay status command sent")
            else:
                self.log("Failed to send read relay status command", "ERROR")
    
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
            
            # 更新灵敏度系数显示
            self.sensitivity_label.setText(f"{packet.sen_coef}")
            
            # 更新继电器状态显示
            relay0_state = (packet.device_status & 0b00001) != 0
            relay1_state = (packet.device_status & 0b00010) != 0
            relay2_state = (packet.device_status & 0b00100) != 0
            
            # 更新复选框状态（但不触发信号）
            self.relay0_checkbox.blockSignals(True)
            self.relay0_checkbox.setChecked(relay0_state)
            self.relay0_checkbox.blockSignals(False)
            
            self.relay1_checkbox.blockSignals(True)
            self.relay1_checkbox.setChecked(relay1_state)
            self.relay1_checkbox.blockSignals(False)
            
            self.relay2_checkbox.blockSignals(True)
            self.relay2_checkbox.setChecked(relay2_state)
            self.relay2_checkbox.blockSignals(False)
            
            # 更新继电器状态标签
            relay_status_text = f"Relay Status: 0={relay0_state}, 1={relay1_state}, 2={relay2_state}"
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
            
            # 调用报警状态回调，更新主窗口的报警指示灯
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
        client_data = {
            'hv': packet.HV,
            'rates': packet.counter,  # 计数率（cps）
            'temp': packet.temperature / 100.0,  # 温度（°C）
            'last_update': current_time,
            'alarm': (packet.device_status & 0b10000) != 0,  # 报警状态
            'client_id': client_id,
            'product_id': packet.product_id,
            'sensitivity': packet.sen_coef
        }
        
        self.client_data[client_id] = client_data
        
        # 清理过期的客户端数据（30秒无更新）
        expired_clients = []
        for cid, data in self.client_data.items():
            if current_time - data['last_update'] > 30:  # 30秒超时
                expired_clients.append(cid)
        
        for cid in expired_clients:
            del self.client_data[cid]
    
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
            
            # 立即更新显示
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
        if self.config.tcp_enabled and isinstance(self.worker, TcpPacketWorker):
            connected_clients = self.worker.get_client_list()
            historical_clients = [
                client_id for client_id in self.client_time_series.keys()
                if client_id in connected_clients
            ]
            return list(dict.fromkeys(connected_clients + historical_clients))

        return list(self.client_time_series.keys())
    
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
                # 简化显示名称
                display_name = client_id
                if "_" in client_id:
                    # 提取IP和端口部分
                    parts = client_id.split("_")
                    if len(parts) >= 3:
                        display_name = f"Client {parts[1]}: {parts[2]}"
                
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
        finally:
            # 恢复信号
            self.client_selection_combo.blockSignals(False)
    
    def log_alarm_event(self, packet: SpectrumPacket, client_id: str, alarm_status: bool):
        """
        记录报警事件到报警日志
        
        Args:
            packet: 数据包
            client_id: 客户端ID
            alarm_status: 报警状态 (True: 报警开始, False: 报警结束)
        """
        try:
            # 获取报警记录器
            alarm_logger = get_alarm_logger()
            
            # 确定客户端ID（如果是串口模式，使用默认ID）
            if client_id is None:
                client_id = "serial_device"
            
            # 获取客户端数据
            client_data = self.client_data.get(client_id, {})
            
            # 记录报警事件
            alarm_logger.log_alarm_event(
                client_id=client_id,
                alarm_status=alarm_status,
                count_rate=packet.counter,  # 计数率 (cps)
                temperature=packet.temperature / 100.0,  # 温度 (°C)
                hv=packet.HV,  # 高压 (V)
                product_id=packet.product_id,  # 产品ID
                sensitivity=packet.sen_coef,  # 灵敏度系数
                alarm_type="Radiation",  # 报警类型
                message=f"计数率: {packet.counter} cps, 温度: {packet.temperature/100.0:.1f}°C, 高压: {packet.HV:.1f}V"
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
            else:
                # 无最近数据包可用时，直接清理状态，至少保证后续报警能被记录
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
            if client_id and client_id != self.primary_client_id:
                self.set_primary_client(client_id)
                self.log(f"Manually selected client: {client_id}", 'INFO')
    
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
                        self.read_timer.start()
                    
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
            0xF0: "错误命令"
        }
        return control_code_descriptions.get(control_code, f"未知命令 (0x{control_code:02X})")
