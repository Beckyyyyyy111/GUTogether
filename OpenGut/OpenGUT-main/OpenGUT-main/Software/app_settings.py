"""Application settings storage for user-configurable paths."""

from __future__ import annotations

import json
from pathlib import Path

from const import (
    AUDIOSEP_CHUNK_SECONDS_DEFAULT,
    AUDIOSEP_DIR_NAME,
    CONSOLE_LINE_LIMIT_DEFAULT,
    SETTINGS_FILENAME,
    SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT,
    SETTING_KEY_AUDIOSEP_CHUNK_SECONDS,
    SETTING_KEY_CONSOLE_LINE_LIMIT,
    SETTING_KEY_AUDIOSEP_YAML_CONFIG,
    SETTING_KEY_MUSIC_SPEECH_CHECKPOINT,
    SETTING_KEY_WORKING_DIRECTORY,
    WORKING_DIR_NAME,
)


SETTINGS_FILE = Path(__file__).resolve().parent / SETTINGS_FILENAME


def default_settings() -> dict:
    audiosep_root = Path(__file__).resolve().parent / AUDIOSEP_DIR_NAME
    working_root = Path(__file__).resolve().parent / WORKING_DIR_NAME
    return {
        SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT: str(audiosep_root / "checkpoint" / "audiosep_base_4M_steps.ckpt"),
        SETTING_KEY_AUDIOSEP_YAML_CONFIG: str(audiosep_root / "config" / "audiosep_base.yaml"),
        SETTING_KEY_MUSIC_SPEECH_CHECKPOINT: str(audiosep_root / "checkpoint" / "music_speech_audioset_epoch_15_esc_89.98.pt"),
        SETTING_KEY_CONSOLE_LINE_LIMIT: CONSOLE_LINE_LIMIT_DEFAULT,
        SETTING_KEY_AUDIOSEP_CHUNK_SECONDS: AUDIOSEP_CHUNK_SECONDS_DEFAULT,
        SETTING_KEY_WORKING_DIRECTORY: str(working_root),
    }


def load_settings() -> dict:
    settings = default_settings()
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                settings.update(loaded)
        except Exception:
            # Fall back to defaults when file is broken.
            pass
    
    # Ensure working directory exists
    working_dir = settings.get(SETTING_KEY_WORKING_DIRECTORY)
    if working_dir:
        working_path = Path(working_dir)
        working_path.mkdir(parents=True, exist_ok=True)
    
    return settings


def save_settings(settings: dict) -> None:
    payload = default_settings()
    if isinstance(settings, dict):
        payload.update(settings)
    
    # Ensure working directory exists
    working_dir = payload.get(SETTING_KEY_WORKING_DIRECTORY)
    if working_dir:
        working_path = Path(working_dir)
        working_path.mkdir(parents=True, exist_ok=True)

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
