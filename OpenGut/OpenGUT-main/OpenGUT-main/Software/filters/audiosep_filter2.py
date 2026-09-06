"""AudioSep (PyTorch) filter plugin v2 — GPU-first + whole-file processing.

This plugin uses the local AudioSep project under demo0/AudioSep.
Improvements over v1:
  - Tries CUDA first, then MPS, then CPU (instead of hardcoded CPU)
  - Feeds whole audio file to AudioSep instead of chunking ourselves
  - Lets AudioSep's use_chunk=True handle internal chunking for memory efficiency
  - Simpler single-pass I/O instead of segment loop
"""

from pathlib import Path
import sys
import tempfile
import importlib
import shutil
import warnings
import gc
from contextlib import contextmanager

import numpy as np
import soundfile as sf

from app_settings import load_settings

_AUDIOSEP_MODEL = None
_AUDIOSEP_MODEL_KEY = None


def _get_audiosep_root() -> Path:
    return Path(__file__).resolve().parent.parent / "AudioSep"


@contextmanager
def _temporary_cwd(path: Path):
    """Temporarily switch current working directory."""
    previous = Path.cwd()
    os_path = str(path)
    import os
    os.chdir(os_path)
    try:
        yield
    finally:
        os.chdir(str(previous))


def _ensure_file_at_path(source_path: str, destination_path: Path) -> None:
    """Ensure destination resolves to source via symlink or copy."""
    src = Path(source_path).expanduser().resolve()
    dst = destination_path.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() or dst.is_symlink():
        try:
            if dst.resolve() == src:
                return
        except Exception:
            pass
        dst.unlink()

    try:
        dst.symlink_to(src)
    except Exception:
        shutil.copy2(src, dst)


def _prepare_audiosep_runtime_assets(config_yaml: str, checkpoint_path: str, music_speech_ckpt: str) -> None:
    """Stage configured files into the locations AudioSep expects at runtime."""
    audiosep_root = _get_audiosep_root()
    _ensure_file_at_path(
        music_speech_ckpt,
        audiosep_root / "checkpoint" / "music_speech_audioset_epoch_15_esc_89.98.pt",
    )
    _ensure_file_at_path(
        checkpoint_path,
        audiosep_root / "checkpoint" / "audiosep_base_4M_steps.ckpt",
    )
    _ensure_file_at_path(
        config_yaml,
        audiosep_root / "config" / "audiosep_base.yaml",
    )


def _select_device():
    """Select best available compute device: CUDA > MPS > CPU."""
    import torch

    if torch.cuda.is_available():
        device = torch.device("cuda")
        device_name = "CUDA"
    elif hasattr(torch, "mps") and torch.mps.is_available():
        device = torch.device("mps")
        device_name = "MPS"
    else:
        device = torch.device("cpu")
        device_name = "CPU"

    return device, device_name


def _build_audiosep_model():
    """Build and cache AudioSep model on selected device."""
    global _AUDIOSEP_MODEL, _AUDIOSEP_MODEL_KEY

    settings = load_settings()
    audiosep_root = _get_audiosep_root()

    config_yaml = settings.get("audiosep_yaml_config") or str(audiosep_root / "config" / "audiosep_base.yaml")
    checkpoint_path = settings.get("audiosep_base_checkpoint") or str(audiosep_root / "checkpoint" / "audiosep_base_4M_steps.ckpt")
    music_speech_ckpt = settings.get("music_speech_checkpoint") or str(audiosep_root / "checkpoint" / "music_speech_audioset_epoch_15_esc_89.98.pt")

    config_yaml = str(Path(config_yaml).expanduser())
    checkpoint_path = str(Path(checkpoint_path).expanduser())
    music_speech_ckpt = str(Path(music_speech_ckpt).expanduser())

    missing = []
    if not Path(config_yaml).exists():
        missing.append(f"audiosep_yaml_config not found: {config_yaml}")
    if not Path(checkpoint_path).exists():
        missing.append(f"audiosep_base_checkpoint not found: {checkpoint_path}")
    if not Path(music_speech_ckpt).exists():
        missing.append(f"music_speech_checkpoint not found: {music_speech_ckpt}")
    if missing:
        raise RuntimeError("; ".join(missing))

    model_key = (config_yaml, checkpoint_path, music_speech_ckpt)
    if _AUDIOSEP_MODEL is not None and _AUDIOSEP_MODEL_KEY == model_key:
        return _AUDIOSEP_MODEL

    try:
        import torch
        import numpy as _np

        # Match compatibility setup used in AudioSep/ryo_demo.py
        torch.serialization.add_safe_globals([
            _np.core.multiarray.scalar,
            _np.dtype,
            _np.dtypes.Float64DType,
        ])

        audiosep_root = _get_audiosep_root()
        if str(audiosep_root) not in sys.path:
            sys.path.insert(0, str(audiosep_root))

        _prepare_audiosep_runtime_assets(config_yaml, checkpoint_path, music_speech_ckpt)

        # Select best available compute device
        device, device_name = _select_device()

        with _temporary_cwd(audiosep_root):
            pipeline_module = importlib.import_module("pipeline")  # pylint: disable=import-error  # type: ignore
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"Found keys that are not in the model state dict but in the checkpoint:.*position_ids.*",
                )
                model = pipeline_module.build_audiosep(
                    config_yaml=str(audiosep_root / "config" / "audiosep_base.yaml"),
                    checkpoint_path=str(audiosep_root / "checkpoint" / "audiosep_base_4M_steps.ckpt"),
                    device=device,
                )

        _AUDIOSEP_MODEL = (model, device, device_name)
        _AUDIOSEP_MODEL_KEY = model_key
        return _AUDIOSEP_MODEL
    except Exception as exc:
        raise RuntimeError(
            "AudioSep dependencies/model are not ready. "
            "Please verify Welcome tab paths for YAML/checkpoints. "
            f"Root cause: {exc}"
        ) from exc


def release_audiosep_resources():
    """Release cached AudioSep model and clear torch allocator caches."""
    global _AUDIOSEP_MODEL, _AUDIOSEP_MODEL_KEY

    if _AUDIOSEP_MODEL is not None:
        try:
            model, _device, _device_name = _AUDIOSEP_MODEL
            del model
        except Exception:
            pass

    _AUDIOSEP_MODEL = None
    _AUDIOSEP_MODEL_KEY = None

    gc.collect()

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
    except Exception:
        pass


class FilterUnit:
    name = "AudioSep Prompt Extractor (GPU-optimized)"
    description = "Extract sound components by text prompt using AudioSep. GPU-first device selection, whole-file processing with internal chunking."

    def get_parameter_schema(self):
        return [
            {
                "key": "prompt",
                "label": "Sound Prompt",
                "type": "text",
                "default": "Gastric sounds produced by the human body during digestion",
            }
        ]

    def apply(self, audio, sr, channel_index, params, source_path, temp_dir, progress_callback=None):
        prompt = str(params.get("prompt", "")).strip()
        if not prompt:
            raise RuntimeError("Prompt cannot be empty for AudioSep filter.")

        model, device, device_name = _build_audiosep_model()

        audiosep_root = _get_audiosep_root()
        if str(audiosep_root) not in sys.path:
            sys.path.insert(0, str(audiosep_root))

        with _temporary_cwd(audiosep_root):
            from pipeline import separate_audio  # pylint: disable=import-error  # type: ignore

        sample_rate = int(sr)
        if sample_rate <= 0 or sample_rate > 768000:
            raise RuntimeError(f"Invalid sample rate: {sr}")

        channel = np.asarray(audio[channel_index], dtype=np.float32)
        channel = np.nan_to_num(channel, nan=0.0, posinf=1.0, neginf=-1.0)

        try:
            with tempfile.TemporaryDirectory(prefix="audiosep_tmp_", dir=temp_dir) as work_dir:
                work_dir_path = Path(work_dir)

                if progress_callback is not None:
                    progress_callback(10, f"Starting AudioSep inference on {device_name}")

                # Write entire channel to a single source file
                src_wav = work_dir_path / "source.wav"
                out_wav = work_dir_path / "separated.wav"
                sf.write(str(src_wav), channel, sample_rate)

                if progress_callback is not None:
                    progress_callback(40, "Running AudioSep engine with internal chunking")

                # Let AudioSep handle chunking internally with use_chunk=True
                # This processes the whole file while managing memory via internal buffering
                with _temporary_cwd(audiosep_root):
                    import torch

                    with torch.inference_mode():
                        separate_audio(
                            model,
                            str(src_wav),
                            prompt,
                            str(out_wav),
                            device,
                            use_chunk=True,
                        )

                if progress_callback is not None:
                    progress_callback(85, "Reading processed audio")

                # Read the entire output
                y, _ = sf.read(str(out_wav), dtype="float32", always_2d=False)
                if np.ndim(y) > 1:
                    y = y[:, 0]

                if progress_callback is not None:
                    progress_callback(100, "AudioSep inference complete")

                return np.asarray(np.clip(y, -1.0, 1.0), dtype=np.float32)
        finally:
            release_audiosep_resources()
