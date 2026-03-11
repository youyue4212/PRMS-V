#!/bin/bash
# Gamma-ray Spectrometer 一键修复脚本（增强版）
# 修复所有问题：图标显示、字体、虚拟环境、自启动等

echo "========================================"
echo "Gamma-ray Spectrometer 一键修复（增强版）"
echo "========================================"

# 获取当前用户和目录
CURRENT_USER=$(whoami)
echo "当前用户: $CURRENT_USER"

# 尝试获取程序目录
if [ -f "main.py" ]; then
    CURRENT_DIR=$(pwd)
elif [ -f "../main.py" ]; then
    cd ..
    CURRENT_DIR=$(pwd)
elif [ -f "daq_tablet/main.py" ]; then
    cd daq_tablet
    CURRENT_DIR=$(pwd)
else
    echo "错误: 请在程序目录或其父目录中运行此脚本"
    echo "当前目录: $(pwd)"
    echo "请切换到包含 main.py 文件的目录"
    exit 1
fi

echo "程序目录: $CURRENT_DIR"

echo ""
echo "步骤1: 修复核心显示问题..."
echo "----------------------------------------"

# 1.1 修复图标显示
echo "1.1 修复Clients和Alarm Log图标..."
if [ -f "core/ui_components.py" ]; then
    # 备份原文件
    BACKUP_FILE="core/ui_components.py.backup.$(date +%Y%m%d_%H%M%S)"
    cp core/ui_components.py "$BACKUP_FILE"
    
    # 修改图标：? -> C, ? -> A
    sed -i 's/"\\U0001f465"/"C"/g' core/ui_components.py
    sed -i 's/"\\U0001f6a8"/"A"/g' core/ui_components.py
    
    echo "  ? 修改完成："
    echo "    - Clients图标：? → C"
    echo "    - Alarm Log图标：? → A"
    echo "    - 备份文件：$BACKUP_FILE"
else
    echo "  ??  警告：core/ui_components.py 不存在，跳过图标修复"
fi

# 1.2 安装字体
echo ""
echo "1.2 安装emoji字体..."
sudo apt-get update
sudo apt-get install -y fonts-noto-color-emoji 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ? Noto Color Emoji字体安装成功"
else
    echo "  ??  字体安装失败，但图标已改为字母，不影响使用"
fi

# 1.3 停止相关进程
echo ""
echo "1.3 停止所有相关进程..."
pkill -f "python3.*main\.py" 2>/dev/null && echo "  ? 已停止运行中的程序" || echo "  ??  没有运行中的程序"
pkill -f "start_spectrometer" 2>/dev/null && echo "  ? 已停止启动脚本进程" || echo "  ??  没有启动脚本进程"

echo ""
echo "步骤2: 配置虚拟环境和依赖..."
echo "----------------------------------------"

# 2.1 检查虚拟环境
echo "2.1 检查虚拟环境..."
if [ -d ~/myenv ]; then
    VENV_PATH=~/myenv
    echo "  ? 使用现有虚拟环境：~/myenv"
elif [ -d ~/spectrometer_env ]; then
    VENV_PATH=~/spectrometer_env
    echo "  ? 使用现有虚拟环境：~/spectrometer_env"
else
    VENV_PATH=~/spectrometer_env
    echo "  ??  创建新虚拟环境：~/spectrometer_env"
    python3 -m venv ~/spectrometer_env
    if [ $? -eq 0 ]; then
        echo "  ? 虚拟环境创建成功"
    else
        echo "  ? 虚拟环境创建失败"
        VENV_PATH=""
    fi
fi

# 2.2 安装Python依赖
if [ -n "$VENV_PATH" ] && [ -d "$VENV_PATH" ]; then
    echo ""
    echo "2.2 安装Python依赖..."
    source "$VENV_PATH/bin/activate"
    
    if [ -f "requirements.txt" ]; then
        echo "  从requirements.txt安装..."
        pip install -r requirements.txt
    else
        echo "  安装核心包..."
        pip install pyqtgraph pyserial numpy pandas matplotlib
    fi
    
    # 检查PyQt5
    if ! python3 -c "import PyQt5" 2>/dev/null; then
        echo "  ??  PyQt5未安装，使用系统包"
        echo "  将系统PyQt5添加到Python路径"
        export PYTHONPATH=/usr/lib/python3/dist-packages:$PYTHONPATH
    else
        echo "  ? PyQt5已安装"
    fi
    
    deactivate
else
    echo "  ??  跳过Python依赖安装（虚拟环境不可用）"
fi

# 2.3 修复串口权限
echo ""
echo "2.3 检查并修复串口权限..."
if groups $CURRENT_USER | grep -q "dialout"; then
    echo "  ? 串口权限: 已配置"
else
    echo "  ??  串口权限: 需要配置"
    echo "  添加用户到dialout组..."
    sudo usermod -a -G dialout $CURRENT_USER
    echo "  ? 已添加，需要重新登录或重启生效"
fi

echo ""
echo "步骤3: 创建优化的启动脚本..."
echo "----------------------------------------"

# 创建简化的启动脚本
cat > "$CURRENT_DIR/start_spectrometer_simple.sh" << 'EOF'
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
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export DISPLAY=:0
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
EOF

chmod +x "$CURRENT_DIR/start_spectrometer_simple.sh"
echo "? 创建简化启动脚本: $CURRENT_DIR/start_spectrometer_simple.sh"

echo ""
echo "步骤4: 设置自启动（使用Cron方案）..."
echo "----------------------------------------"

# 4.1 禁用原有自启动机制
echo "4.1 禁用原有自启动..."
AUTOSTART_FILE="/home/$CURRENT_USER/.config/autostart/spectrometer.desktop"
if [ -f "$AUTOSTART_FILE" ]; then
    mv "$AUTOSTART_FILE" "$AUTOSTART_FILE.disabled"
    echo "  ? 禁用GNOME自动启动"
else
    echo "  ??  GNOME自动启动文件不存在"
fi

sudo systemctl stop spectrometer.service 2>/dev/null || true
sudo systemctl disable spectrometer.service 2>/dev/null || true
echo "  ? 禁用systemd服务"

# 4.2 设置Cron自启动
echo ""
echo "4.2 设置Cron自启动..."
CRON_CMD="@reboot sleep 40 && '$CURRENT_DIR/start_spectrometer_simple.sh' > /tmp/spectrometer_boot.log 2>&1"

# 清理旧的cron任务
(crontab -l 2>/dev/null | grep -v "start_spectrometer" | grep -v "spectrometer") | crontab -

# 添加新的cron任务
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "  ? Cron自启动已设置"
echo "  任务内容：$CRON_CMD"

# 4.3 创建桌面快捷方式
echo ""
echo "4.3 创建桌面快捷方式..."
DESKTOP_FILE="/home/$CURRENT_USER/Desktop/spectrometer.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Gamma-ray Spectrometer
Comment=Spectrometer Data Acquisition
Exec=$CURRENT_DIR/start_spectrometer_simple.sh
Icon=$CURRENT_DIR/core/icons/icon.png
Terminal=false
Categories=Utility;Science;
EOF

chmod +x "$DESKTOP_FILE"
echo "  ? 创建桌面快捷方式: $DESKTOP_FILE"

echo ""
echo "步骤5: 设置环境变量..."
echo "----------------------------------------"

# 添加到.bashrc
BASH_PROFILE="/home/$CURRENT_USER/.bashrc"
if ! grep -q "PYQTGRAPH_QT_LIB" "$BASH_PROFILE"; then
    cat >> "$BASH_PROFILE" << 'EOF'

# Gamma-ray Spectrometer环境变量
export PYQTGRAPH_QT_LIB=PyQt5
export QT_QPA_PLATFORM=xcb
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export DISPLAY=:0
export QT_LOGGING_RULES=qt.qpa.*=false
export LOG_LEVEL=INFO
export NO_AT_BRIDGE=1

# 虚拟键盘输入修复（使用内部软件键盘）
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0
EOF
    echo "  ? 已添加环境变量到 $BASH_PROFILE"
else
    echo "  ??  环境变量已存在"
fi

echo ""
echo "步骤6: 禁用屏幕保护..."
echo "----------------------------------------"

# 尝试禁用GNOME屏幕保护
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
    gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null
    echo "  ? 已尝试禁用GNOME屏幕保护"
else
    echo "  ??  gsettings不可用，跳过屏幕保护设置"
fi

echo ""
echo "步骤7: 检查自动登录设置..."
echo "----------------------------------------"

echo "自动登录检查:"
if [ -f /etc/lightdm/lightdm.conf ]; then
    if grep -q "autologin-user=$CURRENT_USER" /etc/lightdm/lightdm.conf; then
        echo "  ? 自动登录: 已配置"
    else
        echo "  ??  自动登录: 未配置"
        echo "  请手动设置自动登录:"
        echo "  1. 图形界面: Settings → Users → Automatic Login"
        echo "  2. 命令行: sudo nano /etc/lightdm/lightdm.conf"
        echo "     添加: autologin-user=$CURRENT_USER"
    fi
elif [ -f /etc/gdm3/custom.conf ]; then
    echo "  ??  检测到GDM显示管理器"
    echo "  请检查自动登录设置"
else
    echo "  ??  无法确定显示管理器，请手动检查自动登录设置"
fi

echo ""
echo "步骤8: 创建验证脚本..."
echo "----------------------------------------"

# 创建验证脚本
cat > "$CURRENT_DIR/verify_fix.sh" << 'EOF'
#!/bin/bash
echo "=== 修复验证 ==="
echo ""
echo "1. 检查关键文件:"
ls -la start_spectrometer_simple.sh 2>/dev/null && echo "  ? 启动脚本: 存在" || echo "  ? 启动脚本: 缺失"
ls -la ~/Desktop/spectrometer.desktop 2>/dev/null && echo "  ? 桌面快捷方式: 存在" || echo "  ? 桌面快捷方式: 缺失"

echo ""
echo "2. 检查Cron任务:"
if crontab -l 2>/dev/null | grep -q "start_spectrometer"; then
    echo "  ? Cron自启动: 已配置"
    crontab -l | grep "start_spectrometer"
else
    echo "  ? Cron自启动: 未配置"
fi

echo ""
echo "3. 检查图标修改:"
if [ -f "core/ui_components.py" ]; then
    if grep -q '"C"' core/ui_components.py && grep -q "Clients" core/ui_components.py; then
        echo "  ? Clients图标: 已修改为C"
    else
        echo "  ? Clients图标: 未修改"
    fi
    
    if grep -q '"A"' core/ui_components.py && grep -q "Alarm Log" core/ui_components.py; then
        echo "  ? Alarm Log图标: 已修改为A"
    else
        echo "  ? Alarm Log图标: 未修改"
    fi
else
    echo "  ??  core/ui_components.py 不存在"
fi

echo ""
echo "4. 检查虚拟环境:"
if [ -d ~/myenv ]; then
    echo "  ? 虚拟环境myenv: 存在"
elif [ -d ~/spectrometer_env ]; then
    echo "  ? 虚拟环境spectrometer_env: 存在"
else
    echo "  ? 虚拟环境: 不存在"
fi

echo ""
echo "5. 检查进程:"
COUNT=$(ps aux | grep -E "python3.*main\.py" | grep -v grep | wc -l)
echo "  运行中的程序实例: $COUNT"
if [ $COUNT -eq 0 ]; then
    echo "  ??  没有运行中的进程"
elif [ $COUNT -eq 1 ]; then
    echo "  ? 只有一个进程在运行（正常）"
else
    echo "  ??  检测到多个进程 ($COUNT 个)"
fi

echo ""
echo "6. 测试启动:"
echo "  运行测试启动 (5秒测试)..."
timeout 5 ./start_spectrometer_simple.sh 2>&1 | tail -3
if [ $? -eq 124 ]; then
    echo "  ? 程序可以正常启动"
else
    echo "  ??  程序启动可能有问题"
fi

echo ""
echo "=== 验证完成 ==="
echo ""
echo "修复状态:"
echo "- 图标修复: ?"
echo "- 字体安装: ?"
echo "- 虚拟环境: ?"
echo "- 自启动设置: ?"
echo "- 桌面快捷方式: ?"
echo ""
echo "重启系统测试完整自启动:"
echo "sudo reboot"
EOF

chmod +x "$CURRENT_DIR/verify_fix.sh"
echo "? 创建验证脚本: $CURRENT_DIR/verify_fix.sh"

echo ""
echo "步骤9: 运行验证..."
echo "----------------------------------------"

bash "$CURRENT_DIR/verify_fix.sh"

echo ""
echo "========================================"
echo "修复完成!"
echo "========================================"
echo ""
echo "已完成的修复:"
echo "1. ? 修复Clients和Alarm Log图标显示"
echo "2. ? 安装emoji字体"
echo "3. ? 停止相关进程"
echo "4. ? 配置虚拟环境和Python依赖"
echo "5. ? 修复串口权限"
echo "6. ? 创建优化启动脚本"
echo "7. ? 设置Cron自启动"
echo "8. ? 创建桌面快捷方式"
echo "9. ? 设置环境变量"
echo "10. ? 禁用屏幕保护"
echo "11. ? 检查自动登录设置"
echo "12. ? 创建验证脚本"
echo ""
echo "重要提醒:"
echo "1. 必须设置自动登录才能实现开机自启动"
echo "2. 串口权限更改需要重新登录或重启生效"
echo "3. 建议重启系统进行完整测试: sudo reboot"
echo ""
echo "下一步操作:"
echo "1. 设置自动登录 (如果尚未设置)"
echo "2. 重启系统测试: sudo reboot"
echo "3. 检查修复结果: ./verify_fix.sh"
echo ""
echo "如果仍有问题，请提供以下信息:"
echo "1. 系统信息: lsb_release -a"
echo "2. 错误日志: cat /tmp/spectrometer_boot.log 2>/dev/null"
echo "3. 验证结果: ./verify_fix.sh"
echo "========================================"
