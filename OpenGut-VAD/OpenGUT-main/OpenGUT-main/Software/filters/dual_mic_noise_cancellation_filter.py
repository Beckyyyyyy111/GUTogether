"""Adaptive noise cancellation using OpenGUT's second microphone as a real
noise reference (Widrow et al., 1975, "Adaptive Noise Cancelling: Principles
and Applications", Proceedings of the IEEE -- the foundational paper for
this class of technique).

OpenGUT's firmware (Firmware/*/src/PDM.c, PDM_Record_Stereo_Wav_Until) maps
one physical microphone to the left channel and the other to the right
channel of a single stereo WAV file (dmic_build_channel_map(0, 0,
PDM_CHAN_LEFT) | dmic_build_channel_map(1, 0, PDM_CHAN_RIGHT)) -- so every
recording already contains a genuine independent ambient reference, not
just the target channel.

Unlike spectral_noise_reduction_filter.py (which statistically *guesses* a
noise floor from a single channel), this estimates, per time-frequency bin,
the actual linear relationship between the reference channel and the target
channel (a Wiener-style cross-spectral gain) and subtracts only the part of
the target that's genuinely explained by the reference. Content on the
target channel that the reference doesn't predict at all -- e.g. true
internal-body gut sounds that the outward-facing mic barely picks up --
passes through close to untouched, because the estimated gain for that
content is naturally close to zero. This is the same optimization criterion
Widrow's adaptive LMS cancellation uses; this implementation solves it in
blockwise closed form via STFT cross-spectra instead of a per-sample
adaptive filter, which is far faster on long recordings and doesn't have
LMS's step-size/stability tuning problems.

Still not a perfect separation: the cross-spectral gain is a statistical
estimate over a time window, so genuine gut-sound energy that happens to be
correlated with what's on the reference channel at a given frequency can
still be attenuated somewhat, and picking too short a context window can
make the estimate noisy. Prefer speech_removal_filter.py for anything where
exact signal fidelity matters (e.g. playback stimuli).
"""
import numpy as np


class FilterUnit:
    name = "Dual-Mic Noise Cancellation"
    description = (
        "Uses OpenGUT's other microphone channel as a real ambient-noise "
        "reference (adaptive noise cancelling, Widrow et al. 1975) instead of "
        "guessing a noise floor from one channel. Only removes content on the "
        "target channel that's actually explained by the reference channel, "
        "so true body-only gut sounds mostly pass through untouched. Requires "
        "stereo input (OpenGUT's two mics -- see PDM.c)."
    )

    def get_parameter_schema(self):
        return [
            {
                "key": "context_window_s",
                "label": "Context Window (s)",
                "type": "float",
                "default": 5.0,
                "min": 0.5,
                "max": 30.0,
                "step": 0.5,
            },
            {
                "key": "reduction_strength",
                "label": "Reduction Strength",
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 2.0,
                "step": 0.1,
            },
            {
                "key": "spectral_floor_db",
                "label": "Spectral Floor (dB)",
                "type": "float",
                "default": -20.0,
                "min": -40.0,
                "max": 0.0,
                "step": 1.0,
            },
        ]

    def apply(self, audio, sr, channel_index, params, source_path, temp_dir, progress_callback=None):
        try:
            import librosa
        except Exception as exc:
            raise RuntimeError("librosa is required for this filter.") from exc

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 2 or audio.shape[0] < 2:
            raise RuntimeError(
                "Dual-Mic Noise Cancellation needs stereo input (target mic + "
                "ambient reference mic) -- this file only has one channel."
            )

        channel_index = int(channel_index)
        reference_index = 1 - channel_index if channel_index in (0, 1) else (0 if channel_index != 0 else 1)

        context_window_s = float(params.get("context_window_s", 5.0))
        reduction_strength = float(params.get("reduction_strength", 1.0))
        spectral_floor_db = float(params.get("spectral_floor_db", -20.0))

        sr = int(sr)
        target = np.where(np.isfinite(audio[channel_index]), audio[channel_index], 0.0).astype(np.float32)
        reference = np.where(np.isfinite(audio[reference_index]), audio[reference_index], 0.0).astype(np.float32)

        if progress_callback is not None:
            progress_callback(10, "Computing spectrograms for both microphones")

        n_fft = 1024
        hop = n_fft // 4
        D = librosa.stft(target, n_fft=n_fft, hop_length=hop)
        X = librosa.stft(reference, n_fft=n_fft, hop_length=hop)

        if progress_callback is not None:
            progress_callback(35, "Estimating reference-to-target relationship")

        # Instantaneous cross/auto power per time-frequency bin, then smoothed
        # over a sliding time window -- this is the "context window": how much
        # recent history the gain estimate is allowed to use. A closed-form
        # blockwise stand-in for Widrow's per-sample LMS adaptation.
        xx_inst = (X.real ** 2 + X.imag ** 2).astype(np.float32)
        xd_inst = (np.conj(X) * D).astype(np.complex64)

        frames_per_window = max(1, int(round(context_window_s * sr / hop)))
        if frames_per_window > 1:
            kernel = np.ones(frames_per_window, dtype=np.float32) / frames_per_window
            xx_smooth = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), axis=1, arr=xx_inst)
            xd_smooth = np.apply_along_axis(
                lambda row: np.convolve(row, kernel, mode="same"), axis=1, arr=xd_inst.real
            ) + 1j * np.apply_along_axis(
                lambda row: np.convolve(row, kernel, mode="same"), axis=1, arr=xd_inst.imag
            )
        else:
            xx_smooth = xx_inst
            xd_smooth = xd_inst

        if progress_callback is not None:
            progress_callback(60, "Cancelling correlated noise")

        reg = 1e-6 + 1e-3 * np.mean(xx_smooth)
        H = xd_smooth / (xx_smooth + reg)
        predicted_noise = H * X
        D_clean_raw = D - reduction_strength * predicted_noise

        # Safety floor: where cancellation nearly zeroes out a bin, what's
        # left in D_clean_raw is dominated by numerical noise, not signal --
        # scaling *that* back up would amplify noise, not recover anything
        # useful (this was a real bug: it made bins with the *best*
        # cancellation the noisiest). Fall back to a quiet, fixed-ratio copy
        # of the original bin instead, which at least has a real, physically
        # meaningful magnitude and phase. Everywhere else, the genuine
        # complex (magnitude + phase) cancellation result is kept as-is.
        floor = 10.0 ** (spectral_floor_db / 20.0)
        raw_mag = np.abs(D_clean_raw)
        orig_mag = np.abs(D)
        min_mag = floor * orig_mag
        below_floor = raw_mag < min_mag
        D_clean = np.where(below_floor, D * floor, D_clean_raw)

        if progress_callback is not None:
            progress_callback(85, "Reconstructing audio")

        output = librosa.istft(D_clean, hop_length=hop, length=len(target))

        if progress_callback is not None:
            progress_callback(100, "Noise cancellation complete")

        return np.asarray(np.clip(output, -1.0, 1.0), dtype=np.float32)
