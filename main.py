import sys
import platform
import tempfile
import os
from core.main_window import MainWindow, INSTANCE_ACTIVATE_SERVER
from core.login_dialog import LoginDialog
from core.user_manager import UserRole
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt, QLockFile
from PyQt5.QtNetwork import QLocalSocket
from core import themes

def is_raspberry_pi():
    """检测是否运行在树莓派上"""
    try:
        # 方法1: 检查CPU信息
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo:
                return True
        
        # 方法2: 检查硬件型号
        try:
            import subprocess
            result = subprocess.run(['cat', '/sys/firmware/devicetree/base/model'], 
                                  capture_output=True, text=True, timeout=1)
            if 'Raspberry Pi' in result.stdout:
                return True
        except:
            pass
        
        # 方法3: 检查平台架构
        if platform.machine().startswith('arm') or platform.machine().startswith('aarch'):
            # ARM架构，可能是树莓派
            return True
            
    except:
        pass
    
    return False

def _notify_running_instance():
    """通知已运行实例恢复窗口（hide/最小化后再次点图标）。"""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_ACTIVATE_SERVER)
    if sock.waitForConnected(800):
        sock.write(b"raise\n")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        print("检测到程序已在运行，已通知其恢复窗口。")
        return True
    print("检测到程序已在运行，但无法唤起窗口。")
    print("可执行: pkill -f 'python3.*main.py' 后重新启动。")
    return False

def main():
    # 检测是否运行在树莓派上
    is_rpi = is_raspberry_pi()
    
    # 检查命令行参数
    use_fullscreen = "--fullscreen" in sys.argv
    use_resizable = "--resizable" in sys.argv
    keyboard_debug = "--keyboard-debug" in sys.argv
    
    # 打印键盘调试信息
    if keyboard_debug:
        print("=== 虚拟键盘调试模式 ===")
        print("环境变量检查:")
        print(f"  QT_IM_MODULE: {os.environ.get('QT_IM_MODULE', '未设置')}")
        print(f"  GTK_IM_MODULE: {os.environ.get('GTK_IM_MODULE', '未设置')}")
        print(f"  QT_QPA_PLATFORM: {os.environ.get('QT_QPA_PLATFORM', '未设置')}")
        print(f"  DISPLAY: {os.environ.get('DISPLAY', '未设置')}")
        print(f"  WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '未设置')}")
        print(f"  NO_AT_BRIDGE: {os.environ.get('NO_AT_BRIDGE', '未设置')}")
        print("========================")
    
    if is_rpi:
        print("检测到运行在树莓派上，应用优化设置...")
        # 树莓派优化设置
        # 启用高DPI缩放（必须在QApplication创建之前设置）
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # 创建QApplication实例（需先于单实例锁后的唤起套接字）
    app = QApplication(sys.argv)

    # 单实例保护：防止自启动配置（GNOME autostart + systemd 服务等）重复拉起多个实例。
    # 若已在运行：通知其恢复窗口（回到桌面后再次点图标），然后退出。
    lock_path = os.path.join(tempfile.gettempdir(), "daq_tablet.lock")
    single_instance_lock = QLockFile(lock_path)
    single_instance_lock.setStaleLockTime(30000)  # 30s 后视为过期锁
    if not single_instance_lock.tryLock(100):
        _notify_running_instance()
        sys.exit(0)
    # 保持锁对象存活直到进程结束
    main._instance_lock = single_instance_lock
    
    # 设置字体
    font = app.font()
    font.setFamily("Arial")
    if is_rpi and font.pointSize() < 10:
        # 树莓派上可能需要稍大的字体
        font.setPointSize(10)
    app.setFont(font)
    
    # 设置应用程序样式表
    app.setStyleSheet(themes.dark_stylesheet)
    
    # 默认以普通用户（viewer）模式启动，不需要密码
    from core.user_manager import get_user_manager, UserRole
    
    user_manager = get_user_manager()
    
    # 查找viewer用户
    viewer_username = None
    for username, user in user_manager.users.items():
        if user.role == UserRole.VIEWER:
            viewer_username = username
            break
    
    if not viewer_username:
        # 如果没有viewer用户，创建新的"viewer"用户（空密码）
        viewer_username = "viewer"
        user_manager.add_user(
            username=viewer_username,
            password="",  # 空密码
            role=UserRole.VIEWER,
            full_name="普通用户",
            email="viewer@example.com"
        )
    
    # 自动登录为viewer用户（使用空密码）
    success, message = user_manager.authenticate(viewer_username, "")
    
    # 如果认证失败，尝试直接设置当前用户（绕过密码检查）
    if not success:
        print(f"自动登录失败: {message}，尝试直接设置用户...")
        for username, user in user_manager.users.items():
            if user.role == UserRole.VIEWER:
                user_manager.current_user = user
                success = True
                message = "直接设置用户成功"
                break
    
    if success:
        user = user_manager.get_current_user()
        current_user = {
            'username': user.username,
            'role': user.role
        }
        print(f"自动以普通用户模式启动: {user.username} ({user.role.value})")
    else:
        # 如果自动登录失败，显示登录对话框
        print(f"自动登录失败: {message}")
        login_dialog = LoginDialog()
        
        # 如果用户取消登录，退出程序
        if login_dialog.exec_() != LoginDialog.Accepted:
            sys.exit(0)
        
        # 获取登录信息
        current_user = login_dialog.get_current_user_info()
        if not current_user:
            QMessageBox.critical(None, "错误", "无法获取用户信息")
            sys.exit(1)
    
    # 创建主窗口并传递用户信息
    window = MainWindow(current_user)
    
    # 如果启用了键盘调试，设置窗口标题
    if keyboard_debug:
        window.setWindowTitle(f"{window.windowTitle()} - 键盘调试模式")
        print("键盘调试模式已启用 - 窗口标题已更新")
    
    # 根据命令行参数设置窗口模式
    if use_fullscreen:
        # 全屏模式
        window.showFullScreen()
        print("全屏模式已启用")
    elif use_resizable:
        # 可调节大小模式
        window.setFixedSize(16777215, 16777215)  # 解除固定大小限制
        window.resize(1024, 600)  # 初始大小
        window.setMinimumSize(800, 450)  # 最小尺寸
        print("可调节大小模式已启用")
    else:
        # 默认模式：全屏显示（树莓派和非树莓派都使用全屏）
        window.showFullScreen()
        if is_rpi:
            print("树莓派模式：自动启用全屏显示")
        else:
            print("默认模式：全屏显示")
    
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
