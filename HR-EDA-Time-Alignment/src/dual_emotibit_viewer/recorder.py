"""Streams a single participant's aligned (signal, raw_value, cleaned_value)
samples to a long-format CSV.

Long format (one row per sample, tagged by signal) avoids forcing HR
(irregular rate, event-driven) and EDA (steady ~15 Hz) onto a shared grid
in real time. Resampling/pivoting to a common timeline is a one-line pandas
op done afterwards -- see offline/view_recording.py.

Both the raw (as EmotiBit reported it) and cleaned (outlier-rejected +
smoothed, see cleaning.py) values are kept -- cleaning only affects the
live plot and the "cleaned_value" column, never discards anything from
the recording itself. cleaned_value is blank when that sample was
rejected as an artifact.
"""
import csv
import threading
import time
from pathlib import Path

import pylsl


class CsvRecorder:
    def __init__(self, out_path: Path):
        self._out_path = out_path
        self._lock = threading.Lock()
        self._file = None
        self._writer = None

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    def start(self, source_id: str = "") -> None:
        with self._lock:
            if self._file is not None:
                return
            self._out_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._out_path, "w", newline="", encoding="utf-8")
            # lsl_corrected_timestamp is in this process's pylsl.local_clock()
            # frame (monotonic, not Unix epoch). Anchor it to wall-clock time
            # here so it can be converted later: unix_time = anchor_unix +
            # (lsl_corrected_timestamp - anchor_lsl).
            anchor_lsl = pylsl.local_clock()
            anchor_unix = time.time()
            self._file.write(f"# anchor_lsl_clock={anchor_lsl:.6f}\n")
            self._file.write(f"# anchor_unix_time={anchor_unix:.6f}\n")
            if source_id:
                self._file.write(f"# emotibit_source_id={source_id}\n")
            self._writer = csv.writer(self._file)
            self._writer.writerow(["lsl_corrected_timestamp", "signal", "raw_value", "cleaned_value"])

    def write(self, signal: str, timestamp: float, raw_value: float, cleaned_value: float | None) -> None:
        with self._lock:
            if self._writer is None:
                return
            cleaned_str = "" if cleaned_value is None else cleaned_value
            self._writer.writerow([f"{timestamp:.6f}", signal, raw_value, cleaned_str])

    def stop(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
                self._writer = None
