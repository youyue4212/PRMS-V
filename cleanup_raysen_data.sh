#!/bin/bash
# 每天扫 ~/Raysen 下自动保存/报警/通信事件/原始包/运行日志。
# 以 mtime 过期为主，文件名里的 YYYYMMDD 仅作核对；正在写的 .writing. 和近期文件不删。
#
# 保留天数随磁盘余量：
#   可用 >= 50% 且剩余 >= 200GB → 180 天
#   可用 >= 35% 且剩余 >= 100GB → 120 天
#   可用 >= 30%                 → 90 天
#   可用 >= 15%                 → 60 天
#   否则                        → 30 天
#
# crontab（每天 00:00）：
#   0 0 * * * $HOME/daq_tablet/cleanup_raysen_data.sh >> $HOME/Raysen/cleanup.log 2>&1
# 安装：
#   ./cleanup_raysen_data.sh --install-cron
# 试跑：
#   ./cleanup_raysen_data.sh --dry-run

set -u

ROOT="${RAYSEN_HOME:-$HOME/Raysen}"
DRY_RUN=0
MIN_KEEP_DAYS=2
RECENT_WRITE_SEC=7200

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

if [ "${1:-}" = "--install-cron" ]; then
    SCRIPT="$(cd "$(dirname "$0")" && pwd)/cleanup_raysen_data.sh"
    chmod +x "$SCRIPT"
    LINE="0 0 * * * $SCRIPT >> $HOME/Raysen/cleanup.log 2>&1"
    mkdir -p "$HOME/Raysen"
    tmp="$(mktemp)"
    crontab -l 2>/dev/null | grep -v "cleanup_raysen_data.sh" > "$tmp" || true
    echo "$LINE" >> "$tmp"
    crontab "$tmp"
    rm -f "$tmp"
    echo "crontab installed: $LINE"
    exit 0
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

free_pct() {
    local dir="$1"
    df -P "$dir" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print 100-$5}'
}

free_gb() {
    local dir="$1"
    df -Pk "$dir" 2>/dev/null | awk 'NR==2 {printf "%.0f", $4 / 1048576}'
}

keep_days_for() {
    local pct="$1"
    local gb="$2"
    if [ -z "$pct" ]; then
        echo 30
        return
    fi
    if [ "$pct" -ge 50 ] && [ "${gb:-0}" -ge 200 ]; then
        echo 180
    elif [ "$pct" -ge 35 ] && [ "${gb:-0}" -ge 100 ]; then
        echo 120
    elif [ "$pct" -ge 30 ]; then
        echo 90
    elif [ "$pct" -ge 15 ]; then
        echo 60
    else
        echo 30
    fi
}

# 文件名中第一段 20YYMMDD
name_ymd() {
    echo "$1" | grep -oE '20[0-9]{6}' | head -n 1
}

ymd_to_epoch() {
    local ymd="$1"
    if date -d "${ymd:0:4}-${ymd:4:2}-${ymd:6:2}" +%s >/dev/null 2>&1; then
        date -d "${ymd:0:4}-${ymd:4:2}-${ymd:6:2}" +%s
        return
    fi
    date -j -f "%Y%m%d" "$ymd" +%s 2>/dev/null
}

file_mtime() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null
}

scan_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        return
    fi
    local pct gb keep cutoff now
    pct="$(free_pct "$dir")"
    gb="$(free_gb "$dir")"
    keep="$(keep_days_for "${pct:-}" "${gb:-0}")"
    if [ "$keep" -lt "$MIN_KEEP_DAYS" ]; then
        keep="$MIN_KEEP_DAYS"
    fi
    now="$(date +%s)"
    cutoff=$((now - keep * 86400))
    log "scan $dir free=${pct:-?}% free_gb=${gb:-?} keep=${keep}d"

    local f name ymd epoch mtime diff
    find "$dir" -maxdepth 2 -type f \
        \( -name 'data_auto_*.xlsx' -o -name 'alarm_log_*.xlsx' \
           -o -name 'event_log_*.xlsx' \
           -o -name 'gspc_*.bin' -o -name 'daq_log_*.txt' \) \
        ! -name '*.writing.*' -print0 2>/dev/null |
    while IFS= read -r -d '' f; do
        name="$(basename "$f")"
        case "$name" in
            .*) continue ;;
        esac
        mtime="$(file_mtime "$f" || true)"
        if [ -z "${mtime:-}" ]; then
            continue
        fi
        if [ $((now - mtime)) -lt "$RECENT_WRITE_SEC" ]; then
            continue
        fi
        if [ "$mtime" -ge "$cutoff" ]; then
            continue
        fi
        ymd="$(name_ymd "$name")"
        if [ -n "$ymd" ]; then
            epoch="$(ymd_to_epoch "$ymd" || true)"
            if [ -z "${epoch:-}" ]; then
                log "skip invalid date $f (name=$ymd)"
                continue
            fi
            if [ "$epoch" -ge "$cutoff" ]; then
                continue
            fi
            diff=$((mtime - epoch))
            if [ "$diff" -lt 0 ]; then
                diff=$((-diff))
            fi
            if [ "$diff" -gt 86400 ]; then
                log "skip date/mtime mismatch $f (name=$ymd)"
                continue
            fi
        fi
        if [ "$DRY_RUN" -eq 1 ]; then
            log "DRY-RUN delete $f"
        else
            rm -f "$f" && log "deleted $f"
        fi
    done
}

mkdir -p "$ROOT"
log "cleanup start root=$ROOT dry_run=$DRY_RUN"
scan_dir "$ROOT/AutoSave"
scan_dir "$ROOT/AlarmLogs"
scan_dir "$ROOT/EventLogs"
scan_dir "$ROOT"
# 原始包若选在 Raysen 外，可 export RAW_LOG_DIR=/path
if [ -n "${RAW_LOG_DIR:-}" ]; then
    scan_dir "$RAW_LOG_DIR"
fi
log "cleanup done"
