import os
from datetime import datetime


class RawLogger:
    """原始包落盘：满 max_writes 或跨小时换新文件，文件名带 YYYYMMDD。"""

    def __init__(self, folder_path, log=None, prefix="gspc", extension=".bin", max_writes=10000):
        self.folder_path = folder_path
        self.prefix = prefix
        self.log = log
        self.extension = extension
        self.max_writes = int(max_writes)
        self.current_file = None
        self.write_count = 0
        self.current_hour_key = None
        os.makedirs(self.folder_path, exist_ok=True)
        self.is_enabled = True
        self.filepath = None

    def set_enabled(self, stat):
        self.is_enabled = stat

    def _get_log_filename(self):
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(
            self.folder_path, "%s_%s%s" % (self.prefix, timestamp_str, self.extension)
        )

    def stop(self):
        self.close()

    def _rotate_file_if_needed(self):
        hour_key = datetime.now().strftime("%Y%m%d%H")
        need = (
            self.current_file is None
            or self.write_count >= self.max_writes
            or self.current_hour_key != hour_key
        )
        if not need:
            return
        if self.current_file:
            self.current_file.close()
        self.filepath = self._get_log_filename()
        self.current_file = open(self.filepath, "ab")
        self.current_hour_key = hour_key
        self.write_count = 0
        if self.log is not None:
            self.log("Logging raw packets to %s" % self.filepath)

    def write(self, data: bytes):
        if self.is_enabled:
            self._rotate_file_if_needed()
            self.current_file.write(data)
            self.write_count += 1

    def flush(self):
        if self.current_file:
            self.current_file.flush()

    def close(self):
        if self.current_file:
            if self.log:
                self.log("Raw packets has been written to %s" % self.filepath)
            self.current_file.close()
            self.current_file = None
            self.current_hour_key = None
