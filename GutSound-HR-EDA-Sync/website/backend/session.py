"""In-memory recording session: captures (relative_time, signal, raw, cleaned)
samples emitted by the LSL receiver's on_sample callback while a playback
session is active, anchored to the LSL clock timestamp play began at.

Only one session is ever active at a time (single experimenter, single
device) -- see server.py's _session_active guard.
"""
import threading


class SessionRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._start_lsl = None
        self._samples = []

    def begin(self, start_lsl: float) -> None:
        with self._lock:
            self._samples = []
            self._start_lsl = start_lsl
            self._active = True

    def on_sample(self, signal, t, raw_value, cleaned_value) -> None:
        """Registered as the LSL receiver's on_sample callback; called from
        the receiver's background pull thread for every sample, whether or
        not a session is currently recording."""
        with self._lock:
            if not self._active or self._start_lsl is None:
                return
            t_rel = t - self._start_lsl
            if t_rel < 0:
                return
            self._samples.append((t_rel, signal, raw_value, cleaned_value))

    def end(self) -> list[tuple[float, str, float, float | None]]:
        with self._lock:
            self._active = False
            samples = list(self._samples)
            self._samples = []
            return samples
