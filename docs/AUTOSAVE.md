# 自动保存与归档间隔说明

## 分段归档（当前实现）

- **界面曲线**：内存仍只保留约 **15 分钟** 时序（1/5/15 分钟窗）。
- **自动保存**：写入自**上次自动保存以来**的时序 + **本段增量能谱**，文件之间不重复。
- **手动保存**：仍为当前界面用的累计能谱 + 最近 15 分钟时序（与操作员「导出当前」一致）。

## 间隔 5 分钟 vs 1 小时

| 间隔 | 适用 |
| ------ | ------ |
| **1 小时（默认）** | 长期值守、少文件、按小时追查 |
| **15～30 分钟** | 折中，崩溃未落盘窗口更短 |
| **5 分钟** | 极怕丢盘、尚未依赖分段归档时 |

在**旧版**（整份 15 分钟快照重复写盘）下，把间隔调到 3600 **不会**得到完整一小时时序，只会得到每文件约 15 分钟且中间有空洞。  
**分段归档启用后**，1 小时间隔才表示「约一小时一卷、卷内连续」。

## 验证（可选）

1. 设置 → 自动保存间隔设为 **3600** 秒。  
2. 采集 ≥1 小时。  
3. 打开 `~/Raysen/AutoSave/data_auto_*.xlsx`（Windows：`%USERPROFILE%\Raysen\AutoSave`）。  
4. **TimeSeries** 时间跨度应接近本段间隔（而非固定 15 分钟）。  
5. 相邻文件时间戳应首尾相接，无明显 45 分钟级空洞。

## 历史数据清理

程序运行期间每天本地时间 **0 点**执行一次 **Python 留存清理**（Win/Linux 相同规则）。  
Linux 工控机可额外使用 [`cleanup_raysen_data.sh`](../cleanup_raysen_data.sh) 作 0 点 cron 保险。

保留天数按磁盘空间自动计算，同时看空闲百分比和剩余 GB：

- 空闲 ≥ 50% 且剩余 ≥ 200GB：保留 180 天
- 空闲 ≥ 35% 且剩余 ≥ 100GB：保留 120 天
- 空闲 ≥ 30%：保留 90 天
- 空闲 ≥ 15%：保留 60 天
- 空闲 < 15%：保留 30 天

## 外部归档与审计记录

每个自动保存文件写完后，程序会计算 **SHA-256** 并追加一条本地审计记录：

- `~/Raysen/archive_manifest.jsonl`

默认只写本地 manifest，不向外部目录复制。现场需要 NAS/共享盘/挂载目录时，可配置：

- 环境变量 `RAYSEN_ARCHIVE_ENABLED=1`
- 环境变量 `RAYSEN_ARCHIVE_DIR=/path/to/archive`
- 可选：`RAYSEN_SITE_ID`、`RAYSEN_MACHINE_ID`

也可通过 Qt `QSettings` 写入同名配置键：

- `ARCHIVE_ENABLED`
- `ARCHIVE_PATH`
- `ARCHIVE_SITE_ID`
- `ARCHIVE_MACHINE_ID`

启用外部归档后，文件会复制到：

- `<ARCHIVE_PATH>/AutoSave/YYYY/MM/DD/<filename>`

复制后会重新计算 hash 校验。归档失败只写 WARNING 和 manifest，不影响本地自动保存成功，也不阻塞正常采集线程。

## 外部归档配置操作手册

### Linux 工控机

当前 Linux 主启动脚本是：

- `start_spectrometer_absolute.sh`

桌面启动、自启动和 `spectrometer.service` 最终都会调用这个脚本。因此要统一配置外部归档，优先修改它。

1. 打开脚本：

   ```bash
   cd /home/raysen/user/daq_tablet
   nano start_spectrometer_absolute.sh
   ```

2. 找到现有环境变量区域，例如：

   ```bash
   export USE_SOFTWARE_KEYBOARD=1
   export ENABLE_LOGIN_KEYBOARD=1
   export ALLOW_VIEWER_SETTINGS=0
   ```

3. 在下面追加外部归档配置：

   ```bash
   export RAYSEN_ARCHIVE_ENABLED=1
   export RAYSEN_ARCHIVE_DIR=/mnt/raysen_archive
   export RAYSEN_SITE_ID=site-a
   export RAYSEN_MACHINE_ID=gate-01
   ```

4. 保存后重启程序。如果使用 systemd：

   ```bash
   sudo systemctl restart spectrometer.service
   ```

   如果使用桌面自启动，退出程序后重新从桌面图标启动，或重启系统。

5. 验证环境变量：

   ```bash
   cd /home/raysen/user/daq_tablet
   grep '^export RAYSEN_ARCHIVE' start_spectrometer_absolute.sh
   grep '^export RAYSEN_.*ID' start_spectrometer_absolute.sh
   ```

6. 验证归档结果：

   ```bash
   ls -la /mnt/raysen_archive/AutoSave/
   tail -n 5 ~/Raysen/archive_manifest.jsonl
   ```

### Windows 电脑

Windows 直接运行 `python main.py` 时通常没有启动脚本，推荐用系统环境变量。

1. 先准备外部目录，例如网络盘：

   ```text
   Z:\RaysenArchive
   ```

   或 UNC 共享路径：

   ```text
   \\server\share\RaysenArchive
   ```

2. 打开 PowerShell，写入环境变量：

   ```powershell
   setx RAYSEN_ARCHIVE_ENABLED "1"
   setx RAYSEN_ARCHIVE_DIR "Z:\RaysenArchive"
   setx RAYSEN_SITE_ID "site-a"
   setx RAYSEN_MACHINE_ID "pc-01"
   ```

   如果使用 UNC 路径：

   ```powershell
   setx RAYSEN_ARCHIVE_DIR "\\server\share\RaysenArchive"
   ```

3. 关闭当前 PowerShell、Cursor 和程序，再重新打开。`setx` 只对新启动的进程生效。

4. 验证环境变量：

   ```powershell
   echo $env:RAYSEN_ARCHIVE_ENABLED
   echo $env:RAYSEN_ARCHIVE_DIR
   echo $env:RAYSEN_SITE_ID
   echo $env:RAYSEN_MACHINE_ID
   ```

5. 验证归档结果：

   ```powershell
   dir "Z:\RaysenArchive\AutoSave"
   Get-Content "$env:USERPROFILE\Raysen\archive_manifest.jsonl" -Tail 5
   ```

### 注意事项

- 外部目录必须提前挂载或可访问；程序不会自动登录 NAS。
- 外部归档失败不会影响本地自动保存，但会在日志和 manifest 中记录失败。
- 本地自动保存仍在 `~/Raysen/AutoSave` 或 `%USERPROFILE%\Raysen\AutoSave`。
- 正式核电/海关项目建议把外部目录放在有权限控制、备份、快照或 WORM 能力的存储上。
