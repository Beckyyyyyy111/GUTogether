"""Shared logic for building a 3-moment playback clip.

Locates three named 1-minute "moments" in a recording (during eating, near
end of eating, peak gut-sound activity) and joins them with silent gaps into
a single WAV suitable for playback to a participant. Used by both the GUI
(ui/annotation_panel.py) and the standalone CLI (scripts/build_playback_clip.py)
so the moment-finding logic only lives in one place.

Default moment definitions (all relative to total recording length T):
  - peak:        loudest `duration`-second window anywhere in the recording.
  - eating_mid:  centered on T/2 (i.e. starts at T/2 - duration/2).
  - eating_end:  starts at T - `eating_end_offset` seconds (default 180s / 3min).

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
DEFAULT_EATING_END_OFFSET = 180.0  # 3 minutes before the recording ends

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
                    fixed_start: float = None, search_range: tuple = None) -> tuple[float, float]:
    """Return (start_s, rms) for one moment: explicit override > explicit
    search range > the default formula for that moment type."""
    if fixed_start is not None:
        return fixed_start, rms_of(extract_segment(signal, sr, fixed_start, duration_s))

    if search_range is not None:
        return find_peak_window(signal, sr, duration_s, search_range[0], search_range[1])

    if key == "peak":
        return find_peak_window(signal, sr, duration_s, 0.0, total_s)
    if key == "eating_mid":
        start = total_s / 2 - duration_s / 2
        return start, rms_of(extract_segment(signal, sr, start, duration_s))
    if key == "eating_end":
        start = total_s - eating_end_offset
        return start, rms_of(extract_segment(signal, sr, start, duration_s))

    raise AssertionError(key)


def build_moments_clip(signal: np.ndarray, sr: int, duration_s: float = 60.0, gap_s: float = 30.0,
                        eating_end_offset: float = DEFAULT_EATING_END_OFFSET, overrides: dict = None):
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


def find_clean_candidates(signal: np.ndarray, sr: int, speech_segments_s: list,
                           duration_s: float = 60.0, top_n: int = 10,
                           min_separation_s: float = None) -> list:
    """Find the top_n loudest windows of length duration_s that don't overlap
    any speech segment, for picking clean gut-sound clips out of a long
    (e.g. shared-eating) recording instead of trusting a single automatic
    pick. Ranks by energy only (a proxy for "something acoustically active
    is happening here", not a gut-sound classifier) -- always spot-check
    candidates by ear before using one.

    Args:
        signal: mono audio samples.
        sr: sample rate.
        speech_segments_s: list of (start_s, end_s) tuples, e.g. from
            Silero VAD (see filters/speech_removal_filter.py). Any window
            overlapping any of these at all is excluded.
        duration_s: candidate window length in seconds.
        top_n: how many non-overlapping candidates to return, best first.
        min_separation_s: minimum gap between two returned candidates'
            start times, so results aren't near-duplicates of each other.
            Defaults to duration_s (fully non-overlapping candidates).

    Returns:
        List of dicts (best first): start, end, rms, db. Shorter than
        top_n if there aren't enough non-speech windows left.
    """
    win = int(round(duration_s * sr))
    if win <= 0 or win > len(signal):
        raise ValueError(f"Window of {duration_s}s does not fit in the audio.")
    if min_separation_s is None:
        min_separation_s = duration_s

    csum = np.concatenate(([0.0], np.cumsum(signal.astype(np.float64) ** 2)))
    window_energy = csum[win:] - csum[:-win]  # index i = energy of the window starting at sample i
    n_candidates = len(window_energy)

    blocked = np.zeros(n_candidates, dtype=bool)
    for seg_start_s, seg_end_s in speech_segments_s:
        seg_start = int(round(seg_start_s * sr))
        seg_end = int(round(seg_end_s * sr))
        # A window starting at sample i (covering [i, i+win)) overlaps
        # [seg_start, seg_end) iff i < seg_end and i + win > seg_start.
        lo = max(0, seg_start - win + 1)
        hi = min(n_candidates, seg_end)
        if hi > lo:
            blocked[lo:hi] = True

    energy_masked = np.where(blocked, -np.inf, window_energy)
    min_sep_samples = int(round(min_separation_s * sr))

    candidates = []
    for _ in range(top_n):
        best_idx = int(np.argmax(energy_masked))
        if not np.isfinite(energy_masked[best_idx]):
            break  # no more speech-free windows left
        rms = float(np.sqrt(window_energy[best_idx] / win))
        candidates.append({
            "start": best_idx / sr,
            "end": (best_idx + win) / sr,
            "rms": rms,
            "db": 20 * np.log10(max(rms, 1e-9)),
        })
        lo = max(0, best_idx - min_sep_samples)
        hi = min(n_candidates, best_idx + min_sep_samples)
        energy_masked[lo:hi] = -np.inf  # suppress this neighborhood so the next pick isn't a near-duplicate

    return candidates
