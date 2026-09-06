"""Clean tail-window filter plugin.

Crops a fixed-length "clean" window from the channel selected in the
Filtering tab's Channel dropdown, near the end of a recording (the post-meal
stillness period), high-pass filters it, and writes the result directly into
Participant_Gut_Sounds/Selected_Sounds/ as a standalone WAV.

The value returned from apply() only feeds the host app's own same-length
preview/export (silence outside the selected window, per the app's filter
contract); the real deliverable is the short WAV written as a side effect
below.
"""

from pathlib import Path

import numpy as np
import soundfile as sf


class FilterUnit:
    name = "Clean Tail Window (High-Pass) -> Selected_Sounds"
    description = (
        "Crops [duration - start_offset_min, duration - end_offset_min] from the "
        "channel picked in the Channel dropdown above, high-pass filters it, and "
        "exports the short clip directly to Participant_Gut_Sounds/Selected_Sounds."
    )

    def get_parameter_schema(self):
        return [
            {
                "key": "start_offset_min",
                "label": "Window Start (minutes before end)",
                "type": "float",
                "default": 4.0,
                "min": 0.1,
                "max": 60.0,
                "step": 0.5,
            },
            {
                "key": "end_offset_min",
                "label": "Window End (minutes before end)",
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 60.0,
                "step": 0.5,
            },
            {
                "key": "hp_order",
                "label": "High-Pass Order",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 20,
                "step": 1,
            },
            {
                "key": "hp_critical_frequency",
                "label": "High-Pass Critical Frequency (Hz)",
                "type": "float",
                "default": 200.0,
                "min": 10.0,
                "max": 20000.0,
                "step": 10.0,
            },
            {
                "key": "group",
                "label": "Group (e.g. A, B, ... L)",
                "type": "text",
                "default": "A",
            },
            {
                "key": "session_number",
                "label": "Number",
                "type": "int",
                "default": 1,
                "min": 1,
                "max": 999,
                "step": 1,
            },
        ]

    def _sanitize_group(self, value):
        text = "" if value is None else str(value)
        allowed = [ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in text]
        return "".join(allowed).strip("_")

    def _select_channel(self, audio, channel_index):
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim == 1:
            return arr, "mono"
        if arr.shape[0] <= 1:
            return arr[0], "mono"
        # index 0 = left, index 1 = right, matches this app's L/R convention
        safe_index = max(0, min(int(channel_index), arr.shape[0] - 1))
        side = "left" if safe_index == 0 else "right"
        return arr[safe_index], side

    def _highpass(self, x, sr, order, critical_frequency):
        from scipy import signal

        x = np.where(np.isfinite(x), x, 0.0).astype(np.float64)
        if sr <= 0:
            raise ValueError("Sample rate must be positive.")
        nyq = sr / 2.0
        normalized = min(max(critical_frequency / nyq, 1e-5), 0.999)
        sos = signal.butter(order, normalized, btype="highpass", output="sos")
        y = signal.sosfilt(sos, x)
        y = np.where(np.isfinite(y), y, 0.0)
        return np.clip(y, -1.0, 1.0).astype(np.float32)

    def apply(self, audio, sr, channel_index, params, source_path, temp_dir):
        sr = int(sr)
        channel, side = self._select_channel(audio, channel_index)
        total_samples = channel.shape[-1]
        duration_s = total_samples / sr

        start_offset_min = float(params.get("start_offset_min", 4.0))
        end_offset_min = float(params.get("end_offset_min", 1.0))
        if start_offset_min <= end_offset_min:
            raise ValueError(
                f"start_offset_min ({start_offset_min}) must be greater than "
                f"end_offset_min ({end_offset_min})."
            )

        window_start_s = duration_s - start_offset_min * 60.0
        window_end_s = duration_s - end_offset_min * 60.0
        if window_start_s < 0:
            raise ValueError(
                f"Recording is only {duration_s:.1f}s long, shorter than the "
                f"requested start offset of {start_offset_min * 60:.0f}s."
            )

        start_sample = max(0, int(round(window_start_s * sr)))
        end_sample = min(total_samples, int(round(window_end_s * sr)))
        if end_sample <= start_sample:
            raise ValueError("Computed clean window is empty; check offset parameters.")

        order = int(params.get("hp_order", 4))
        critical_frequency = float(params.get("hp_critical_frequency", 200.0))

        cropped = channel[start_sample:end_sample]
        filtered = self._highpass(cropped, sr, order, critical_frequency)

        if source_path:
            selected_dir = Path(source_path).resolve().parent.parent / "Selected_Sounds"
            selected_dir.mkdir(parents=True, exist_ok=True)

            group = self._sanitize_group(params.get("group", "A")) or "A"
            session_number = int(params.get("session_number", 1))
            stem = f"Group{group}_{session_number:03d}"

            out_path = selected_dir / f"{stem}.wav"
            dedup_counter = 1
            while out_path.exists():
                out_path = selected_dir / f"{stem}_{dedup_counter}.wav"
                dedup_counter += 1

            sf.write(str(out_path), filtered, sr)

            log_path = out_path.with_suffix(".txt")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(
                    "clean_tail_r_highpass_filter,"
                    f"channel={side},"
                    f"start_offset_min={start_offset_min},end_offset_min={end_offset_min},"
                    f"hp_order={order},hp_critical_frequency={critical_frequency},"
                    f"window=[{window_start_s:.2f}s,{window_end_s:.2f}s],"
                    f"source={Path(source_path).name},output={out_path.name}\n"
                )

        preview = np.zeros(total_samples, dtype=np.float32)
        preview[start_sample:end_sample] = filtered
        return preview
