#!/bin/bash
# Wrapper: wait for device to be mounted, then call export_to_usb.sh
set -euo pipefail
DEV_KERN="$1"
DEV_PATH="/dev/${DEV_KERN}"
LOG="/tmp/usb_export_wrapper_${DEV_KERN}_$(date +%s).log"
PROGRAM_DIR="${PROGRAM_DIR:-/home/raysen/user/daq_tablet}"
EXPORT_SCRIPT="${EXPORT_SCRIPT:-/usr/local/bin/export_to_usb.sh}"
echo "Wrapper started for $DEV_PATH at $(date)" >> "$LOG"
echo "PROGRAM_DIR=$PROGRAM_DIR" >> "$LOG"
echo "EXPORT_SCRIPT=$EXPORT_SCRIPT" >> "$LOG"
# wait up to 120 seconds for the device to be mounted
MOUNT_POINT=""
for i in {1..120}; do
    MOUNT_POINT=$(findmnt -n -o TARGET "$DEV_PATH" 2>/dev/null || true)
    if [ -n "$MOUNT_POINT" ]; then
        echo "Found mount: $MOUNT_POINT" >> "$LOG"
        break
    fi
    sleep 1
done

if [ -z "$MOUNT_POINT" ]; then
    echo "Attempting to mount $DEV_PATH via udisksctl" >> "$LOG"
    /usr/bin/udisksctl mount -b "$DEV_PATH" >> "$LOG" 2>&1 || true
    # retry after mount attempt
    for i in {1..30}; do
        MOUNT_POINT=$(findmnt -n -o TARGET "$DEV_PATH" 2>/dev/null || true)
        if [ -n "$MOUNT_POINT" ]; then
            echo "Found mount after udisksctl: $MOUNT_POINT" >> "$LOG"
            break
        fi
        sleep 1
    done
fi

if [ -z "$MOUNT_POINT" ]; then
    echo "Device $DEV_PATH was not mounted after waiting; attempting to scan /media and /mnt" >> "$LOG"
    mapfile -t mounts < <(findmnt -rn -o TARGET | grep -E '^/media/|^/mnt/' || true)
    for m in "${mounts[@]}"; do
        # check if this mount is for our device
        if mount | awk -v dev="$DEV_PATH" -v m="$m" '$1==dev && $3==m {exit 0} END {exit 1}'; then
            MOUNT_POINT="$m"
            echo "Fallback found mount: $MOUNT_POINT" >> "$LOG"
            break
        fi
    done
fi

if [ -z "$MOUNT_POINT" ]; then
    echo "No mount found for $DEV_PATH; exiting" >> "$LOG"
    exit 1
fi

if [ ! -x "$EXPORT_SCRIPT" ]; then
    echo "Export script not found or not executable: $EXPORT_SCRIPT" >> "$LOG"
    exit 1
fi

echo "Calling export_to_usb.sh with $DEV_KERN (mount=$MOUNT_POINT)" >> "$LOG"
if [ -d "$PROGRAM_DIR" ]; then
    cd "$PROGRAM_DIR"
fi
DEBUG=0 "$EXPORT_SCRIPT" "$DEV_KERN" >> "$LOG" 2>&1 || {
    echo "export_to_usb.sh failed" >> "$LOG"
    exit 1
}

echo "Wrapper finished for $DEV_PATH at $(date)" >> "$LOG"
exit 0
