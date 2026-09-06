"""Shared logic for building a 3-moment playback clip.

Locates three named 1-minute "moments" in a recording (during eating, near
end of eating, peak gut-sound activity) and joins them with silent gaps into
a single WAV suitable for playback to a participant. Used by both the GUI
(ui/annotation_panel.py) and the standalone CLI (scripts/build_playback_clip.py)
so the moment-finding logic only lives in one place.

Default moment definitions (all relative to total recording length T):
  - eating_mid:  centered on T/2 (i.e. starts at T/2 - duration/2).
  - eating_end:  starts at T - `eating_end_offset` seconds (default 360s / 6min).
  - peak:        loudest `duration`-second window within
                  [`peak_search_margin`, T - `peak_search_margin`] (default
                  180s / 3min on each side), excluding the start/end of the
                  recording where participants were putting on or removing
                  the OpenGut devices.

These defaults assume the recording spans roughly the meal session itself.
Pass an override (a fixed start second, or a search range to search within
instead) per moment when that assumption does not hold.
"""

from pathlib import Path

import numpy as np

MOMENT_ORDER = ("eating_mid", "eating_end", "peak")
MOMENT_LABELS = {
    "eating_mid": "during eating",
    "eating_end": "near end of eating",
    "peak": "peak gut-sound activity",
}
DEFAULT_EATING_END_OFFSET = 360.0  # 6 minutes before the recording ends
DEFAULT_PEAK_SEARCH_MARGIN = 180.0  # 3 minutes excluded from each end when searching for the peak

# Single source of truth for the fixed Participant_Gut_Sounds pipeline layout:
# raw recordings in -> processed/filtered output -> final selected playback clips.
_PARTICIPANT_GUT_SOUNDS_ROOT = Path(r"D:\AAAAAAAA\OpenGut\Participant_Gut_Sounds")
DEFAULT_ORIGINAL_SOUNDS_DIR = _PARTICIPANT_GUT_SOUNDS_ROOT / "Origianl_Sounds"
DEFAULT_PROCESSED_SOUNDS_DIR = _PARTICIPANT_GUT_SOUNDS_ROOT / "Processed_Sounds"
DEFAULT_SELECTED_SOUNDS_DIR = _PARTICIPANT_GUT_SOUNDS_ROOT / "Selected_Sounds"


def find_peak_window(signal: np.ndarray, sr: int, duration_s: float,
                      search_start_s: float, search_end_s: float) -> tuple[float, float]:
    """Return (start_seconds, rms) of the loudest window of length duration_s
    within [search_start_s, search_end_s]."""
    win = int(round(duration_s * sr))
    if win <= 0 or win > len(signal):
        raise ValueError(f"Window of {duration_s}s does not fit in the audio.")

    search_start = max(0, int(round(search_start_s * sr)))
    search_end = min(len(signal), int(round(search_end_s * sr)))
    last_valid_start = search_end - win
    if last_valid_start < search_start:
        raise ValueError(
            f"Search range [{search_start_s}, {search_end_s}]s is too short to fit a {duration_s}s window."
        )

    # Cumulative sum of squares -> O(1) energy lookup per candidate window start.
    csum = np.concatenate(([0.0], np.cumsum(signal.astype(np.float64) ** 2)))
    window_energy = csum[win:] - csum[:-win]  # index i = energy of window starting at sample i

    candidates = window_energy[search_start:last_valid_start + 1]
    best_offset = int(np.argmax(candidates))
    best_start_sample = search_start + best_offset
    rms = float(np.sqrt(candidates[best_offset] / win))
    return best_start_sample / sr, rms


def extract_segment(signal: np.ndarray, sr: int, start_s: float, duration_s: float) -> np.ndarray:
    start = int(round(start_s * sr))
    end = start + int(round(duration_s * sr))
    if start < 0 or end > len(signal):
        raise ValueError(f"Segment [{start_s:.2f}, {start_s + duration_s:.2f}]s falls outside the audio.")
    return signal[start:end]


def rms_of(segment: np.ndarray) -> float:
    return float(np.sqrt(np.mean(segment.astype(np.float64) ** 2)))


def resolve_moment(key: str, signal: np.ndarray, sr: int, duration_s: float, total_s: float,
                    eating_end_offset: float = DEFAULT_EATING_END_OFFSET,
                    peak_search_margin: float = DEFAULT_PEAK_SEARCH_MARGIN,
                    fixed_start: float = None, search_range: tuple = None) -> tuple[float, float]:
    """Return (start_s, rms) for one moment: explicit override > explicit
    search range > the default formula for that moment type."""
    if fixed_start is not None:
        return fixed_start, rms_of(extract_segment(signal, sr, fixed_start, duration_s))

    if search_range is not None:
        return find_peak_window(signal, sr, duration_s, search_range[0], search_range[1])

    if key == "peak":
        return find_peak_window(signal, sr, duration_s, peak_search_margin, total_s - peak_search_margin)
    if key == "eating_mid":
        start = total_s / 2 - duration_s / 2
        return start, rms_of(extract_segment(signal, sr, start, duration_s))
    if key == "eating_end":
        start = total_s - eating_end_offset
        return start, rms_of(extract_segment(signal, sr, start, duration_s))

    raise AssertionError(key)


def build_moments_clip(signal: np.ndarray, sr: int, duration_s: float = 60.0, gap_s: float = 30.0,
                        eating_end_offset: float = DEFAULT_EATING_END_OFFSET,
                        peak_search_margin: float = DEFAULT_PEAK_SEARCH_MARGIN, overrides: dict = None):
    """Locate the three moments and concatenate them with silence in between.

    overrides: optional dict keyed by moment ("eating_mid"/"eating_end"/"peak"),
    each value a dict with "start" (fixed second) or "range" (start, end) to
    search within, e.g. {"eating_mid": {"start": 340}}.

    Returns (combined_audio, moments) where moments is a list of dicts with
    keys: key, label, start, end, rms, db -- in playback order.
    """
    overrides = overrides or {}
    total_s = len(signal) / sr

    segments = []
    moments = []
    for key in MOMENT_ORDER:
        override = overrides.get(key, {})
        start_s, rms = resolve_moment(
            key, signal, sr, duration_s, total_s,
            eating_end_offset=eating_end_offset,
            peak_search_margin=peak_search_margin,
            fixed_start=override.get("start"),
            search_range=override.get("range"),
        )
        segments.append(extract_segment(signal, sr, start_s, duration_s))
        moments.append({
            "key": key,
            "label": MOMENT_LABELS[key],
            "start": start_s,
            "end": start_s + duration_s,
            "rms": rms,
            "db": 20 * np.log10(max(rms, 1e-9)),
        })

    silence = np.zeros(int(round(gap_s * sr)), dtype=np.float32)
    combined = np.concatenate([
        segments[0], silence,
        segments[1], silence,
        segments[2],
    ]).astype(np.float32)

    return combined, moments
