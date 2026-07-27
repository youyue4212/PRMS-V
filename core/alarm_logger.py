# -*- coding: utf-8 -*-
"""
Alarm Logger Manager
For recording alarm events and automatically saving to EXCEL files
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os
import time
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from core.singleton import singleton


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

        self.auto_save_interval = 300
        self.last_auto_save_time = time.time()

        self.current_excel_file = None
        self._create_new_excel_file()

    def _get_default_log_folder(self) -> Path:
        home_dir = Path.home()
        log_folder = home_dir / "Raysen" / "AlarmLogs"
        return log_folder

    def _create_new_excel_file(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"alarm_log_{timestamp}.xlsx"
        self.current_excel_file = self.log_folder / filename

        df = pd.DataFrame(columns=[
            'Timestamp', 'DateTime', 'ClientID', 'AlarmType',
            'AlarmStatus', 'PeakCountRate', 'TriggerCountRate', 'Temperature', 'HV',
            'ProductID', 'Sensitivity', 'Duration', 'Message'
        ])
        try:
            from core.excel_io import dataframe_to_excel_atomic
            size = dataframe_to_excel_atomic(df, self.current_excel_file)
            print(f"Created new alarm log file: {self.current_excel_file} ({size} bytes)")
        except Exception as e:
            print(f"Failed to create alarm log file: {e}")
            self.current_excel_file = None

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
        self.active_alarms[client_id] = alarm_status

        status_text = "start" if alarm_status else "end"
        duration_text = f", duration: {duration:.1f} seconds" if not alarm_status and duration > 0 else ""
        print(f"Alarm event recorded: client {client_id} - {alarm_type} alarm {status_text}{duration_text} - "
              f"trigger: {trigger_count_rate:.1f} cps, peak: {peak_count_rate:.1f} cps - {event.message}")

        self._save_to_excel(event)
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

    def _save_to_excel(self, event: AlarmEvent):
        try:
            if self.current_excel_file is None:
                self._create_new_excel_file()
            if self.current_excel_file is None:
                return

            cols = [
                'Timestamp', 'DateTime', 'ClientID', 'AlarmType',
                'AlarmStatus', 'PeakCountRate', 'TriggerCountRate', 'Temperature', 'HV',
                'ProductID', 'Sensitivity', 'Duration', 'Message'
            ]
            if self.current_excel_file.exists() and self.current_excel_file.stat().st_size > 0:
                df = pd.read_excel(self.current_excel_file)
            else:
                df = pd.DataFrame(columns=cols)

            new_row = {
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
                'Message': event.message
            }

            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            from core.excel_io import dataframe_to_excel_atomic
            dataframe_to_excel_atomic(df, self.current_excel_file)

        except Exception as e:
            print(f"Failed to save alarm event to EXCEL: {e}")

    def _check_and_rotate_file(self):
        if self.current_excel_file and self.current_excel_file.exists():
            try:
                file_date = datetime.fromtimestamp(os.path.getctime(self.current_excel_file)).date()
            except OSError:
                return
            current_date = datetime.now().date()
            if file_date != current_date:
                self._create_new_excel_file()

    def _check_auto_save(self):
        current_time = time.time()
        if current_time - self.last_auto_save_time >= self.auto_save_interval:
            self.save_all_events()
            self.last_auto_save_time = current_time

    def save_all_events(self, filename: Optional[str] = None):
        if not self.alarm_events:
            print("No alarm events to save")
            return

        if filename:
            filepath = self.log_folder / filename
        else:
            filepath = self.current_excel_file

        try:
            data = []
            for event in self.alarm_events:
                data.append({
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
                    'Message': event.message
                })

            df = pd.DataFrame(data)
            from core.excel_io import dataframe_to_excel_atomic
            size = dataframe_to_excel_atomic(df, filepath)
            print(f"Saved {len(self.alarm_events)} alarm events to: {filepath} ({size} bytes)")

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

    def clear_events(self):
        self.alarm_events.clear()
        self.active_alarms.clear()
        self.alarm_start_times.clear()
        self.alarm_start_count_rates.clear()
        self.alarm_peak_count_rates.clear()
        print("Cleared all alarm events")

    def get_statistics(self) -> Dict:
        if not self.alarm_events:
            return {
                'total_events': 0,
                'active_alarms': 0,
                'alarm_types': {},
                'clients': {}
            }

        alarm_types = {}
        for event in self.alarm_events:
            alarm_types[event.alarm_type] = alarm_types.get(event.alarm_type, 0) + 1

        clients = {}
        for event in self.alarm_events:
            if event.client_id not in clients:
                clients[event.client_id] = {'total': 0, 'active': 0}
            clients[event.client_id]['total'] += 1
            if event.alarm_status:
                clients[event.client_id]['active'] += 1

        return {
            'total_events': len(self.alarm_events),
            'active_alarms': sum(self.active_alarms.values()),
            'alarm_types': alarm_types,
            'clients': clients
        }


def get_alarm_logger() -> AlarmLogger:
    return AlarmLogger()
