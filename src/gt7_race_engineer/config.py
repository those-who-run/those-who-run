"""Settings from environment variables and rule configuration from YAML."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES: dict[str, Any] = {
    "voice": {"length_scale": 0.9, "noise_scale": 0.5, "noise_w_scale": 0.5},
    "queue": {"max_age_seconds": 8.0},
    "rules": {
        "lap_time": {
            "enabled": True,
            "priority": 20,
            "template": "Lap {lap}. {time}. {delta}",
            "delta_faster": "{delta} under best",
            "delta_slower": "{delta} over best",
            "delta_equal": "equal to best",
            "delta_first": "",
        },
        "fuel": {
            "enabled": True,
            "priority": 15,
            "critical_priority": 5,
            "thresholds_laps": [10, 5, 3, 2, 1],
            "rolling_laps": 3,
            "refuel_epsilon": 0.5,
            "template": "Fuel. {laps} remaining.",
            "template_critical": "Fuel critical. Less than one lap.",
        },
        "final_lap": {"enabled": True, "priority": 10, "template": "Final lap."},
    },
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    ps5_ip: str | None
    discord_token: str | None
    discord_channel_id: int | None
    rules_file: Path | None
    data_dir: Path
    voice_model: Path
    metrics_port: int
    idle_disconnect_secs: float
    telemetry_timeout_secs: float
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        rules_file = e.get("GT7_RULES_FILE")
        return cls(
            ps5_ip=e.get("GT7_PS5_IP") or None,
            discord_token=e.get("DISCORD_BOT_TOKEN") or None,
            discord_channel_id=_int_or_none(e.get("DISCORD_VOICE_CHANNEL_ID")),
            rules_file=Path(rules_file) if rules_file else None,
            data_dir=Path(e.get("GT7_DATA_DIR", "./data")),
            voice_model=Path(e.get("GT7_VOICE_MODEL", "voices/en_GB-alba-medium.onnx")),
            metrics_port=int(e.get("GT7_METRICS_PORT", "9850")),
            idle_disconnect_secs=float(e.get("GT7_IDLE_DISCONNECT_SECS", "600")),
            telemetry_timeout_secs=float(e.get("GT7_TELEMETRY_TIMEOUT_SECS", "3")),
            log_level=e.get("LOG_LEVEL", "INFO").upper(),
        )

    def require_live(self) -> None:
        missing = [
            name
            for name, value in (
                ("GT7_PS5_IP", self.ps5_ip),
                ("DISCORD_BOT_TOKEN", self.discord_token),
                ("DISCORD_VOICE_CHANNEL_ID", self.discord_channel_id),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"missing required environment variables: {', '.join(missing)}")


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"DISCORD_VOICE_CHANNEL_ID must be an integer, got {value!r}") from exc


def deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_rules_config(path: Path | None) -> dict[str, Any]:
    """Defaults merged with the YAML file, if any. Unknown keys are kept for rules to read."""
    if path is None:
        return copy.deepcopy(DEFAULT_RULES)
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"rules file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"rules file is not valid YAML: {path}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"rules file must be a mapping at the top level: {path}")
    return deep_merge(DEFAULT_RULES, loaded)
