"""Scipy-based high-pass Butterworth filter plugin."""

import numpy as np


class FilterUnit:
    name = "Scipy Butterworth High-Pass"
    description = "High-pass Butterworth filtering using scipy.signal."

    def get_parameter_schema(self):
        return [
            {
                "key": "order",
                "label": "Order",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 20,
                "step": 1,
            },
            {
                "key": "critical_frequency",
                "label": "Critical Frequency (Hz)",
                "type": "float",
                "default": 200.0,
                "min": 10.0,
                "max": 20000.0,
                "step": 10.0,
            },
            {
                "key": "analog",
                "label": "Filter Type",
                "type": "choice",
                "default": "digital",
                "choices": ["digital", "analog"],
            },
        ]

    def apply(self, audio, sr, channel_index, params, source_path, temp_dir):
        try:
            from scipy import signal
        except Exception as exc:
            raise RuntimeError("scipy is required for this filter.") from exc

        order = int(params.get("order", 4))
        critical_frequency = float(params.get("critical_frequency", 200.0))
        analog_mode = str(params.get("analog", "digital")).lower() == "analog"

        x = np.asarray(audio[channel_index], dtype=np.float64)
        x = np.where(np.isfinite(x), x, 0.0)

        if analog_mode:
            # Design in zpk form for numerical stability, then bilinear-transform to digital SOS.
            z_a, p_a, k_a = signal.butter(
                order, 2.0 * np.pi * critical_frequency,
                btype="highpass", analog=True, output="zpk",
            )
            z_d, p_d, k_d = signal.bilinear_zpk(z_a, p_a, k_a, fs=sr)
            sos = signal.zpk2sos(z_d, p_d, k_d)
        else:
            if sr <= 0:
                raise ValueError("Sample rate must be positive.")
            nyq = sr / 2.0
            normalized = min(max(critical_frequency / nyq, 1e-5), 0.999)
            sos = signal.butter(order, normalized, btype="highpass", output="sos")

        # Use single-pass SOS filtering for robustness on some macOS/scipy builds
        # where filtfilt/sosfiltfilt may crash at native level.
        y = signal.sosfilt(sos, x)

        # Sanitize any NaN/inf that may arise from extreme parameters.
        y = np.where(np.isfinite(y), y, 0.0)
        return np.asarray(np.clip(y, -1.0, 1.0), dtype=np.float32)
