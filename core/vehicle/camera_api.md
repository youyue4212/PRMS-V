# 车辆通道相机对接接口清单（PRMS-V）

## 1. 配置（QSettings / ConfigManager）

| 键 | 属性 | 说明 |
|----|------|------|
| `VEHICLE_RTSP_URL` | `vehicle_rtsp_url` | 预览 RTSP（建议海康 102 子码流） |
| `VEHICLE_CAPTURE_DIR` | `vehicle_capture_dir` | 硬报 JPEG 目录，空则 `~/daq_tablet/vehicle_captures` |
| `VEHICLE_CAMERA_CHANNEL` | `vehicle_camera_channel` | ISAPI 抓图通道，默认 `101`（主码流抓拍） |

用户名/密码/主机：优先从 `vehicle_rtsp_url` 解析（`rtsp://user:pass@host:554/...`）。

## 2. 模块边界

```text
core/vehicle/rtsp_url.py       → parse_rtsp_endpoint(url)
core/vehicle/hik_isapi.py      → hikvision_snapshot(host, user, pwd, channel) -> bytes
core/vehicle/camera_service.py → VehicleCameraService（硬报沿 + 异步存盘）
core/vehicle/rtsp_preview.py   → RtspPreviewWidget（预览 + 可选 alarm 静图）
```

## 3. VehicleCameraService（上位机调用面）

| 方法 | 说明 |
|------|------|
| `configure(config)` | 读 ConfigManager，创建抓拍目录 |
| `on_hard_alarm_rising(passage_id, on_saved=None)` | **辐射硬报首次置位**时调用；ISAPI 抓图，失败则回调 `None` |
| `ingest_plate(plate, passage_id=None)` | 相机识牌结果写入（ISAPI/报警/FTP 接入点，当前可手工测） |

回调：`on_saved(path: str | None)` 在 **GUI 线程外** 触发，UI 侧用 `QTimer.singleShot(0, ...)` 刷新。

## 4. Passage / FSM

| 字段 | 说明 |
|------|------|
| `Passage.image_paths` | 分号分隔的本地 JPEG 路径，入库 `passage.image_paths` |
| `Passage.plate` | 相机识牌或手补 |
| `Passage.plate_manual` | 手补为 True 时不覆盖 plate |

硬报沿检测：`_vehicle_on_summary` 在 `on_packet` 前记 `hard_alarm`，之后 `open.hard_alarm and not prev` → `on_hard_alarm_rising`。

## 5. UI

| 位置 | 行为 |
|------|------|
| 设置 | RTSP、抓拍目录（可选） |
| 车辆页中间 | 平时 RTSP；硬报且有 `image_paths` → 显示最近抓拍 |
| `build_dashboard` | `alarm_snapshot` = 当前趟首张图路径 |

## 6. 口岸证据包（已实现 V1）

- 规格：`口岸证据包规格.md`
- 导出：`core/vehicle/evidence_export.py`（硬报有效趟 → `evidence/{passage_id}/` + zip）
- 抓拍节点：entry / alarm / exit（`camera_service.py` + `evidence_assets.py`）

## 7. 后续（未实现）

- ISAPI 订阅 / HTTP 带车牌 **图片** → `plate|path`
- FFmpeg 报警前后 10s 小视频
- 双机位 RTSP

## 8. 海康 DS-TCG405-E 参考

- 预览：`.../Streaming/Channels/102?transportmode=unicast`
- 硬报抓图：`GET http://{host}/ISAPI/Streaming/channels/101/picture`（Digest）
