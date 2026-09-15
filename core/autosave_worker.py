# -*- coding: utf-8 -*-
"""Background auto-save: snapshot on UI thread, Excel write in QThread."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal


def write_autosave_job(job: Dict[str, Any]) -> Tuple[int, float, int]:
    """Write one pre-snapshotted client job to xlsx (no UI access)."""
    filename = job["filename"]
    spectrum_data_to_save = np.asarray(job["spectrum"], dtype=float)
    time_series_data = list(job["time_series"] or [])
    client_info = dict(job.get("client_info") or {})
    meta = dict(job.get("meta") or {})
    probe = meta.get("label") or job.get("client_id") or "probe"
    loc = meta.get("location") or ""
    ip = meta.get("ip") or ""
    is_tcp_mode = bool(job.get("is_tcp_mode", True))

    def _token(text: str) -> str:
        s = str(text or "").replace("¡¤", "-").replace(" ", "")
        out = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in s)
        while "__" in out:
            out = out.replace("__", "_")
        return out.strip("._") or ""

    spec_col = _token("_".join([probe, loc])) or "Spectrum"
    spec_col = "Counts_%s" % spec_col if spec_col != "Spectrum" else "Spectrum"

    df_spectrum = pd.DataFrame({
        "Channel": list(range(len(spectrum_data_to_save))),
        spec_col: spectrum_data_to_save,
    })
    ts_cols = [
        "Probe", "Location", "IP",
        "Timestamp", "Counter", "Temperature", "HV", "Spectrum_Counts",
    ]
    if time_series_data:
        timestamps, counters, temperatures, hvs, spec_counts = zip(*time_series_data)
        n = len(timestamps)
        df_time_series = pd.DataFrame({
            "Probe": [probe] * n,
            "Location": [loc] * n,
            "IP": [ip] * n,
            "Timestamp": [
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t)))
                for t in timestamps
            ],
            "Counter": counters,
            "Temperature": temperatures,
            "HV": hvs,
            "Spectrum_Counts": spec_counts,
        })
    else:
        df_time_series = pd.DataFrame(columns=ts_cols)

    spec_kind = job.get("spectrum_kind") or "cumulative"
    df_client_info = pd.DataFrame({
        "Probe": [probe],
        "Location": [loc or "--"],
        "IP": [ip or "--"],
        "Mode": ["TCP" if is_tcp_mode else "Serial"],
        "Client_ID": [job.get("client_id") or ""],
        "Product_ID": [client_info.get("product_id", "--")],
        "Sensitivity": [client_info.get("sensitivity", "--")],
        "Save_Time": [time.strftime("%Y-%m-%d %H:%M:%S")],
        "TimeSeries_Points": [len(time_series_data)],
        "Spectrum_Sum": [float(np.sum(spectrum_data_to_save))],
        "Spectrum_Kind": [spec_kind],
    })

    from core.excel_io import write_excel_atomic

    def _write(tmp: str):
        with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
            df_spectrum.to_excel(writer, sheet_name="Spectrum", index=False)
            df_time_series.to_excel(writer, sheet_name="TimeSeries", index=False)
            df_client_info.to_excel(writer, sheet_name="DeviceInfo", index=False)

    size = write_excel_atomic(filename, _write, min_bytes=200)
    return len(time_series_data), float(np.sum(spectrum_data_to_save)), size


class AutoSaveWorker(QThread):
    """Write autosave jobs off the UI thread."""

    finished_ok = pyqtSignal(int, object, object)  # saved_count, logs, saved_client_ids

    def __init__(self, jobs: List[Dict[str, Any]]):
        super().__init__()
        self.jobs = list(jobs or [])
        self.result = None

    def run(self):
        logs: List[Tuple[str, str]] = []
        saved = 0
        saved_cids: List[str] = []
        for job in self.jobs:
            cid = job.get("client_id") or "?"
            try:
                n_ts, spec_sum, size = write_autosave_job(job)
                ident = job.get("ident") or cid
                logs.append((
                    "Auto-saved %s (probe=%s, points=%d, spectrum_sum=%.1f, bytes=%d)"
                    % (job.get("filename"), ident, n_ts, spec_sum, size),
                    "INFO",
                ))
                try:
                    from core.archive_manager import archive_file

                    archive = archive_file(
                        job.get("filename"),
                        "AutoSave",
                        metadata={
                            "client_id": cid,
                            "probe": ident,
                            "time_series_points": n_ts,
                            "spectrum_sum": spec_sum,
                            "spectrum_kind": job.get("spectrum_kind") or "segment",
                        },
                        settings=job.get("archive_settings") or {},
                    )
                    status = archive.get("archive_status")
                    if status == "archived":
                        logs.append((
                            "Archived %s -> %s"
                            % (job.get("filename"), archive.get("archive_path")),
                            "INFO",
                        ))
                    elif status == "failed":
                        logs.append((
                            "Archive failed for %s: %s"
                            % (job.get("filename"), archive.get("error") or archive.get("manifest_error")),
                            "WARNING",
                        ))
                except Exception as e:
                    logs.append(("Archive record failed for %s: %s" % (job.get("filename"), e), "WARNING"))
                saved += 1
                if cid and cid != "?":
                    saved_cids.append(cid)
            except Exception as e:
                logs.append(("Auto-save failed for %s: %s" % (cid, e), "ERROR"))
        self.result = (saved, logs, saved_cids)
        self.finished_ok.emit(saved, logs, saved_cids)
