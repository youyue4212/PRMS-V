import os
from datetime import datetime


class RawLogger:
    def __init__(self, folder_path, log=None, prefix="gspc", extension=".bin"):
        self.folder_path = folder_path
        self.prefix = prefix
        self.log = log
        self.extension = extension
        self.current_file = None
        self.write_count = 0
        self.current_timestamp = None
        os.makedirs(self.folder_path, exist_ok=True)
        self.is_enabled = True
        self.filepath=None


    def set_enabled(self, stat):
        self.is_enabled = stat

    def _get_log_filename(self ):
        timestamp_str=datetime.now().strftime("%Y%m%d%H%M")

        return os.path.join(self.folder_path, f"{self.prefix}_{timestamp_str}{self.extension}")

    def stop(self):
        print('stop')
        self.close()

    def _rotate_file_if_needed(self):
        if self.write_count >= 10000 or self.current_file is None:
            if self.current_file:
                self.current_file.close()
            self.filepath = self._get_log_filename()
            print(self.filepath)
            
            self.current_file = open(self.filepath, "ab")
            if self.log is not None:
                self.log(f"Logging raw packets to {self.filepath}")
            self.write_count = 0

    def write(self, data: bytes):
        print(self.is_enabled, data)
        if self.is_enabled:
            self._rotate_file_if_needed()
            self.current_file.write(data)
            self.write_count += 1

    def flush(self):
        if self.current_file:
            self.current_file.flush()

    def close(self):
        if self.current_file:
            self.log(f"Raw packets has been written to {self.filepath}")
            self.current_file.close()
            self.current_file = None
