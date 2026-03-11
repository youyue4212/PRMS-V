
#!/bin/bash
# Gamma-ray Spectrometer启动脚本
# 适用于树莓派5

# 设置环境变量 - 修复Qt问题
# 注意：这些环境变量已经在systemd服务文件中设置
# 这里再次设置以确保直接运行脚本时也能正常工作

# 确保pyqtgraph使用PyQt5而不是PySide
export PYQTGRAPH_QT_LIB=PyQt5

# 设置QT显示缩放（针对树莓派屏幕优化）
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1

# 修复Qt线程和样式表问题
export QT_QPA_PLATFORM=xcb
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_LOGGING_RULES=qt.qpa.*=false
export DISPLAY=:0

# 禁用 AT-SPI 桥接以防止段错误 (Segmentation Fault) 和大量警告
export NO_AT_BRIDGE=1

# 启用输入法以支持 onboard 等虚拟键盘
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0
export LOG_LEVEL=INFO

# Disable GNOME OSK to avoid double keyboards when using internal keyboard
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled false >/dev/null 2>&1 || true

# 设置Python路径
export PYTHONPATH="$(dirname "$(realpath "$0")"):$PYTHONPATH"

# 获取脚本所在目录
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
cd "$SCRIPT_DIR"

echo "========================================"
echo "Gamma-ray Spectrometer 启动中..."
echo "========================================"
echo "当前目录: $SCRIPT_DIR"
echo "Python路径: $PYTHONPATH"
echo "环境变量:"
echo "  PYQTGRAPH_QT_LIB: $PYQTGRAPH_QT_LIB"
echo "  QT_AUTO_SCREEN_SCALE_FACTOR: $QT_AUTO_SCREEN_SCALE_FACTOR"
echo "  QT_SCALE_FACTOR: $QT_SCALE_FACTOR"
echo "  QT_IM_MODULE: $QT_IM_MODULE"
echo "========================================"

# 检查Python3是否可用
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3，请安装Python3"
    exit 1
fi

# 检查依赖
echo "检查Python依赖..."
python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "警告: 某些Python依赖缺失，尝试安装..."
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt
    else
        echo "错误: 未找到requirements.txt文件"
        echo "请手动安装依赖: pip3 install PyQt5 pyqtgraph pyserial numpy pandas"
        exit 1
    fi
fi

# 检查串口权限
echo "检查串口权限..."
if ! groups $USER | grep -q "dialout"; then
    echo "警告: 用户不在dialout组中，串口访问可能受限"
    echo "请运行: sudo usermod -a -G dialout $USER"
    echo "然后重新登录"
fi

# 检查日志目录
if [ ! -d "core/logs" ]; then
    mkdir -p core/logs
    echo "创建日志目录: core/logs"
fi

# 启动程序
echo "启动主程序..."
echo "========================================"

# 运行主程序
python3 main.py

# 程序退出后的处理
EXIT_CODE=$?
echo "========================================"
echo "程序退出，代码: $EXIT_CODE"
echo "========================================"

if [ $EXIT_CODE -eq 0 ]; then
    echo "程序正常退出"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "程序因错误退出"
else
    echo "程序退出代码: $EXIT_CODE"
fi

exit $EXIT_CODE
