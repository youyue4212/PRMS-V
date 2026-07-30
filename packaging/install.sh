#!/bin/bash
# 在目标工控机 / 树莓派上执行（需要有图形桌面）
# 用法: sudo ./install.sh
set -e

APP_NAME="daq_tablet"
INSTALL_DIR="/opt/${APP_NAME}"
DESKTOP_DIR="/usr/share/applications"
SERVICE_USER="${SUDO_USER:-$USER}"

if [ "$(id -u)" -ne 0 ]; then
    echo "请使用: sudo ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "安装到 ${INSTALL_DIR} ..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -a "$SCRIPT_DIR"/* "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/${APP_NAME}" || true

# 串口权限（常见工控需求）
if id "$SERVICE_USER" &>/dev/null; then
    usermod -aG dialout "$SERVICE_USER" 2>/dev/null || true
fi

# 桌面快捷方式
cat > "${DESKTOP_DIR}/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Gamma Spectrometer
Name[zh_CN]=伽马能谱探测系统
Comment=DAQ Tablet
Exec=${INSTALL_DIR}/${APP_NAME}
Path=${INSTALL_DIR}
Icon=utilities-system-monitor
Terminal=false
Categories=Science;Utility;
EOF

# 可选：命令行启动
ln -sf "${INSTALL_DIR}/${APP_NAME}" "/usr/local/bin/${APP_NAME}"

echo ""
echo "安装完成。"
echo "  启动: ${APP_NAME}"
echo "  或从开始菜单/应用列表打开"
echo "  若串口仍无权限，注销后重新登录一次"
echo ""
echo "（可选）开机自启可参考工程里的 spectrometer.service，把 ExecStart 改成:"
echo "  ExecStart=${INSTALL_DIR}/${APP_NAME}"
