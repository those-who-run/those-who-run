"""Helpers more than one command uses."""

from __future__ import annotations

from pathlib import Path

from those_who_run.config import ConfigError, Settings


def require_voice_model(settings: Settings) -> Path:
    path = settings.voice_model
    if not path.exists():
        raise ConfigError(f"voice model not found: {path} (set GT7_VOICE_MODEL, or `make voice`)")
    return path
