# 使用文档（Ubuntu 20.04）

## 1. 适用范围
- 适用于 Ubuntu 20.04 及其他带 systemd/udev 的 Linux。
- Windows 不支持本套自动导出方式。

---

## 2. 目录与核心文件
- 主程序入口：[main.py](main.py)
- 依赖清单：[requirements.txt](requirements.txt)
- 核心代码：[core/](core/)
- 数据目录：
  - 报警日志默认位置：`~/Raysen/AlarmLogs`
  - 导出会包含：程序 `logs/`、`data/` 以及 `~/Raysen`
  - 记录规则见 [ALARM_LOG.md](ALARM_LOG.md)（TCP+主控时一次通道硬报一条，不与探头辐射位重复）

---

## 3. 安装（推荐方式）
### 3.1 一键安装（含可选 USB 自动导出）
```bash
bash /home/<user>/daq_tablet/install_spectrometer.sh
```
脚本会引导完成：
- 系统依赖安装
- Python 虚拟环境
- 依赖安装
- 启动脚本与桌面快捷方式
- 可选：USB 自动导出

### 3.2 只安装 USB 自动导出
```bash
bash /home/<user>/daq_tablet/setup_usb_autoexport.sh
```

---

## 4. 启动程序
### 4.1 直接启动
```bash
cd /home/<user>/daq_tablet
source source ~/myenv/bin/activate
python3 main.py
```

### 4.2 使用启动脚本（推荐）
```bash
cd /home/<user>/daq_tablet
./start_spectrometer_absolute.sh
```

### 4.3 systemd 自启（可选）
```bash
sudo cp /home/<user>/daq_tablet/spectrometer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable spectrometer.service
sudo systemctl start spectrometer.service
```

---

## 5. USB 自动导出
### 5.1 功能说明
插入 U 盘后自动导出到根目录，生成：
- `EXPORT_DONE_YYYYMMDD_HHMMSS.txt`
- `spectrometer_data_YYYYMMDD_HHMMSS/`

### 5.2 相关文件
- 导出脚本：[export_to_usb.sh](export_to_usb.sh)
- wrapper：[spectrometer-usb-export-wrapper.sh](spectrometer-usb-export-wrapper.sh)
- udev 规则：[99-usb-export.rules](99-usb-export.rules)

### 5.3 手动触发测试
```bash
sudo systemctl start spectrometer-usb-export@sda1.service
sudo systemctl status spectrometer-usb-export@sda1.service --no-pager -l
sudo journalctl -u spectrometer-usb-export@sda1.service -n 80 --no-pager
```



## 6. 常见问题
### 6.1 Windows 看不到导出文件
可能原因：
- 导出时间较长（1–2 分钟甚至更久），过早拔出。
- Windows 缓存未刷新，重新插入并等待。
- U 盘文件系统错误，建议在 Windows 运行磁盘检查。

### 6.2 自动导出未触发
检查日志：
```bash
ls -ltr /tmp/usb_export_*.log /tmp/usb_export_wrapper_*.log
sudo journalctl -u 'spectrometer-usb-export@*.service' -n 100 --no-pager
```

---

## 7. 需要保留的关键文件清单
**必须**
- [main.py](main.py)
- [core/](core/)
- [requirements.txt](requirements.txt)

**USB 自动导出（可选）**
- [export_to_usb.sh](export_to_usb.sh)
- [spectrometer-usb-export-wrapper.sh](spectrometer-usb-export-wrapper.sh)
- [99-usb-export.rules](99-usb-export.rules)

---

## 8. 备注
- 如果你在其他 Linux 发行版部署，需要保证 systemd + udev 可用。
- 若要更简化部署流程，可将 USB 自动导出合并进安装脚本（已完成）。
