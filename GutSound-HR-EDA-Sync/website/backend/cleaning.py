"""Outlier rejection + smoothing for HR and EDA.

EDA thresholds are taken directly from a published, peer-reviewed method:
    Kleckner et al. (2018), "Simple, Transparent, and Flexible Automated
    Quality Assessment Procedures for Ambulatory Electrodermal Activity
    Data", IEEE Transactions on Biomedical Engineering.
    (reference implementation: https://github.com/iankleckner/EDAQA)
Their rules: valid range 0.05-60 uS, max slope +/-10 uS/s, and -- when a
sample fails either check -- the surrounding +/-5s is also marked invalid,
since contact-loss/motion episodes don't cleanly start and end at a single
sample. This module only spreads *forward* 5s from a detected artifact:
Kleckner's original is a batch/offline procedure that can also invalidate
the preceding 5s, which isn't possible in a live, low-latency stream
without buffering (that would need to look into the future to decide the
past). Backward-spreading would need to happen as an offline pass -- see
offline/view_recording.py, which does not currently do this.

HR has no directly-applicable published method here: the well-established
one, Lipponen & Tarvainen (2019) (used by Kubios HRV), flags a beat by
comparing its RR-interval to the local median RR-interval of surrounding
beats, with the threshold itself scaled by heart rate (Kubios' "medium"
setting is roughly a 25% deviation from the local median at a 60 bpm
reference). That method needs individual beat-to-beat RR intervals, which
EmotiBit's LSL "HR" channel does not expose (only the already-computed bpm
value) -- so this only borrows the *shape* of that approach (deviation
from a local median, as a percentage rather than a fixed bpm/s) rather
than reproducing it.

Rejected samples are dropped (not clamped or filled) so the recording
stays honest about what was and wasn't trusted -- the live plot's
continuity (holding the last good value across a gap) is a display-only
concern handled in app.py, not here.
"""
import statistics
from collections import deque


class _RangeRejector:
    """Hard floor/ceiling check only (no rate/deviation check)."""

    def __init__(self, value_range: tuple[float, float]):
        self._lo, self._hi = value_range

    def in_range(self, value: float) -> bool:
        return self._lo <= value <= self._hi


class _MedianSmoother:
    def __init__(self, window: int):
        self._buf: deque[float] = deque(maxlen=window)

    def smooth(self, value: float) -> float:
        self._buf.append(value)
        return statistics.median(self._buf)


class _MovingAverageSmoother:
    def __init__(self, window: int):
        self._buf: deque[float] = deque(maxlen=window)

    def smooth(self, value: float) -> float:
        self._buf.append(value)
        return sum(self._buf) / len(self._buf)


class HrCleaner:
    """Range 60-200 bpm (user-specified); rejects a value that deviates
    from the local median of the last few *accepted* readings by more than
    ~25% (approximating Kubios/Lipponen & Tarvainen's "medium" sensitivity,
    adapted to work on bpm values instead of raw RR-intervals -- see module
    docstring); final 5-sample rolling median smooth."""

    def __init__(
        self,
        value_range: tuple[float, float] = (60.0, 200.0),
        max_relative_deviation: float = 0.25,
        local_median_window: int = 7,
        smooth_window: int = 5,
    ):
        self._range = _RangeRejector(value_range)
        self._max_relative_deviation = max_relative_deviation
        self._recent_accepted: deque[float] = deque(maxlen=local_median_window)
        self._smoother = _MedianSmoother(smooth_window)

    def process(self, t: float, value: float) -> float | None:
        if not self._range.in_range(value):
            return None
        if self._recent_accepted:
            local_median = statistics.median(self._recent_accepted)
            if abs(value - local_median) / local_median > self._max_relative_deviation:
                return None
        self._recent_accepted.append(value)
        return self._smoother.smooth(value)


class EdaCleaner:
    """Kleckner et al. (2018): range 0.05-60 uS, max slope 10 uS/s, and a
    5s forward quarantine after any rejected sample. ~1.3s moving-average
    window (20 samples @ 15 Hz) smooths sensor noise without flattening
    genuine SCR shapes."""

    def __init__(
        self,
        value_range: tuple[float, float] = (0.05, 60.0),
        max_rate_per_s: float = 10.0,
        spread_radius_s: float = 5.0,
        smooth_window: int = 20,
    ):
        self._range = _RangeRejector(value_range)
        self._max_rate_per_s = max_rate_per_s
        self._spread_radius_s = spread_radius_s
        self._smoother = _MovingAverageSmoother(smooth_window)
        self._last_t: float | None = None
        self._last_value: float | None = None
        self._invalid_until: float | None = None

    def process(self, t: float, value: float) -> float | None:
        if self._invalid_until is not None and t <= self._invalid_until:
            return None

        valid = self._range.in_range(value)
        if valid and self._last_t is not None:
            dt = max(t - self._last_t, 1e-3)
            if abs(value - self._last_value) / dt > self._max_rate_per_s:
                valid = False

        if not valid:
            self._invalid_until = t + self._spread_radius_s
            return None

        self._last_t = t
        self._last_value = value
        return self._smoother.smooth(value)


def make_cleaner(signal: str):
    if signal == "HR":
        return HrCleaner()
    if signal == "EDA":
        return EdaCleaner()
    raise ValueError(f"No cleaner defined for signal {signal!r}")
