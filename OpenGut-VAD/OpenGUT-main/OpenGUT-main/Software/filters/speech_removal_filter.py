"""Removes human speech from a channel using Silero VAD (voice activity
detection): detected speech segments are muted/attenuated in place,
everything else (gut sounds) is left untouched.

Lighter-weight alternative to the AudioSep prompt-extractor filters: no
multi-GB checkpoint downloads, runs on CPU in well under real time (Silero
VAD's traced model is a couple MB, fetched once via torch.hub and cached).
Since this detects *when* speech happens rather than truly separating
overlapping speech+gut-sound audio at the waveform level, it works best
when the participant isn't talking at the exact same instant a gut sound
occurs -- the common case for these recordings -- rather than for audio
where the two are tightly layered together.
"""
import numpy as np


def _resample_linear(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    duration = len(x) / sr_in
    n_out = max(1, int(round(duration * sr_out)))
    t_in = np.linspace(0.0, duration, num=len(x), endpoint=False)
    t_out = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(t_out, t_in, x).astype(np.float32)


class FilterUnit:
    name = "Speech Removal (Silero VAD)"
    description = (
        "Detects human speech with Silero VAD and mutes those segments, "
        "leaving gut sounds untouched. Lightweight alternative to the "
        "AudioSep prompt extractor -- no large model download, runs on CPU."
    )

    def get_parameter_schema(self):
        return [
            {
                "key": "threshold",
                "label": "VAD Sensitivity",
                "type": "float",
                "default": 0.5,
                "min": 0.1,
                "max": 0.9,
                "step": 0.05,
            },
            {
                "key": "attenuation_db",
                "label": "Speech Attenuation (dB)",
                "type": "float",
                "default": -60.0,
                "min": -80.0,
                "max": 0.0,
                "step": 5.0,
            },
            {
                "key": "padding_ms",
                "label": "Padding Around Speech (ms)",
                "type": "int",
                "default": 150,
                "min": 0,
                "max": 1000,
                "step": 10,
            },
            {
                "key": "fade_ms",
                "label": "Fade In/Out (ms)",
                "type": "int",
                "default": 20,
                "min": 0,
                "max": 200,
                "step": 5,
            },
        ]

    def apply(self, audio, sr, channel_index, params, source_path, temp_dir, progress_callback=None):
        import torch

        threshold = float(params.get("threshold", 0.5))
        attenuation_db = float(params.get("attenuation_db", -60.0))
        padding_ms = int(params.get("padding_ms", 150))
        fade_ms = int(params.get("fade_ms", 20))

        sr = int(sr)
        channel = np.asarray(audio[channel_index], dtype=np.float32)
        channel = np.where(np.isfinite(channel), channel, 0.0).astype(np.float32)

        if progress_callback is not None:
            progress_callback(5, "Loading Silero VAD model")

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad",
            trust_repo=True, onnx=False, verbose=False,
        )
        get_speech_timestamps = utils[0]

        vad_sr = 16000
        vad_audio = _resample_linear(channel, sr, vad_sr)
        vad_tensor = torch.from_numpy(vad_audio)

        if progress_callback is not None:
            progress_callback(30, "Running voice activity detection")

        speech_segments = get_speech_timestamps(
            vad_tensor, model,
            threshold=threshold,
            sampling_rate=vad_sr,
            speech_pad_ms=padding_ms,
            return_seconds=True,
        )

        if progress_callback is not None:
            progress_callback(70, f"Muting {len(speech_segments)} detected speech segment(s)")

        gain_floor = 10.0 ** (attenuation_db / 20.0)
        fade_samples = max(1, int(sr * fade_ms / 1000.0))
        output = channel.copy()

        for seg in speech_segments:
            start = max(0, int(seg["start"] * sr))
            end = min(len(output), int(seg["end"] * sr))
            if end <= start:
                continue

            gain = np.full(end - start, gain_floor, dtype=np.float32)
            ramp_len = min(fade_samples, (end - start) // 2)
            if ramp_len > 0:
                gain[:ramp_len] = np.linspace(1.0, gain_floor, ramp_len, dtype=np.float32)
                gain[-ramp_len:] = np.linspace(gain_floor, 1.0, ramp_len, dtype=np.float32)

            output[start:end] *= gain

        if progress_callback is not None:
            progress_callback(100, "Speech removal complete")

        return np.asarray(np.clip(output, -1.0, 1.0), dtype=np.float32)
