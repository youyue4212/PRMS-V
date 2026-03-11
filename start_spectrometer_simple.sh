#!/bin/bash
# Gamma-ray Spectrometer 简化启动脚本

# 检查是否已经运行
if pgrep -f "python3.*main\.py" >/dev/null; then
    echo "程序已经在运行中"
    exit 0
fi

# 设置环境变量
export PYQTGRAPH_QT_LIB=PyQt5
export QT_QPA_PLATFORM=xcb
export DISPLAY=:0
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export QT_LOGGING_RULES=qt.qpa.*=false
export LOG_LEVEL=INFO
export NO_AT_BRIDGE=1
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0

# Disable GNOME OSK to avoid double keyboards when using internal keyboard
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled false >/dev/null 2>&1 || true

# 使用虚拟环境
if [ -d ~/myenv ]; then
    source ~/myenv/bin/activate
elif [ -d ~/spectrometer_env ]; then
    source ~/spectrometer_env/bin/activate
else
    echo "错误: 虚拟环境不存在"
    exit 1
fi

# 切换到程序目录
cd "$(dirname "$(realpath "$0")")"

# 运行程序
exec python3 main.py
