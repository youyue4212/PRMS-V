#!/bin/bash

# U盘数据导出脚本
# 当U盘插入时自动导出报警记录和能谱数据

LOG_FILE="/tmp/usb_export_$(date +%s).log"
# 若设定 DEBUG=1，则脚本会输出详细扫描日志；默认只输出关键事件
DEBUG=${DEBUG:-0}

echo "开始执行U盘导出脚本: $(date)" >> "$LOG_FILE"

# 允许空glob展开，这样不存在的路径不会被当作文字保留
shopt -s nullglob

# 等待一小段时间以便桌面环境自动挂载U盘
sleep 2

# 获取当前脚本所在目录（程序根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRAM_DIR="$SCRIPT_DIR"

echo "脚本目录: $SCRIPT_DIR" >> "$LOG_FILE"
echo "程序目录: $PROGRAM_DIR" >> "$LOG_FILE"

# 如果udev传入了设备名称作为第一个参数，则等待该设备挂载并取得挂载点
if [ -n "$1" ]; then
    dev="/dev/$1"
    echo "收到设备参数: $dev" >> "$LOG_FILE"
    echo "尝试通过 findmnt 获取挂载点..." >> "$LOG_FILE"
    # 优先使用 findmnt 直接查询设备对应的挂载点（更可靠）
    for i in {1..20}; do
        mp=$(findmnt -n -o TARGET "$dev" 2>/dev/null || true)
        if [ -n "$mp" ]; then
            echo "设备已挂载到 $mp" >> "$LOG_FILE"
            MOUNT_POINT="$mp"
            break
        fi
        sleep 1
    done
    if [ -z "$MOUNT_POINT" ]; then
        echo "设备 $dev 未通过 findmnt 找到挂载点，后续将扫描常见挂载目录" >> "$LOG_FILE"
    fi
fi

# 查找U盘挂载点（通常在/media或/mnt下）
find_mount_point() {
    echo "开始查找挂载点..." >> "$LOG_FILE"
    # 等待U盘挂载完成，最多等待20秒
    for i in {1..20}; do
        echo "检查第 $i 次..." >> "$LOG_FILE"
        # 使用 findmnt 列出所有挂载点，然后筛选出 /media 和 /mnt 下的目录
        mapfile -t mounts < <(findmnt -rn -o TARGET | grep -E '^/media/|^/mnt/' || true)
        echo "候选挂载点: ${mounts[*]}" >> "$LOG_FILE"
        for mount in "${mounts[@]}"; do
            echo "检查挂载点: $mount" >> "$LOG_FILE"
            if [ -d "$mount" ] && mountpoint -q "$mount"; then
                echo "找到挂载点 $mount，检查写权限..." >> "$LOG_FILE"
                if touch "$mount/.test_write" 2>/dev/null; then
                    rm -f "$mount/.test_write"
                    echo "挂载点 $mount 有写权限" >> "$LOG_FILE"
                    echo "$mount"
                    return 0
                else
                    echo "挂载点 $mount 没有写权限" >> "$LOG_FILE"
                fi
            else
                echo "挂载点 $mount 无效或非挂载点" >> "$LOG_FILE"
            fi
        done
        sleep 1
    done
    echo "未找到可写挂载点" >> "$LOG_FILE"
    return 1
}

if [ -z "$MOUNT_POINT" ]; then
    MOUNT_POINT=$(find_mount_point)
    if [ -z "$MOUNT_POINT" ]; then
        echo "未找到可写的U盘挂载点" >> "$LOG_FILE"
        exit 1
    fi
else
    echo "使用传入设备参数确定的挂载点: $MOUNT_POINT" >> "$LOG_FILE"
fi

echo "找到U盘挂载点: $MOUNT_POINT" >> "$LOG_FILE"

# 在开始复制前重验证挂载点仍然是挂载点（使用 mountpoint 更可靠）
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "挂载点 $MOUNT_POINT 已不可用，取消导出" >> "$LOG_FILE"
    exit 1
fi

# 创建导出目录
EXPORT_DIR="$MOUNT_POINT/spectrometer_data_$(date +%Y%m%d_%H%M%S)"
echo "准备创建导出目录: $EXPORT_DIR" >> "$LOG_FILE"
if ! mkdir -p "$EXPORT_DIR" 2>/dev/null; then
    echo "创建导出目录失败: $EXPORT_DIR" >> "$LOG_FILE"
    exit 1
fi

# 使用 rsync 做稳健复制（保留权限并在发生中断时可重试）
RSYNC_OPTS=( -a --no-O --info=progress2 )

copy_dir() {
    local src="$1"
    local dst="$2"
    if [ -d "$src" ]; then
        echo "正在复制 $src 到 $dst ..." >> "$LOG_FILE"
        rsync "${RSYNC_OPTS[@]}" "$src" "$dst" >> "$LOG_FILE" 2>&1 || {
            echo "rsync 复制 $src 到 $dst 失败" >> "$LOG_FILE"
            return 1
        }
    else
        echo "源不存在: $src" >> "$LOG_FILE"
    fi
}

# 导出日志、数据和用户 Raysen 目录
copy_dir "$PROGRAM_DIR/logs" "$EXPORT_DIR/"
copy_dir "$PROGRAM_DIR/data" "$EXPORT_DIR/"
copy_dir "$HOME/Raysen" "$EXPORT_DIR/"

# 创建导出完成标记文件
echo "数据导出完成于 $(date)" > "$EXPORT_DIR/export_complete.txt"
echo "导出目录: $EXPORT_DIR" >> "$EXPORT_DIR/export_complete.txt"
echo "数据导出完成: $EXPORT_DIR" >> "$LOG_FILE"

# 在U盘根目录创建一个易于在Windows看到的完成标记
ROOT_MARKER="$MOUNT_POINT/EXPORT_DONE_$(date +%Y%m%d_%H%M%S).txt"
echo "Export done at $(date)" > "$ROOT_MARKER" 2>/dev/null || true
echo "Marker: $ROOT_MARKER" >> "$LOG_FILE"

# 确保所有数据已经写入磁盘
sync "$EXPORT_DIR" || true
echo "同步完成" >> "$LOG_FILE"

# 如果不是调试模式，则尝试卸载U盘以降低后续拔出风险
if [ "${DEBUG:-0}" -eq 0 ]; then
    if umount "$MOUNT_POINT"; then
        echo "已卸载 $MOUNT_POINT" >> "$LOG_FILE"
    else
        echo "卸载 $MOUNT_POINT 失败" >> "$LOG_FILE"
    fi
else
    echo "DEBUG 模式：保留挂载点，不卸载" >> "$LOG_FILE"
fi