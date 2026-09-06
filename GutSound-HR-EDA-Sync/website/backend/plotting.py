"""Builds the single time-aligned summary PNG for a session: gut-sound
waveform, spectrogram, HR, and EDA stacked on a shared x-axis (seconds since
playback started, i.e. t=0 is the same instant for all four).

The spectrogram panel mirrors OpenGut's own "Processed Output" view
(Software/ui/components/plot_utils.py: STFT magnitude -> dB, linear
frequency axis) so a session recorded here looks visually consistent with
OpenGut's own viewer.
"""
import wave
from pathlib import Path

import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MAX_WAVEFORM_POINTS = 20_000
SPECTROGRAM_N_FFT = 2048
SPECTROGRAM_HOP_LENGTH = 512
SPECTROGRAM_MAX_FREQ_HZ = 11_000.0  # matches OpenGut's DEFAULT_SPECTROGRAM_FREQ_HZ


def read_wav_waveform(path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        n_frames = wf.getnframes()
        rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        n_channels = wf.getnchannels()
        raw = wf.readframes(n_frames)

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sampwidth)
    if dtype is None:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    data = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    peak = float(np.iinfo(dtype).max)
    data /= peak

    t = np.arange(len(data), dtype=np.float64) / rate
    return t, data, rate


def get_wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _downsample(t: np.ndarray, v: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if len(t) <= max_points:
        return t, v
    step = len(t) // max_points
    return t[::step], v[::step]


def _compute_spectrogram_db(audio: np.ndarray, rate: int) -> np.ndarray:
    stft_mag = np.abs(librosa.stft(audio.astype(np.float32), n_fft=SPECTROGRAM_N_FFT, hop_length=SPECTROGRAM_HOP_LENGTH))
    return librosa.amplitude_to_db(stft_mag, ref=np.max)


def make_summary_plot(
    out_path: Path,
    wav_path: Path,
    hr_samples: list[tuple[float, float | None]],
    eda_samples: list[tuple[float, float | None]],
    duration_s: float,
    title: str,
) -> None:
    t_audio, audio_vals, rate = read_wav_waveform(wav_path)
    t_wave, v_wave = _downsample(t_audio, audio_vals, MAX_WAVEFORM_POINTS)

    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

    axes[0].plot(t_wave, v_wave, linewidth=0.4, color="#1f77b4")
    axes[0].set_ylabel("Gut sound\n(amplitude)")
    axes[0].set_title(title)

    spec_db = _compute_spectrogram_db(audio_vals, rate)
    nyquist_hz = rate / 2.0
    target_hz = min(SPECTROGRAM_MAX_FREQ_HZ, nyquist_hz)
    n_freq_bins = spec_db.shape[0]  # = n_fft // 2 + 1
    hz_per_bin = nyquist_hz / (n_freq_bins - 1)
    max_bin = min(n_freq_bins, int(round(target_hz / hz_per_bin)) + 1)
    cropped = spec_db[:max_bin, :]
    effective_max_hz = (max_bin - 1) * hz_per_bin

    axes[1].imshow(
        cropped, origin="lower", aspect="auto", cmap="viridis",
        extent=(0, duration_s, 0, effective_max_hz),
    )
    axes[1].set_ylabel("Frequency (Hz)")
    axes[1].set_ylim(0, target_hz)

    hr_pts = [(t, v) for t, v in hr_samples if v is not None]
    if hr_pts:
        ht, hv = zip(*hr_pts)
        axes[2].plot(ht, hv, marker="o", markersize=2, linewidth=1, color="#d62728")
    else:
        axes[2].text(0.5, 0.5, "no HR data", transform=axes[2].transAxes, ha="center", color="gray")
    axes[2].set_ylabel("HR (bpm)")

    eda_pts = [(t, v) for t, v in eda_samples if v is not None]
    if eda_pts:
        et, ev = zip(*eda_pts)
        axes[3].plot(et, ev, linewidth=1, color="#2ca02c")
    else:
        axes[3].text(0.5, 0.5, "no EDA data", transform=axes[3].transAxes, ha="center", color="gray")
    axes[3].set_ylabel("EDA (µS)")
    axes[3].set_xlabel("Time since playback start (s)")
    axes[3].set_xlim(0, max(duration_s, 0.1))

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
