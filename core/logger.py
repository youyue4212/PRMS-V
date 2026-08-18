# -*- coding: utf-8 -*-
# env: python
"""
 Description: 
    customized logging 
 History:
   - 2024-12-13: Initial version created by Hualin Xiao.
"""



import logging
from datetime import datetime
from pathlib import Path
from core.singleton import singleton
import os

def get_home():
    home_dir = os.path.expanduser("~")
    return home_dir


@singleton
class Logger:
    def __init__(self, name='', output_path = None, file_tag = None ):
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)  # Logger keeps DEBUG; handlers control output
        log_level_env = os.environ.get("LOG_LEVEL", "INFO").upper()
        stream_level = logging.INFO
        if log_level_env == "DEBUG":
            stream_level = logging.DEBUG
        elif log_level_env == "WARNING":
            stream_level = logging.WARNING
        elif log_level_env == "ERROR":
            stream_level = logging.ERROR
        # 记录级别供文件 handler 复用，避免文件被逐包 DEBUG 撑爆（可用 LOG_LEVEL=DEBUG 打开）
        self.output_level = stream_level
        
        self.log_filename =''
        # Create stream handler for terminal output
        self.stream_handler = logging.StreamHandler()
        self.stream_handler.setLevel(stream_level)
        self.stream_handler.setFormatter(self.formatter)
        
        # Add stream handler only if it is not already added
        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            self.logger.addHandler(self.stream_handler)
        if output_path is None:
            output_path = get_home()
            file_tag=''

        self.write_to(output_path, file_tag)

    def write_to(self, output_path, file_tag):
        # If log_filename is provided, create file handler for logging to filename
        if not output_path:
            return 
        file_tag = f'_{str(file_tag)}' if file_tag else ''

        date_str= datetime.now().strftime('%H%M%S')

        self.log_filename= Path(output_path)/'Raysen'/f'daq_log_{file_tag}_{date_str}.txt'
        self.log_filename.parent.mkdir(parents=True, exist_ok=True)

        
        # Create file handler if it hasn't been added already
        if not any(isinstance(h, logging.FileHandler) for h in self.logger.handlers):
            file_handler = logging.FileHandler(
                self.log_filename, encoding="utf-8", errors="replace"
            )
            file_handler.setLevel(getattr(self, 'output_level', logging.INFO))
            file_handler.setFormatter(self.formatter)
            self.logger.addHandler(file_handler)
    def get_log_filename(self):
        return str(self.log_filename)

    def set_level(self, level):
        self.logger.setLevel(level)

    def tell_filename(self):
        if self.log_filename:
            print("Log filename:", self.log_filename)
        else:
            print("The log was not written to a file")

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def critical(self, message):
        self.logger.critical(message)



def get_logger():
    return Logger()

