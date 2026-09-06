"""Pivot a live-recorded long-format CSV (from CsvRecorder) into a wide,
human-readable table: one row per timestamp, a *_raw and *_cleaned column
per signal (HR, EDA), with real wall-clock time restored from the
recording's anchor lines.

*_raw is EmotiBit's value untouched. *_cleaned has outlier-rejected
samples (see cleaning.py) linearly interpolated through, so it's a
complete, analysis-ready series rather than one with gaps -- the live
viewer shows the honest gaps in real time, but a finished recording is
more useful with them bridged.

Usage:
    python -m dual_emotibit_viewer.offline.view_recording \\
        data/recordings/2026-06-30_23-10-05_aligned.csv \\
        --out data/recordings/2026-06-30_23-10-05_wide.csv
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _read_anchors(path: Path) -> tuple[float, float]:
    anchor_lsl = anchor_unix = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            if "anchor_lsl_clock=" in line:
                anchor_lsl = float(line.split("=", 1)[1])
            elif "anchor_unix_time=" in line:
                anchor_unix = float(line.split("=", 1)[1])
    if anchor_lsl is None or anchor_unix is None:
        raise ValueError(f"{path}: missing anchor_lsl_clock/anchor_unix_time header lines")
    return anchor_lsl, anchor_unix


def build_wide_dataframe(long_df: pd.DataFrame, resample_hz: float) -> pd.DataFrame:
    t_min, t_max = long_df["timestamp"].min(), long_df["timestamp"].max()
    grid = np.arange(t_min, t_max, 1.0 / resample_hz)
    wide = pd.DataFrame({"timestamp": grid})

    for signal, group in long_df.groupby("signal"):
        group = group.sort_values("timestamp")
        wide[f"{signal}_raw"] = np.interp(grid, group["timestamp"], group["raw_value"])

        cleaned = group.dropna(subset=["cleaned_value"])
        if len(cleaned) >= 2:
            wide[f"{signal}_cleaned"] = np.interp(grid, cleaned["timestamp"], cleaned["cleaned_value"])
        else:
            wide[f"{signal}_cleaned"] = np.nan

    return wide


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", type=Path, help="Path to a *_aligned.csv written by the live viewer")
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: <recording>_wide.csv)")
    parser.add_argument("--resample-hz", type=float, default=15.0)
    args = parser.parse_args()

    anchor_lsl, anchor_unix = _read_anchors(args.recording)

    long_df = pd.read_csv(args.recording, comment="#")
    long_df = long_df.rename(columns={"lsl_corrected_timestamp": "timestamp"})

    wide_df = build_wide_dataframe(long_df, args.resample_hz)
    wide_df.insert(1, "unix_time", anchor_unix + (wide_df["timestamp"] - anchor_lsl))
    wide_df.insert(2, "datetime", pd.to_datetime(wide_df["unix_time"], unit="s"))

    out_path = args.out or args.recording.with_name(args.recording.stem + "_wide.csv")
    wide_df.to_csv(out_path, index=False)
    print(f"Wrote {len(wide_df)} rows @ {args.resample_hz} Hz -> {out_path}")


if __name__ == "__main__":
    main()
