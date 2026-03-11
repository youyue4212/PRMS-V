# 脚本用途与分类（当前保留脚本）

本文档汇总当前目录下保留的 14 个脚本用途与分类，便于维护与清理。

## 核心运行（建议保留）
- [start_spectrometer_absolute.sh](start_spectrometer_absolute.sh) — 绝对路径 + 虚拟环境启动主程序，最稳定。
- [start_spectrometer_rpi.sh](start_spectrometer_rpi.sh) — 树莓派环境启动脚本（含 Qt/键盘兼容设置）。
- [start_spectrometer.sh](start_spectrometer.sh) — 通用启动脚本（非虚拟环境必需时可用）。
- [start_spectrometer_simple.sh](start_spectrometer_simple.sh) — 简化启动（单实例检查 + 直启）。
- [start_spectrometer_venv.sh](start_spectrometer_venv.sh) — 虚拟环境包装器，调用树莓派启动脚本。
- [start_spectrometer_venv_simple.sh](start_spectrometer_venv_simple.sh) — 简化虚拟环境包装器。

## 安装与配置（按需保留）
- [install_spectrometer.sh](install_spectrometer.sh) — 新系统安装依赖、创建虚拟环境并生成启动脚本。
- [setup_ubuntu_autostart.sh](setup_ubuntu_autostart.sh) — 生成桌面图标与 GNOME 自启动配置。
- [update_launchers.sh](update_launchers.sh) — 更新 desktop/autostart/systemd 启动器文件。
- [setup_usb_autoexport.sh](setup_usb_autoexport.sh) — 安装 U 盘自动导出（udev + systemd）。

## USB 导出（按需保留）
- [export_to_usb.sh](export_to_usb.sh) — 手动/自动导出日志和数据到 U 盘。
- [spectrometer-usb-export-wrapper.sh](spectrometer-usb-export-wrapper.sh) — udev/systemd 触发的挂载等待与导出包装器。

## 一键修复（一次性）
- [fix_all_issues_enhanced.sh](fix_all_issues_enhanced.sh) — 增强版一键修复（依赖/启动/自启动）。
- [fix_all_problems.sh](fix_all_problems.sh) — 修复登录循环与重复启动问题。

## 使用建议
- 日常启动推荐使用 [start_spectrometer_absolute.sh](start_spectrometer_absolute.sh)。
- 若不再需要 USB 自动导出，可移除 USB 导出相关脚本。
- 一键修复脚本仅在故障排查时使用，平时可归档。
