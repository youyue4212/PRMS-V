#!/bin/bash
# Ubuntu系统自动启动设置

echo "========================================"
echo "Ubuntu系统自动启动设置"
echo "========================================"

# 检查当前用户
CURRENT_USER=$(whoami)
echo "当前用户: $CURRENT_USER"

# 检查程序目录
if [ ! -f "main.py" ]; then
    echo "错误: 请在程序目录中运行此脚本"
    echo "当前目录: $(pwd)"
    exit 1
fi

# 获取当前绝对路径
CURRENT_DIR=$(pwd)
echo "程序目录: $CURRENT_DIR"

echo "步骤1: 确保启动脚本可执行..."
chmod +x start_spectrometer_rpi.sh
chmod +x start_spectrometer.sh

echo "步骤2: 创建桌面快捷方式..."
DESKTOP_FILE="/home/$CURRENT_USER/Desktop/spectrometer.desktop"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Gamma-ray Spectrometer
Comment=Gamma-ray Spectrometer Data Acquisition
Exec=/bin/bash -c "cd '$CURRENT_DIR' && ./start_spectrometer_absolute.sh > /home/$CURRENT_USER/spectrometer.log 2>&1"
Icon=$CURRENT_DIR/core/icons/icon.png
Terminal=false
Categories=Utility;Science;
EOF

chmod +x "$DESKTOP_FILE"
echo "创建桌面快捷方式: $DESKTOP_FILE"

echo "步骤3: 创建GNOME自动启动文件..."
AUTOSTART_DIR="/home/$CURRENT_USER/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

AUTOSTART_FILE="$AUTOSTART_DIR/spectrometer.desktop"

cat > "$AUTOSTART_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Gamma-ray Spectrometer
Comment=Gamma-ray Spectrometer Data Acquisition
Exec=/bin/bash -c "cd '$CURRENT_DIR' && ./start_spectrometer_absolute.sh > /home/$CURRENT_USER/spectrometer.log 2>&1"
Icon=$CURRENT_DIR/core/icons/icon.png
Terminal=false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=Gamma-ray Spectrometer
EOF

echo "创建GNOME自动启动文件: $AUTOSTART_FILE"

echo "步骤4: 设置环境变量..."
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
export NO_AT_BRIDGE=1

# 禁用输入法模块，使用软件键盘方案
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
EOF
    echo "已添加环境变量到 $BASH_PROFILE"
fi

# 添加到.profile（确保登录时生效）
PROFILE_FILE="/home/$CURRENT_USER/.profile"
if ! grep -q "PYQTGRAPH_QT_LIB" "$PROFILE_FILE"; then
    cat >> "$PROFILE_FILE" << 'EOF'

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
export NO_AT_BRIDGE=1

# 禁用输入法模块，使用软件键盘方案
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
EOF
    echo "已添加环境变量到 $PROFILE_FILE"
fi

echo "步骤5: 设置Ubuntu自动登录..."
echo "注意: Ubuntu自动登录需要手动设置"
echo ""
echo "设置方法1: 使用GUI"
echo "1. 打开 'Settings' (设置)"
echo "2. 选择 'Users' (用户)"
echo "3. 点击 'Unlock' (解锁)"
echo "4. 打开 'Automatic Login' (自动登录)"
echo ""
echo "设置方法2: 使用命令行"
echo "1. 编辑lightdm配置:"
echo "   sudo nano /etc/lightdm/lightdm.conf"
echo "2. 添加以下内容:"
echo "   [Seat:*]"
echo "   autologin-user=$CURRENT_USER"
echo "   autologin-user-timeout=0"
echo "3. 重启lightdm:"
echo "   sudo systemctl restart lightdm"

echo "步骤6: 禁用屏幕保护和电源管理..."
# 禁用GNOME屏幕保护
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.desktop.session idle-delay 0
    gsettings set org.gnome.desktop.screensaver lock-enabled false
    gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
    echo "已禁用GNOME屏幕保护和电源管理"
fi

# 禁用Ubuntu自动锁屏
if [ -f /etc/xdg/autostart/gnome-screensaver.desktop ]; then
    sudo mv /etc/xdg/autostart/gnome-screensaver.desktop /etc/xdg/autostart/gnome-screensaver.desktop.disabled
    echo "已禁用系统级屏幕保护"
fi

echo "步骤7: 创建systemd用户服务（可选）..."
SYSTEMD_USER_DIR="/home/$CURRENT_USER/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

USER_SERVICE="$SYSTEMD_USER_DIR/spectrometer.service"

cat > "$USER_SERVICE" << EOF
[Unit]
Description=Gamma-ray Spectrometer (User Service)
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$CURRENT_DIR
Environment="PYQTGRAPH_QT_LIB=PyQt5"
Environment="QT_QPA_PLATFORM=xcb"
Environment="QT_OPENGL=software"
Environment="QT_FONT_DPI=96"
Environment="QT_AUTO_SCREEN_SCALE_FACTOR=1"
Environment="QT_SCALE_FACTOR=1.0"
Environment="QT_SCREEN_SCALE_FACTORS=1"
Environment="DISPLAY=:0"
Environment="QT_LOGGING_RULES=qt.qpa.*=false"
Environment="NO_AT_BRIDGE=1"
Environment="QT_IM_MODULE=none"
Environment="GTK_IM_MODULE=none"
Environment="XMODIFIERS=@im=none"
Environment="CLUTTER_IM_MODULE=none"
Environment="ONBOARD_PRELOAD_SYMBOLS=1"
Environment="ONBOARD_DISABLE_DBUS=0"
Environment="USE_SOFTWARE_KEYBOARD=1"
Environment="ENABLE_LOGIN_KEYBOARD=1"
Environment="ALLOW_VIEWER_SETTINGS=0"
Environment="LOG_LEVEL=INFO"
ExecStart=$CURRENT_DIR/start_spectrometer_absolute.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "创建systemd用户服务: $USER_SERVICE"

echo "步骤8: 启用用户服务..."
systemctl --user daemon-reload
systemctl --user enable spectrometer.service
systemctl --user start spectrometer.service

echo "步骤9: 创建测试脚本..."
TEST_SCRIPT="$CURRENT_DIR/test_ubuntu.sh"
cat > "$TEST_SCRIPT" << EOF
#!/bin/bash
echo "测试Ubuntu自动启动..."
echo "当前用户: \$USER"
echo "桌面环境: \$XDG_CURRENT_DESKTOP"
echo "DISPLAY: \$DISPLAY"
echo ""
echo "检查环境变量:"
echo "PYQTGRAPH_QT_LIB=\$PYQTGRAPH_QT_LIB"
echo "QT_QPA_PLATFORM=\$QT_QPA_PLATFORM"
echo ""
echo "检查自动启动文件:"
ls -la ~/.config/autostart/
echo ""
echo "检查systemd用户服务:"
systemctl --user status spectrometer.service --no-pager
EOF

chmod +x "$TEST_SCRIPT"
echo "测试脚本已创建: $TEST_SCRIPT"

echo "步骤10: 运行测试..."
bash "$TEST_SCRIPT"

echo "========================================"
echo "设置完成!"
echo "========================================"
echo ""
echo "Ubuntu自动启动已设置完成。"
echo ""
echo "设置内容:"
echo "1. 桌面快捷方式: /home/$CURRENT_USER/Desktop/spectrometer.desktop"
echo "2. GNOME自动启动: /home/$CURRENT_USER/.config/autostart/spectrometer.desktop"
echo "3. 环境变量: ~/.bashrc 和 ~/.profile"
echo "4. systemd用户服务: ~/.config/systemd/user/spectrometer.service"
echo "5. 禁用屏幕保护: 已配置"
echo ""
echo "重要步骤:"
echo "1. 必须设置自动登录（见步骤5）"
echo "2. 重启系统测试: sudo reboot"
echo ""
echo "测试方法:"
echo "1. 运行测试脚本: ./test_ubuntu.sh"
echo "2. 手动启动: ./start_spectrometer_rpi.sh"
echo "3. 检查日志: journalctl --user -u spectrometer.service -f"
echo ""
echo "重启测试:"
echo "sudo reboot"
echo "========================================"

# 创建Ubuntu专用使用说明
echo "创建Ubuntu使用说明..."
cat > "$CURRENT_DIR/Ubuntu自动启动使用说明.txt" << EOF
Gamma-ray Spectrometer Ubuntu自动启动设置

系统信息:
- 系统: Ubuntu
- 用户: $CURRENT_USER
- 程序目录: $CURRENT_DIR

已完成的设置:
1. 桌面快捷方式 - 双击可手动启动
2. GNOME自动启动 - 登录后自动启动
3. 环境变量配置 - 解决Qt问题
4. systemd用户服务 - 后台管理
5. 屏幕保护禁用 - 防止中断

必须完成的手动设置:
1. 设置自动登录:
   - 打开 "Settings" -> "Users"
   - 解锁并启用 "Automatic Login"
   或
   - 编辑 /etc/lightdm/lightdm.conf
   - 添加: autologin-user=$CURRENT_USER
   - 重启lightdm: sudo systemctl restart lightdm

2. 重启系统:
   sudo reboot

启动流程:
1. 系统启动
2. 自动登录到桌面
3. GNOME自动启动运行程序
4. 程序全屏显示

环境变量:
- PYQTGRAPH_QT_LIB=PyQt5
- QT_QPA_PLATFORM=xcb
- QT_OPENGL=software
- QT_FONT_DPI=96
- DISPLAY=:0

故障排除:
1. 程序没有启动:
   - 检查自动登录是否设置
   - 查看 ~/.xsession-errors
   - 检查: ls -la ~/.config/autostart/

2. Qt相关错误:
   - 运行: ./test_ubuntu.sh
   - 检查环境变量: echo \$PYQTGRAPH_QT_LIB

3. 手动测试:
   - 打开终端
   - 运行: ./start_spectrometer_rpi.sh

4. 查看服务状态:
   systemctl --user status spectrometer.service
   journalctl --user -u spectrometer.service -f

文件位置:
- 程序目录: $CURRENT_DIR
- 自动启动: ~/.config/autostart/spectrometer.desktop
- 桌面图标: ~/Desktop/spectrometer.desktop
- 用户服务: ~/.config/systemd/user/spectrometer.service

最后更新: $(date)
EOF

echo "使用说明已创建: $CURRENT_DIR/Ubuntu自动启动使用说明.txt"
