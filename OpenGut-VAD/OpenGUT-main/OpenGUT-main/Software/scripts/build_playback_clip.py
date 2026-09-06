#!/usr/bin/env python3
"""
Build a single playback WAV from three 1-minute "moments" (during eating,
near end of eating, peak gut-sound activity) found in a processed recording,
joined by silent gaps. See audio_moments.py for the moment-finding rules.

Output is saved as "<Selected_Sounds folder>/<participant-id>_playback_clip.wav" by
default -- just pass --participant-id. Use --output to save somewhere else instead.

Example:

    python build_playback_clip.py \\
        --input "Participant_Gut_Sounds/Processed_Sounds/sound_scipy_highpass_filter_1783247841_right.wav" \\
        --participant-id P01

To override a moment instead of using the default formula:

    --eating-mid-start 340
    --eating-end-range 600 780   # search this range for the loudest window
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audio_moments import (  # noqa: E402
    MOMENT_ORDER,
    MOMENT_LABELS,
    DEFAULT_EATING_END_OFFSET,
    DEFAULT_SELECTED_SOUNDS_DIR,
    build_moments_clip,
)


def load_channel(path: Path, channel: str) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    n_channels = audio.shape[1]

    if n_channels == 1:
        return audio[:, 0], sr

    if channel == "left":
        return audio[:, 0], sr
    if channel == "right":
        return audio[:, 1], sr
    if channel == "mono":
        return audio.mean(axis=1), sr

    raise ValueError(
        f"'{path.name}' has {n_channels} channels; pass --channel left/right/mono to pick one."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="Processed source WAV file.")
    parser.add_argument("--participant-id", default=None,
                         help="Participant number/code, e.g. P01. Used to name the output file "
                              "when --output is not given.")
    parser.add_argument("--output", type=Path, default=None,
                         help="Combined output WAV file. Overrides --participant-id/--output-dir.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SELECTED_SOUNDS_DIR,
                         help=f"Folder to save into when using --participant-id (default: {DEFAULT_SELECTED_SOUNDS_DIR}).")
    parser.add_argument("--channel", choices=["left", "right", "mono"], default="right",
                         help="Channel to use if --input is stereo (default: right / body mic).")
    parser.add_argument("--duration", type=float, default=60.0, help="Length of each moment in seconds (default: 60).")
    parser.add_argument("--gap", type=float, default=30.0, help="Silence between moments in seconds (default: 30).")
    parser.add_argument("--eating-end-offset", type=float, default=DEFAULT_EATING_END_OFFSET,
                         help="Seconds before the recording ends where the 'near end of eating' moment starts (default: 180 / 3min).")

    for key in MOMENT_ORDER:
        flag = key.replace("_", "-")
        parser.add_argument(f"--{flag}-range", nargs=2, type=float, metavar=("START", "END"),
                             help=f"Override: search this time range (seconds) for the loudest {MOMENT_LABELS[key]} window.")
        parser.add_argument(f"--{flag}-start", type=float, default=None,
                             help=f"Override: use this exact start second for the {MOMENT_LABELS[key]} moment.")

    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    if args.output is None:
        if not args.participant_id:
            raise SystemExit("Provide --participant-id (to auto-name the file) or --output (exact path).")
        args.output = args.output_dir / f"{args.participant_id}_playback_clip.wav"

    signal, sr = load_channel(args.input, args.channel)

    overrides = {}
    for key in MOMENT_ORDER:
        fixed_start = getattr(args, f"{key}_start")
        search_range = getattr(args, f"{key}_range")
        if fixed_start is not None:
            overrides[key] = {"start": fixed_start}
        elif search_range is not None:
            overrides[key] = {"range": tuple(search_range)}

    print(f"Loaded {args.input.name}: {len(signal) / sr:.1f}s @ {sr} Hz\n")

    combined, moments = build_moments_clip(
        signal, sr,
        duration_s=args.duration,
        gap_s=args.gap,
        eating_end_offset=args.eating_end_offset,
        overrides=overrides,
    )

    for moment in moments:
        print(f"[{moment['label']:>24}] start={moment['start']:7.2f}s  end={moment['end']:7.2f}s  "
              f"rms={moment['rms']:.4f} ({moment['db']:.1f} dBFS)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), combined, sr)

    total_out = len(combined) / sr
    print(f"\nWrote {args.output} ({total_out:.1f}s total: 3 x {args.duration:.0f}s moments + 2 x {args.gap:.0f}s gaps)")


if __name__ == "__main__":
    sys.exit(main())
