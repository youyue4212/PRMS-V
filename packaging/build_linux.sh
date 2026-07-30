#!/bin/bash
# 在「目标架构」的 Linux 上执行（Pi5 / ARM 工控机 / x86 工控机）
# 规则：在 aarch64 上打出的包只能给 aarch64 用；x86_64 同理。
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ARCH="$(uname -m)"
OUT_NAME="daq_tablet_linux_${ARCH}"

echo "========================================"
echo " 打包平台: $(uname -s) / ${ARCH}"
echo " 工程目录: ${APP_DIR}"
echo "========================================"

cd "$APP_DIR"

# 1) 建议用虚拟环境，避免污染系统 Python
if [ ! -d ".venv_pack" ]; then
    python3 -m venv .venv_pack
fi
# shellcheck disable=SC1091
source .venv_pack/bin/activate

pip install -U pip wheel
pip install pyinstaller
# 按你现场需要安装运行依赖（可改成 -r requirements.txt）
pip install PyQt5 pyqtgraph numpy pandas pyserial openpyxl psutil scipy

# 2) 清理旧产物
rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/build"

# 3) 打包（目录模式，比单文件更稳，启动也更快）
cd "$SCRIPT_DIR"
pyinstaller --noconfirm --clean daq_tablet.spec

# 4) 附带安装脚本与说明
cp install.sh "dist/daq_tablet/"
chmod +x "dist/daq_tablet/install.sh" "dist/daq_tablet/daq_tablet" || true

# 5) 打成压缩包，方便拷到 U 盘
cd dist
tar -czvf "${OUT_NAME}.tar.gz" daq_tablet
echo ""
echo "完成！"
echo "产物: ${SCRIPT_DIR}/dist/${OUT_NAME}.tar.gz"
echo "拷到目标机后:"
echo "  tar -xzvf ${OUT_NAME}.tar.gz"
echo "  cd daq_tablet && sudo ./install.sh"
