"""Reusable plotting utilities for waveform and spectrogram rendering."""

import librosa
import numpy as np
import pyqtgraph as pg
from const import (
    DEFAULT_SPECTROGRAM_FREQ_HZ,
    WAVEFORM_MAX_SAMPLES_DEFAULT,
    WAVEFORM_Y_MAX,
    WAVEFORM_Y_MIN,
)


def downsample_waveform(channel_data, sr, max_samples=WAVEFORM_MAX_SAMPLES_DEFAULT):
    """Downsample waveform for plotting while preserving time scale."""
    total_samples = len(channel_data)
    if total_samples > max_samples:
        downsample_factor = total_samples // max_samples
        y_display = channel_data[::downsample_factor]
        time_scale = downsample_factor / sr
    else:
        y_display = channel_data
        time_scale = 1 / sr

    time = np.arange(len(y_display)) * time_scale
    return time, y_display


def draw_waveform(plot_widget, channel_data, sr, pen, duration, max_samples=WAVEFORM_MAX_SAMPLES_DEFAULT):
    """Render waveform into a pyqtgraph PlotWidget."""
    time, y_display = downsample_waveform(channel_data, sr, max_samples=max_samples)
    plot_widget.plot(time, y_display, pen=pen)
    plot_widget.setLabel("left", "Amplitude")
    plot_widget.setXRange(0, duration, padding=0)
    plot_widget.setYRange(WAVEFORM_Y_MIN, WAVEFORM_Y_MAX, padding=0)


def compute_stft_spectrogram_db(channel_data, sr, n_fft=2048, hop_length=512):
    """Compute linear STFT spectrogram in dB for plotting.

    STFT bins are uniformly spaced in Hz (bin i = i * sr / n_fft Hz), so the
    resulting image maps correctly to a linear frequency axis without distortion.
    """
    stft_mag = np.abs(librosa.stft(channel_data.astype(np.float32), n_fft=n_fft, hop_length=hop_length))
    spec_db = librosa.amplitude_to_db(stft_mag, ref=np.max)
    return spec_db


def draw_spectrogram(plot_widget, channel_data, sr, duration, y_max_hz=DEFAULT_SPECTROGRAM_FREQ_HZ):
    """Render spectrogram into a pyqtgraph PlotWidget and return the ImageItem."""
    n_fft = 2048
    spec_db = compute_stft_spectrogram_db(channel_data, sr, n_fft=n_fft)

    nyquist_hz = max(1.0, float(sr) / 2.0)
    target_hz = min(float(y_max_hz), nyquist_hz)

    # STFT bins are linearly spaced: bin i is at frequency i * nyquist_hz / (n_freq_bins - 1).
    # Crop to the bins that fall within [0, target_hz] so the image exactly represents
    # the requested frequency band.
    n_freq_bins = spec_db.shape[0]  # = n_fft // 2 + 1
    hz_per_bin = nyquist_hz / (n_freq_bins - 1)
    max_bin = min(n_freq_bins, int(np.round(target_hz / hz_per_bin)) + 1)

    cropped_spec = spec_db[:max_bin, :]
    effective_max_hz = (max_bin - 1) * hz_per_bin

    image = pg.ImageItem(cropped_spec.T)
    image.setRect(0, 0, duration, effective_max_hz)
    plot_widget.addItem(image)
    plot_widget.setLabel("left", "Frequency (Hz)")
    plot_widget.setXRange(0, duration, padding=0)
    plot_widget.setYRange(0.0, target_hz, padding=0)
    return image
