"""Combine a single participant's HR and EDA CSVs (parsed by
EmotiBitDataParser) into one time-aligned dataset.

Usage:
    python -m dual_emotibit_viewer.offline.combine_csv \\
        --hr path/to/_HR.csv --eda path/to/_EA.csv --out combined

Produces:
    combined_long.csv  -- one row per sample: timestamp, signal, value
    combined_wide.csv  -- resampled to a common time grid, one column per
                          signal (HR, EDA), for spreadsheet-style analysis
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

TIMESTAMP_CANDIDATES = ["EpochTimestamp", "LocalTimestamp"]


def _load_signal_csv(path: Path, signal: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts_col = next((c for c in TIMESTAMP_CANDIDATES if c in df.columns), None)
    if ts_col is None:
        raise ValueError(
            f"{path}: none of {TIMESTAMP_CANDIDATES} found in columns {list(df.columns)}"
        )
    value_col = signal if signal in df.columns else df.columns[-1]
    out = df[[ts_col, value_col]].dropna()
    out.columns = ["timestamp", "value"]
    return out


def build_long_dataframe(inputs: dict[str, Path]) -> pd.DataFrame:
    frames = []
    for signal, path in inputs.items():
        sig_df = _load_signal_csv(path, signal)
        sig_df["signal"] = signal
        frames.append(sig_df[["timestamp", "signal", "value"]])
    long_df = pd.concat(frames, ignore_index=True).sort_values("timestamp")
    return long_df.reset_index(drop=True)


def build_wide_dataframe(long_df: pd.DataFrame, resample_hz: float) -> pd.DataFrame:
    t_min, t_max = long_df["timestamp"].min(), long_df["timestamp"].max()
    grid = np.arange(t_min, t_max, 1.0 / resample_hz)
    wide = pd.DataFrame({"timestamp": grid})
    for signal, group in long_df.groupby("signal"):
        group = group.sort_values("timestamp")
        wide[signal] = np.interp(grid, group["timestamp"], group["value"])
    return wide


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hr", type=Path, required=True, help="Path to the participant's _HR.csv")
    parser.add_argument("--eda", type=Path, required=True, help="Path to the participant's _EA.csv")
    parser.add_argument("--out", type=Path, required=True, help="Output path prefix, e.g. ./combined")
    parser.add_argument("--resample-hz", type=float, default=15.0, help="Common grid rate for the wide CSV (default 15 Hz, matching EDA)")
    args = parser.parse_args()

    long_df = build_long_dataframe({"HR": args.hr, "EDA": args.eda})
    wide_df = build_wide_dataframe(long_df, args.resample_hz)

    long_path = args.out.with_name(args.out.name + "_long.csv")
    wide_path = args.out.with_name(args.out.name + "_wide.csv")
    long_df.to_csv(long_path, index=False)
    wide_df.to_csv(wide_path, index=False)

    print(f"Wrote {len(long_df)} samples -> {long_path}")
    print(f"Wrote {len(wide_df)} rows @ {args.resample_hz} Hz -> {wide_path}")


if __name__ == "__main__":
    main()
