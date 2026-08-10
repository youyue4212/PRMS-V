# -*- coding: utf-8 -*-
"""
Alarm Logger Manager
For recording alarm events and automatically saving to EXCEL files

Excel I/O runs on a background writer thread so UI / DAQ paths stay non-blocking.
Day-rotate / file create also run on the writer thread.
"""

import json
import pandas as pd
from datetime import datetime
import os
import queue
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from core.singleton import singleton


EXCEL_COLS = [
    'Timestamp', 'DateTime', 'ClientID', 'AlarmType',
    'AlarmStatus', 'PeakCountRate', 'TriggerCountRate', 'Temperature', 'HV',
    'ProductID', 'Sensitivity', 'Duration', 'Message'
]

# 有界队列：满则落盘 spool，避免卡 UI / 丢事件
WRITE_QUEUE_MAX = 500
# 内存事件列表上限（清屏前 UI 展示用）
MAX_MEMORY_EVENTS = 5000
WRITE_RETRIES = 3
WRITE_RETRY_SLEEP_S = 0.35


@dataclass
class AlarmEvent:
    """Alarm event data class"""
    timestamp: float
    client_id: str
    alarm_type: str
    alarm_status: bool
    count_rate: float  # ACTIVE=触发瞬时；INACTIVE=报警期间峰值
    temperature: float
    hv: float
    product_id: int
    sensitivity: int
    message: str
    duration: float = 0.0
    trigger_count_rate: float = 0.0
    peak_count_rate: float = 0.0


@singleton
class AlarmLogger:
    """Alarm logger manager singleton class

    上位机不重新判定报警：以设备报警位为准。
    ACTIVE 期间持续跟踪峰值 CPS；解除时记录峰值与持续时间。
    Excel 追加/建文件/日切均在后台写线程完成。
    """

    def __init__(self, log_folder: Optional[str] = None):
        self.alarm_events: List[AlarmEvent] = []
        self.active_alarms: Dict[str, bool] = {}
        self.alarm_start_times: Dict[str, float] = {}
        self.alarm_start_count_rates: Dict[str, float] = {}
        self.alarm_peak_count_rates: Dict[str, float] = {}

        if log_folder is None:
            self.log_folder = self._get_default_log_folder()
        else:
            self.log_folder = Path(log_folder)

        self.log_folder.mkdir(parents=True, exist_ok=True)
        self._spool_path = self.log_folder / "alarm_write_spool.jsonl"

        self.auto_save_interval = 300
        self.last_auto_save_time = time.time()

        self.current_excel_file = None
        self._path_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._spool_lock = threading.Lock()
        self._write_q: queue.Queue = queue.Queue(maxsize=WRITE_QUEUE_MAX)
        self._writer_stop = threading.Event()
        self._write_fail_count = 0
        self._writer = threading.Thread(
            target=self._writer_loop,
            name="AlarmExcelWriter",
            daemon=True,
        )
        self._writer.start()
        # 建文件丢给写线程，不在 UI 线程同步 flush/写盘
        self._try_put(("ensure_file",), block=True, timeout=1.0)

    def _get_default_log_folder(self) -> Path:
        home_dir = Path.home()
        log_folder = home_dir / "Raysen" / "AlarmLogs"
        return log_folder

    def _event_to_row(self, event: AlarmEvent) -> dict:
        return {
            'Timestamp': event.timestamp,
            'DateTime': datetime.fromtimestamp(event.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'ClientID': event.client_id,
            'AlarmType': event.alarm_type,
            'AlarmStatus': 'ACTIVE' if event.alarm_status else 'INACTIVE',
            'PeakCountRate': event.peak_count_rate,
            'TriggerCountRate': event.trigger_count_rate,
            'Temperature': event.temperature,
            'HV': event.hv,
            'ProductID': event.product_id,
            'Sensitivity': event.sensitivity,
            'Duration': f"{event.duration:.3f}" if event.duration > 0 else "",
            'Message': event.message,
        }

    def _try_put(self, item: tuple, block: bool = False, timeout: float = 0.05) -> bool:
        if self._writer_stop.is_set():
            if item[0] == "append":
                self._append_spool_rows([item[1]])
            return False
        try:
            self._write_q.put(item, block=block, timeout=timeout)
            return True
        except queue.Full:
            if item[0] == "append":
                # 队列满：立刻落盘 spool，避免静默丢事件
                self._append_spool_rows([item[1]])
                print("Alarm Excel queue full → row spilled to spool")
            return False

    def log_alarm_event(self,
                       client_id: str,
                       alarm_status: bool,
                       count_rate: float,
                       temperature: float,
                       hv: float,
                       product_id: int,
                       sensitivity: int,
                       alarm_type: str = "Radiation",
                       message: str = ""):
        """设备报警位边沿变化时记录；ACTIVE 期间持续更新峰值 CPS。"""
        current_time = time.time()
        previous_status = self.active_alarms.get(client_id, False)

        # 仍在报警中：只更新峰值，不写新行
        if previous_status and alarm_status:
            prev_peak = self.alarm_peak_count_rates.get(client_id, count_rate)
            self.alarm_peak_count_rates[client_id] = max(prev_peak, count_rate)
            return None

        # 无边沿变化则不记
        if previous_status == alarm_status:
            return None

        duration = 0.0
        trigger_count_rate = count_rate
        peak_count_rate = count_rate
        event_count_rate = count_rate

        if alarm_status:
            self.alarm_start_times[client_id] = current_time
            self.alarm_start_count_rates[client_id] = count_rate
            self.alarm_peak_count_rates[client_id] = count_rate
            trigger_count_rate = count_rate
            peak_count_rate = count_rate
            event_count_rate = count_rate
        else:
            start_time = self.alarm_start_times.pop(client_id, current_time)
            duration = current_time - start_time
            trigger_count_rate = self.alarm_start_count_rates.pop(client_id, count_rate)
            peak_count_rate = self.alarm_peak_count_rates.pop(client_id, trigger_count_rate)
            event_count_rate = peak_count_rate

        event = AlarmEvent(
            timestamp=current_time,
            client_id=client_id,
            alarm_type=alarm_type,
            alarm_status=alarm_status,
            count_rate=event_count_rate,
            temperature=temperature,
            hv=hv,
            product_id=product_id,
            sensitivity=sensitivity,
            message=message if message else self._generate_alarm_message(
                alarm_status, alarm_type, duration, event_count_rate,
                trigger_count_rate, peak_count_rate
            ),
            duration=duration,
            trigger_count_rate=trigger_count_rate,
            peak_count_rate=peak_count_rate
        )

        self.alarm_events.append(event)
        if len(self.alarm_events) > MAX_MEMORY_EVENTS:
            # 保留最近事件供 UI；Excel 由写线程负责持久化
            del self.alarm_events[:-MAX_MEMORY_EVENTS]
        self.active_alarms[client_id] = alarm_status

        status_text = "start" if alarm_status else "end"
        duration_text = f", duration: {duration:.1f} seconds" if not alarm_status and duration > 0 else ""
        print(f"Alarm event recorded: client {client_id} - {alarm_type} alarm {status_text}{duration_text} - "
              f"trigger: {trigger_count_rate:.1f} cps, peak: {peak_count_rate:.1f} cps - {event.message}")

        self._enqueue_excel_row(event)
        self._check_and_rotate_file()
        self._check_auto_save()

        return event

    def _generate_alarm_message(self, alarm_status: bool, alarm_type: str, duration: float = 0.0,
                                count_rate: float = 0.0, trigger_count_rate: float = 0.0,
                                peak_count_rate: float = 0.0) -> str:
        if alarm_status:
            return f"{alarm_type} alarm triggered at {trigger_count_rate:.1f} cps"
        else:
            if duration > 0:
                if duration < 60:
                    duration_str = f"{duration:.1f}s"
                elif duration < 3600:
                    duration_str = f"{duration / 60:.1f}min"
                else:
                    duration_str = f"{duration / 3600:.1f}h"
                return (f"{alarm_type} alarm cleared, peak {peak_count_rate:.1f} cps "
                        f"(triggered at {trigger_count_rate:.1f} cps, lasted {duration_str})")
            return (f"{alarm_type} alarm cleared, peak {peak_count_rate:.1f} cps "
                    f"(triggered at {trigger_count_rate:.1f} cps)")

    def _enqueue_excel_row(self, event: AlarmEvent):
        """UI 线程只入队行数据；路径/建文件由写线程决定。"""
        self._try_put(("append", self._event_to_row(event)))

    def _writer_loop(self):
        pending: List[dict] = []
        batch_limit = 25
        idle_flush_s = 0.4

        while not self._writer_stop.is_set():
            try:
                item = self._write_q.get(timeout=idle_flush_s)
            except queue.Empty:
                if pending:
                    self._flush_pending(pending)
                    pending = []
                self._drain_spool_into_excel()
                continue

            kind = item[0]
            if kind == "stop":
                if pending:
                    self._flush_pending(pending)
                    pending = []
                self._drain_spool_into_excel()
                break
            if kind == "flush":
                if pending:
                    self._flush_pending(pending)
                    pending = []
                self._drain_spool_into_excel()
                done_evt = item[1]
                if done_evt is not None:
                    done_evt.set()
                continue
            if kind == "ensure_file":
                if pending:
                    self._flush_pending(pending)
                    pending = []
                self._ensure_excel_file(force_new=False)
                continue
            if kind == "rotate":
                if pending:
                    self._flush_pending(pending)
                    pending = []
                self._ensure_excel_file(force_new=True)
                continue
            if kind == "append":
                self._ensure_excel_file(force_new=False)
                pending.append(item[1])
                if len(pending) >= batch_limit:
                    self._flush_pending(pending)
                    pending = []

        # drain remaining after stop
        while True:
            try:
                item = self._write_q.get_nowait()
            except queue.Empty:
                break
            if item[0] == "append":
                pending.append(item[1])
            elif item[0] == "flush" and item[1] is not None:
                item[1].set()
        if pending:
            self._flush_pending(pending)
        self._drain_spool_into_excel()

    def _file_needs_rotate(self, path: Optional[Path]) -> bool:
        if path is None:
            return True
        if not path.exists():
            return True
        try:
            file_date = datetime.fromtimestamp(os.path.getctime(path)).date()
        except OSError:
            return True
        return file_date != datetime.now().date()

    def _ensure_excel_file(self, force_new: bool = False):
        """仅写线程调用：保证当日有效 xlsx 存在。"""
        with self._path_lock:
            path = self.current_excel_file
        need_new = force_new or self._file_needs_rotate(path)
        if not need_new:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_path = self.log_folder / f"alarm_log_{timestamp}.xlsx"
        df = pd.DataFrame(columns=EXCEL_COLS)
        try:
            with self._io_lock:
                from core.excel_io import dataframe_to_excel_atomic
                size = dataframe_to_excel_atomic(df, new_path)
            with self._path_lock:
                self.current_excel_file = new_path
            print(f"Created new alarm log file: {new_path} ({size} bytes)")
        except Exception as e:
            print(f"Failed to create alarm log file: {e}")
            # 保留旧 path（若仍可用），否则置空；后续 append 会再试
            if path is None or not path.exists():
                with self._path_lock:
                    self.current_excel_file = None

    def _flush_pending(self, pending: List[dict]):
        if not pending:
            return
        with self._path_lock:
            path = self.current_excel_file
        if path is None:
            self._ensure_excel_file(force_new=False)
            with self._path_lock:
                path = self.current_excel_file
        if path is None:
            self._append_spool_rows(pending)
            print("No Excel path → rows spilled to spool")
            return

        ok = False
        last_err = None
        for attempt in range(1, WRITE_RETRIES + 1):
            try:
                self._append_rows_sync(path, pending)
                ok = True
                self._write_fail_count = 0
                break
            except Exception as e:
                last_err = e
                print(f"Excel write attempt {attempt}/{WRITE_RETRIES} failed: {e}")
                time.sleep(WRITE_RETRY_SLEEP_S * attempt)

        if not ok:
            self._write_fail_count += 1
            self._append_spool_rows(pending)
            print(f"Excel write failed after retries → spool ({last_err})")

    def _append_rows_sync(self, filepath: Path, rows: List[dict]):
        if not rows:
            return
        with self._io_lock:
            if filepath.exists() and filepath.stat().st_size > 0:
                df = pd.read_excel(filepath)
            else:
                df = pd.DataFrame(columns=EXCEL_COLS)

            df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
            from core.excel_io import dataframe_to_excel_atomic
            dataframe_to_excel_atomic(df, filepath)

    def _append_spool_rows(self, rows: List[dict]):
        if not rows:
            return
        try:
            self.log_folder.mkdir(parents=True, exist_ok=True)
            with self._spool_lock:
                with open(self._spool_path, "a", encoding="utf-8") as f:
                    for row in rows:
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            print(f"Failed to write alarm spool: {e}")

    def _drain_spool_into_excel(self):
        """把失败 spool 补写回当前 Excel（写线程空闲时）。"""
        with self._spool_lock:
            if not self._spool_path.exists():
                return
            try:
                raw = self._spool_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                print(f"Spool read failed: {e}")
                return
            if not raw:
                try:
                    self._spool_path.unlink()
                except OSError:
                    pass
                return
            rows = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if not rows:
                return
            # 先挪走 spool，避免写盘期间 UI 再 append 进同一文件导致丢行
            staging = self._spool_path.with_suffix(".draining.jsonl")
            try:
                if staging.exists():
                    staging.unlink()
            except OSError:
                pass
            try:
                self._spool_path.replace(staging)
            except OSError as e:
                print(f"Spool stage failed: {e}")
                return

        try:
            self._ensure_excel_file(force_new=False)
            with self._path_lock:
                path = self.current_excel_file
            if path is None:
                # 放回 spool
                with self._spool_lock:
                    try:
                        staging.replace(self._spool_path)
                    except OSError:
                        pass
                return

            self._append_rows_sync(path, rows)
            try:
                staging.unlink()
            except OSError:
                pass
            print(f"Recovered {len(rows)} alarm rows from spool → {path}")
        except Exception as e:
            print(f"Spool recover failed (will retry): {e}")
            with self._spool_lock:
                try:
                    if staging.exists():
                        # 合并回主 spool（可能已有新行）
                        extra = staging.read_text(encoding="utf-8")
                        with open(self._spool_path, "a", encoding="utf-8") as f:
                            f.write(extra if extra.endswith("\n") or not extra else extra + "\n")
                        staging.unlink()
                except Exception as e2:
                    print(f"Spool restore failed: {e2}")

    def flush(self, timeout: float = 8.0) -> bool:
        """等待后台写队列落盘。退出/合并保存前调用；日常路径勿在 UI 热路径调用。"""
        if self._writer_stop.is_set() or not self._writer.is_alive():
            return True
        done = threading.Event()
        if not self._try_put(("flush", done), block=True, timeout=1.0):
            return False
        return done.wait(timeout=timeout)

    def shutdown(self, timeout: float = 10.0):
        """应用退出时调用：刷盘并停止写线程。"""
        ok = self.flush(timeout=max(1.0, timeout * 0.6))
        self._writer_stop.set()
        self._try_put(("stop",), block=True, timeout=0.5)
        self._writer.join(timeout=timeout)
        if not ok or self._writer.is_alive():
            print("Alarm Excel shutdown: flush/join incomplete; check spool file if present")

    def _check_and_rotate_file(self):
        """UI 仅发出轮转提示，不阻塞。"""
        with self._path_lock:
            path = self.current_excel_file
        if self._file_needs_rotate(path):
            self._try_put(("rotate",))

    def _check_auto_save(self):
        # 事件已异步追加；禁止周期性全量覆写，避免清屏后冲掉文件历史
        self.last_auto_save_time = time.time()

    def save_all_events(self, filename: Optional[str] = None):
        """Merge in-memory events into Excel by key; never shrink existing history."""
        self.flush(timeout=8.0)

        if filename:
            filepath = self.log_folder / filename
        else:
            with self._path_lock:
                filepath = self.current_excel_file
        if filepath is None:
            return

        try:
            with self._io_lock:
                if filepath.exists() and filepath.stat().st_size > 0:
                    df = pd.read_excel(filepath)
                else:
                    df = pd.DataFrame(columns=EXCEL_COLS)

                if self.alarm_events:
                    data = [self._event_to_row(event) for event in self.alarm_events]
                    df = pd.concat([df, pd.DataFrame(data)], ignore_index=True)
                    subset = [c for c in ('Timestamp', 'ClientID', 'AlarmStatus') if c in df.columns]
                    if subset:
                        df = df.drop_duplicates(subset=subset, keep='last')

                if df.empty and not self.alarm_events:
                    print("No alarm events to save")
                    return

                from core.excel_io import dataframe_to_excel_atomic
                size = dataframe_to_excel_atomic(df, filepath)
            print(f"Merged/saved alarm events to: {filepath} ({size} bytes, rows={len(df)})")

        except Exception as e:
            print(f"Failed to save alarm events: {e}")

    def get_recent_events(self, count: int = 100) -> List[AlarmEvent]:
        return self.alarm_events[-count:] if self.alarm_events else []

    def get_active_alarms(self) -> Dict[str, bool]:
        return self.active_alarms.copy()

    def reset_client_state(self, client_id: str):
        """清理指定客户端的报警状态（断线/复位时调用），不生成事件。"""
        self.active_alarms.pop(client_id, None)
        self.alarm_start_times.pop(client_id, None)
        self.alarm_start_count_rates.pop(client_id, None)
        self.alarm_peak_count_rates.pop(client_id, None)

    def clear_events(self, clear_active_state: bool = False):
        """Clear on-screen event list.

        By default keep active_alarms / peak tracking so edge logging stays correct
        while an alarm is still physically active. Excel files are never deleted here.
        """
        self.alarm_events.clear()
        if clear_active_state:
            self.active_alarms.clear()
            self.alarm_start_times.clear()
            self.alarm_start_count_rates.clear()
            self.alarm_peak_count_rates.clear()
        print("Cleared displayed alarm events (active_state=%s)" % clear_active_state)

    def get_statistics(self) -> Dict:
        now = datetime.now()
        day_start = datetime(now.year, now.month, now.day).timestamp()

        if not self.alarm_events:
            return {
                'total_events': 0,
                'today_events': 0,
                'active_alarms': 0,
                'alarm_types': {},
                'clients': {},
                'last_event': None,
            }

        alarm_types = {}
        # 今日报警次数：只计触发边沿，解除不算（一次周期 = 1）
        today_events = 0
        for event in self.alarm_events:
            alarm_types[event.alarm_type] = alarm_types.get(event.alarm_type, 0) + 1
            if float(event.timestamp or 0) >= day_start and bool(event.alarm_status):
                today_events += 1

        clients = {}
        for event in self.alarm_events:
            if event.client_id not in clients:
                clients[event.client_id] = {'total': 0, 'active': 0}
            clients[event.client_id]['total'] += 1
            if event.alarm_status:
                clients[event.client_id]['active'] += 1

        return {
            'total_events': len(self.alarm_events),
            'today_events': today_events,
            'active_alarms': sum(self.active_alarms.values()),
            'alarm_types': alarm_types,
            'clients': clients,
            'last_event': self.alarm_events[-1] if self.alarm_events else None,
        }


def get_alarm_logger() -> AlarmLogger:
    return AlarmLogger()
