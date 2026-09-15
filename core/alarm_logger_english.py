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
    timestamp: float  # timestamp
    client_id: str    # client ID
    alarm_type: str   # alarm type
    alarm_status: bool  # alarm status (True: alarm start, False: alarm end)
    count_rate: float  # count rate (cps)
    temperature: float  # temperature (deg C)
    hv: float         # high voltage (V)
    product_id: int   # product ID
    sensitivity: int  # sensitivity coefficient
    message: str      # alarm message
    duration: float = 0.0  # alarm duration (seconds), valid only when alarm ends
    trigger_count_rate: float = 0.0  # count rate when alarm triggered


@singleton
class AlarmLogger:
    """Alarm logger manager singleton class"""
    
    def __init__(self, log_folder: Optional[str] = None):
        """
        Initialize alarm logger manager
        
        Args:
            log_folder: log folder path, if None use user home directory
        """
        self.alarm_events: List[AlarmEvent] = []
        self.active_alarms: Dict[str, bool] = {}  # client ID -> whether in alarm state
        self.alarm_start_times: Dict[str, float] = {}  # client ID -> alarm start time
        self.alarm_start_count_rates: Dict[str, float] = {}  # client ID -> count rate at alarm start
        
        # Set log folder
        if log_folder is None:
            self.log_folder = self._get_default_log_folder()
        else:
            self.log_folder = Path(log_folder)
        
        # Ensure log folder exists
        self.log_folder.mkdir(parents=True, exist_ok=True)
        
        # Auto-save timer
        self.auto_save_interval = 300  # auto save every 5 minutes
        self.last_auto_save_time = time.time()
        
        # Current EXCEL file path
        self.current_excel_file = None
        self._create_new_excel_file()
    
    def _get_default_log_folder(self) -> Path:
        """Get default log folder path"""
        home_dir = Path.home()
        log_folder = home_dir / "Raysen" / "AlarmLogs"
        return log_folder
    
    def _create_new_excel_file(self):
        """Create new EXCEL file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"alarm_log_{timestamp}.xlsx"
        self.current_excel_file = self.log_folder / filename
        
        # Create empty DataFrame and save
        df = pd.DataFrame(columns=[
            'Timestamp', 'DateTime', 'ClientID', 'AlarmType', 
            'AlarmStatus', 'CountRate', 'TriggerCountRate', 'Temperature', 'HV',
            'ProductID', 'Sensitivity', 'Duration', 'Message'
        ])
        df.to_excel(self.current_excel_file, index=False)
        
        print(f"Created new alarm log file: {self.current_excel_file}")
    
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
        """
        Record alarm event
        
        Args:
            client_id: client ID
            alarm_status: alarm status (True: alarm start, False: alarm end)
            count_rate: count rate (cps)
            temperature: temperature (deg C)
            hv: high voltage (V)
            product_id: product ID
            sensitivity: sensitivity coefficient
            alarm_type: alarm type
            message: alarm message
        """
        current_time = time.time()
        
        # Check alarm status change
        previous_status = self.active_alarms.get(client_id, False)
        
        # Only record when alarm status changes
        if previous_status != alarm_status:
            # Calculate alarm duration (if alarm ends)
            duration = 0.0
            trigger_count_rate = count_rate
            
            if alarm_status:
                # Alarm start: record start time and trigger count rate
                self.alarm_start_times[client_id] = current_time
                self.alarm_start_count_rates[client_id] = count_rate
                trigger_count_rate = count_rate
            else:
                # Alarm end: calculate duration
                start_time = self.alarm_start_times.pop(client_id, current_time)
                duration = current_time - start_time
                trigger_count_rate = self.alarm_start_count_rates.pop(client_id, count_rate)
            
            # Create alarm event
            event = AlarmEvent(
                timestamp=current_time,
                client_id=client_id,
                alarm_type=alarm_type,
                alarm_status=alarm_status,
                count_rate=count_rate,
                temperature=temperature,
                hv=hv,
                product_id=product_id,
                sensitivity=sensitivity,
                message=message if message else self._generate_alarm_message(alarm_status, alarm_type, duration),
                duration=duration,
                trigger_count_rate=trigger_count_rate
            )
            
            # Add to event list
            self.alarm_events.append(event)
            
            # Update active alarm status
            self.active_alarms[client_id] = alarm_status
            
            # Print log
            status_text = "start" if alarm_status else "end"
            duration_text = f", duration: {duration:.1f} seconds" if not alarm_status and duration > 0 else ""
            print(f"Alarm event recorded: client {client_id} - {alarm_type} alarm {status_text}{duration_text} - trigger count rate: {trigger_count_rate:.1f} cps - {event.message}")
            
            # Immediately save to EXCEL file
            self._save_to_excel(event)
            
            # Check if need to create new EXCEL file (one file per day)
            self._check_and_rotate_file()
            
            # Check if need to auto-save
            self._check_auto_save()
            
            return event
        return None
    
    def _generate_alarm_message(self, alarm_status: bool, alarm_type: str, duration: float = 0.0) -> str:
        """Generate alarm message"""
        if alarm_status:
            return f"{alarm_type} alarm triggered"
        else:
            if duration > 0:
                # Format duration
                if duration < 60:
                    duration_str = f"{duration:.1f} seconds"
                elif duration < 3600:
                    minutes = duration / 60
                    duration_str = f"{minutes:.1f} minutes"
                else:
                    hours = duration / 3600
                    duration_str = f"{hours:.1f} hours"
                return f"{alarm_type} alarm cleared, lasted {duration_str}"
            else:
                return f"{alarm_type} alarm cleared"
    
    def _save_to_excel(self, event: AlarmEvent):
        """Save single event to EXCEL file"""
        try:
            # Read existing data
            if self.current_excel_file.exists():
                df = pd.read_excel(self.current_excel_file)
            else:
                df = pd.DataFrame(columns=[
                    'Timestamp', 'DateTime', 'ClientID', 'AlarmType', 
                    'AlarmStatus', 'CountRate', 'TriggerCountRate', 'Temperature', 'HV',
                    'ProductID', 'Sensitivity', 'Duration', 'Message'
                ])
            
            # Add new event
            new_row = {
                'Timestamp': event.timestamp,
                'DateTime': datetime.fromtimestamp(event.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],  # include milliseconds
                'ClientID': event.client_id,
                'AlarmType': event.alarm_type,
                'AlarmStatus': 'ACTIVE' if event.alarm_status else 'INACTIVE',
                'CountRate': event.count_rate,
                'TriggerCountRate': event.trigger_count_rate,
                'Temperature': event.temperature,
                'HV': event.hv,
                'ProductID': event.product_id,
                'Sensitivity': event.sensitivity,
                'Duration': f"{event.duration:.3f}" if event.duration > 0 else "",
                'Message': event.message
            }
            
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            
            # Save to file
            df.to_excel(self.current_excel_file, index=False)
            
        except Exception as e:
            print(f"Failed to save alarm event to EXCEL: {e}")
    
    def _check_and_rotate_file(self):
        """Check and rotate EXCEL file (create new file each day)"""
        if self.current_excel_file:
            file_date = datetime.fromtimestamp(os.path.getctime(self.current_excel_file)).date()
            current_date = datetime.now().date()
            
            if file_date != current_date:
                # Date changed, create new file
                self._create_new_excel_file()
    
    def _check_auto_save(self):
        """Check and execute auto-save"""
        current_time = time.time()
        if current_time - self.last_auto_save_time >= self.auto_save_interval:
            self.save_all_events()
            self.last_auto_save_time = current_time
    
    def save_all_events(self, filename: Optional[str] = None):
        """
        Save all alarm events to EXCEL file
        
        Args:
            filename: filename, if None use current file
        """
        if not self.alarm_events:
            print("No alarm events to save")
            return
        
        if filename:
            filepath = self.log_folder / filename
        else:
            filepath = self.current_excel_file
        
        try:
            # Create DataFrame
            data = []
            for event in self.alarm_events:
                data.append({
                    'Timestamp': event.timestamp,
                    'DateTime': datetime.fromtimestamp(event.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],  # include milliseconds
                    'ClientID': event.client_id,
                    'AlarmType': event.alarm_type,
                    'AlarmStatus': 'ACTIVE' if event.alarm_status else 'INACTIVE',
                    'CountRate': event.count_rate,
                    'TriggerCountRate': event.trigger_count_rate,
                    'Temperature': event.temperature,
                    'HV': event.hv,
                    'ProductID': event.product_id,
                    'Sensitivity': event.sensitivity,
                    'Duration': f"{event.duration:.3f}" if event.duration > 0 else "",
                    'Message': event.message
                })
            
            df = pd.DataFrame(data)
            df.to_excel(filepath, index=False)
            
            print(f"Saved {len(self.alarm_events)} alarm events to: {filepath}")
            
        except Exception as e:
            print(f"Failed to save alarm events: {e}")
    
    def get_recent_events(self, count: int = 100) -> List[AlarmEvent]:
        """Get recent alarm events"""
        return self.alarm_events[-count:] if self.alarm_events else []
    
    def get_active_alarms(self) -> Dict[str, bool]:
        """Get current active alarm status"""
        return self.active_alarms.copy()
    
    def clear_events(self):
        """Clear all alarm events"""
        self.alarm_events.clear()
        self.active_alarms.clear()
        print("Cleared all alarm events")
    
    def get_statistics(self) -> Dict:
        """Get alarm statistics"""
        if not self.alarm_events:
            return {
                'total_events': 0,
                'active_alarms': 0,
                'alarm_types': {},
                'clients': {}
            }
        
        # Count alarm types
        alarm_types = {}
        for event in self.alarm_events:
            alarm_types[event.alarm_type] = alarm_types.get(event.alarm_type, 0) + 1
        
        # Count client alarms
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
    """Get alarm logger manager singleton"""
    return AlarmLogger()
