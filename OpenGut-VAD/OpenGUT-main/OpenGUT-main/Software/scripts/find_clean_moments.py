#!/usr/bin/env python3
"""
Scan a long recording (e.g. a ~20min shared-eating session) and list the
top candidate windows that are both acoustically active (loud -- a proxy
for gut-sound activity) and free of detected speech, using Silero VAD to
find the speech segments to avoid. See audio_moments.find_clean_candidates
for the ranking logic.

This does NOT replace listening to the candidates -- energy is just a proxy
for "something is happening here", not a gut-sound classifier, so a loud
non-speech window could still be silverware clatter, a chair scrape, etc.
Use --export to also save each candidate as its own short WAV file so you
can quickly listen through them.

Example:

    python find_clean_moments.py \\
        --input "Participant_Gut_Sounds/Origianl_Sounds/REC1507.WAV" \\
        --channel right --duration 60 --top-n 10 --export
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from audio_moments import find_clean_candidates  # noqa: E402
from filters.speech_removal_filter import _resample_linear  # noqa: E402


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
    raise ValueError(f"'{path.name}' has {n_channels} channels; pass --channel left/right/mono to pick one.")


def detect_speech_segments(signal: np.ndarray, sr: int, threshold: float, speech_pad_ms: int) -> list:
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad", model="silero_vad",
        trust_repo=True, onnx=False, verbose=False,
    )
    get_speech_timestamps = utils[0]
    vad_audio = _resample_linear(signal, sr, 16000)
    segs = get_speech_timestamps(
        torch.from_numpy(vad_audio), model,
        sampling_rate=16000, threshold=threshold, speech_pad_ms=speech_pad_ms,
        return_seconds=True,
    )
    return [(s["start"], s["end"]) for s in segs]


def format_hms(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="Source WAV file.")
    parser.add_argument("--channel", choices=["left", "right", "mono"], default="right",
                         help="Channel to analyze if stereo (default: right / body mic).")
    parser.add_argument("--duration", type=float, default=60.0, help="Candidate window length in seconds (default: 60).")
    parser.add_argument("--top-n", type=int, default=10, help="How many candidates to list (default: 10).")
    parser.add_argument("--vad-threshold", type=float, default=0.3,
                         help="Silero VAD sensitivity; lower catches quieter/less-confident speech (default: 0.3).")
    parser.add_argument("--vad-pad-ms", type=int, default=150,
                         help="Padding (ms) added around each detected speech segment before excluding it (default: 150).")
    parser.add_argument("--export", action="store_true",
                         help="Also save each candidate as its own WAV file next to --input, for quick listening.")
    parser.add_argument("--export-dir", type=Path, default=None,
                         help="Folder to save exported candidate clips into (default: alongside --input).")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    signal, sr = load_channel(args.input, args.channel)
    total_s = len(signal) / sr
    print(f"Loaded {args.input.name}: {total_s:.1f}s ({format_hms(total_s)}) @ {sr} Hz, channel={args.channel}\n")

    print("Running Silero VAD to find speech to avoid...")
    speech_segments = detect_speech_segments(signal, sr, args.vad_threshold, args.vad_pad_ms)
    total_speech = sum(e - s for s, e in speech_segments)
    print(f"  {len(speech_segments)} speech segment(s), {total_speech:.1f}s total "
          f"({100 * total_speech / total_s:.1f}% of recording)\n")

    candidates = find_clean_candidates(
        signal, sr, speech_segments, duration_s=args.duration, top_n=args.top_n,
    )

    if not candidates:
        print("No speech-free windows of this duration were found. Try a shorter --duration "
              "or a lower --vad-threshold isn't the fix here -- the recording may just not have "
              "enough continuous quiet time; consider a shorter clip duration instead.")
        return

    print(f"Top {len(candidates)} candidate window(s) ({args.duration:.0f}s each, ranked loudest first):\n")
    for i, c in enumerate(candidates, start=1):
        print(f"  {i:2d}. {format_hms(c['start'])} - {format_hms(c['end'])}  "
              f"(rms={c['rms']:.4f}, {c['db']:.1f} dBFS)")

    if args.export:
        export_dir = args.export_dir or args.input.parent
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = args.input.stem
        print(f"\nExporting candidates to {export_dir}/")
        for i, c in enumerate(candidates, start=1):
            start_sample = int(round(c["start"] * sr))
            end_sample = int(round(c["end"] * sr))
            clip = signal[start_sample:end_sample]
            out_path = export_dir / f"{stem}_candidate{i:02d}_{int(c['start'])}s.wav"
            sf.write(str(out_path), clip, sr)
            print(f"  wrote {out_path.name}")


if __name__ == "__main__":
    sys.exit(main())
