"""Thread-safe rolling buffers for a single participant's signal time series."""
import threading
from collections import deque

import numpy as np


class RollingBuffer:
    """Stores (timestamp, value) samples and trims anything older than max_age_s.

    Samples must arrive with a strictly increasing timestamp -- anything
    at or before the last accepted timestamp is dropped. This guards
    against out-of-order delivery (e.g. an LSL inlet with recover=True
    re-sending a backlog of buffered samples after a brief WiFi hiccup),
    which would otherwise get appended after newer samples and make the
    plotted line zig-zag backwards in time.
    """

    def __init__(self, max_age_s: float = 120.0, max_len: int = 20_000):
        self._max_age_s = max_age_s
        self._times: deque[float] = deque(maxlen=max_len)
        self._values: deque[float] = deque(maxlen=max_len)
        self._lock = threading.Lock()
        self._last_time: float | None = None

    def append(self, timestamp: float, value: float) -> None:
        with self._lock:
            if self._last_time is not None and timestamp <= self._last_time:
                return
            self._last_time = timestamp
            self._times.append(timestamp)
            self._values.append(value)
            cutoff = timestamp - self._max_age_s
            while self._times and self._times[0] < cutoff:
                self._times.popleft()
                self._values.popleft()

    def extend(self, timestamps, values) -> None:
        with self._lock:
            for t, v in zip(timestamps, values):
                if self._last_time is not None and t <= self._last_time:
                    continue
                self._last_time = t
                self._times.append(t)
                self._values.append(v)
            if self._times:
                cutoff = self._times[-1] - self._max_age_s
                while self._times and self._times[0] < cutoff:
                    self._times.popleft()
                    self._values.popleft()

    def snapshot(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            return np.fromiter(self._times, dtype=np.float64), np.fromiter(self._values, dtype=np.float64)

    def latest(self):
        with self._lock:
            if not self._times:
                return None
            return self._times[-1], self._values[-1]


class BufferStore:
    """Keyed collection of RollingBuffers, created lazily per signal (e.g. "HR", "EDA")."""

    def __init__(self, max_age_s: float = 120.0):
        self._max_age_s = max_age_s
        self._buffers: dict[str, RollingBuffer] = {}
        self._lock = threading.Lock()

    def get(self, signal: str) -> RollingBuffer:
        with self._lock:
            buf = self._buffers.get(signal)
            if buf is None:
                buf = RollingBuffer(max_age_s=self._max_age_s)
                self._buffers[signal] = buf
            return buf

    def keys(self):
        with self._lock:
            return list(self._buffers.keys())
