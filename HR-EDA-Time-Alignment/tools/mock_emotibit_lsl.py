"""Simulates one EmotiBit's "HR" and "EDA" LSL outlets, for testing the
viewer without real hardware. Mirrors what EmotiBit Oscilloscope publishes
once "Send data via" is set to LSL: stream names "HR" and "EDA", HR at an
irregular ~1 Hz, EDA at a steady 15 Hz (matching EmotiBit's defaults).

Signal shapes are meant to look like plausible physiology, not just noise:
- EDA: a slow, mean-reverting tonic baseline plus occasional phasic SCRs
  (skin conductance responses) shaped as a fast rise / slow exponential
  decay bump, the way real EDA looks (not a clean sine wave).
- HR: a mean-reverting random walk (slow arousal-driven drift) plus a small
  respiratory sinus arrhythmia ripple, instead of independent per-beat
  white noise.

Usage: python tools/mock_emotibit_lsl.py
"""
import math
import random
import time

import pylsl

EDA_RATE_HZ = 15.0
SOURCE_ID = "MOCK-DEVICE-A"

EDA_NORMAL_RANGE = (1.0, 8.0)
HR_NORMAL_RANGE = (55.0, 100.0)


class RealisticEda:
    """Mean-reverting tonic baseline (whose center itself wanders slowly)
    plus occasional phasic SCR bumps."""

    def __init__(self, base_level: float, rng: random.Random):
        self._rng = rng
        self._base_level = base_level
        self._tonic = base_level
        self._scr_start_t: float | None = None
        self._scr_amplitude = 0.0
        self._next_scr_at = rng.uniform(8.0, 25.0)

    def value_at(self, t: float, dt: float) -> float:
        self._base_level += self._rng.uniform(-0.01, 0.01)
        self._base_level = min(max(self._base_level, EDA_NORMAL_RANGE[0] + 0.5), EDA_NORMAL_RANGE[1] - 1.5)

        self._tonic += dt * (0.015 * (self._base_level - self._tonic) + self._rng.uniform(-0.03, 0.03))

        if self._scr_start_t is None and t >= self._next_scr_at:
            self._scr_start_t = t
            self._scr_amplitude = self._rng.uniform(0.3, 1.1)

        phasic = 0.0
        if self._scr_start_t is not None:
            elapsed = t - self._scr_start_t
            rise_tau, decay_tau = 1.5, self._rng.uniform(6.0, 12.0)
            phasic = self._scr_amplitude * (1 - math.exp(-elapsed / rise_tau)) * math.exp(-elapsed / decay_tau)
            if elapsed > 40.0:
                self._scr_start_t = None
                self._next_scr_at = t + self._rng.uniform(8.0, 25.0)

        noise = self._rng.uniform(-0.01, 0.01)
        value = self._tonic + phasic + noise
        return min(max(value, EDA_NORMAL_RANGE[0]), EDA_NORMAL_RANGE[1])


class RealisticHr:
    """Mean-reverting random walk (whose center itself wanders slowly) plus
    a small respiratory sinus arrhythmia ripple."""

    def __init__(self, base_bpm: float, rng: random.Random):
        self._rng = rng
        self._base_bpm = base_bpm
        self._level = base_bpm
        self._resp_phase = rng.uniform(0, 2 * math.pi)
        self._resp_freq_hz = rng.uniform(0.15, 0.32)  # ~9-19 breaths/min

    def next_value(self, t: float) -> float:
        self._base_bpm += self._rng.uniform(-0.15, 0.15)
        self._base_bpm = min(max(self._base_bpm, HR_NORMAL_RANGE[0] + 5), HR_NORMAL_RANGE[1] - 5)

        self._level += 0.05 * (self._base_bpm - self._level) + self._rng.uniform(-1.0, 1.0)
        resp_ripple = 2.5 * math.sin(2 * math.pi * self._resp_freq_hz * t + self._resp_phase)
        beat_noise = self._rng.uniform(-0.4, 0.4)
        value = self._level + resp_ripple + beat_noise
        return min(max(value, HR_NORMAL_RANGE[0]), HR_NORMAL_RANGE[1])

    @property
    def current_bpm(self) -> float:
        return self._level


def main() -> None:
    hr_info = pylsl.StreamInfo("HR", "HeartRate", 1, 0.0, "float32", SOURCE_ID)
    eda_info = pylsl.StreamInfo("EDA", "EDA", 1, EDA_RATE_HZ, "float32", SOURCE_ID)
    hr_outlet = pylsl.StreamOutlet(hr_info)
    eda_outlet = pylsl.StreamOutlet(eda_info)

    rng = random.Random(1000)
    eda_model = RealisticEda(base_level=3.5, rng=rng)
    hr_model = RealisticHr(base_bpm=74, rng=rng)

    start = time.time()
    next_hr_at = start
    next_eda_at = start
    last_eda_t = 0.0

    print(f"Streaming mock HR/EDA with source_id={SOURCE_ID} (Ctrl+C to stop)")

    try:
        while True:
            now = time.time()
            if now >= next_eda_at:
                t = now - start
                value = eda_model.value_at(t, dt=t - last_eda_t)
                last_eda_t = t
                eda_outlet.push_sample([value])
                next_eda_at += 1.0 / EDA_RATE_HZ
            if now >= next_hr_at:
                t = now - start
                value = hr_model.next_value(t)
                hr_outlet.push_sample([value])
                # Beat interval follows this device's own current rate (60/bpm), with jitter.
                next_hr_at = now + (60.0 / hr_model.current_bpm) * rng.uniform(0.85, 1.15)
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopping mock stream.")


if __name__ == "__main__":
    main()
