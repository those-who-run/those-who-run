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
    # Layer the bundled script (data/script.yaml) of phrase variants over the
    # single templates below. The rules file still wins key by key.
    "script": True,
    "voice": {
        "length_scale": 0.9,
        "noise_scale": 0.5,
        "noise_w_scale": 0.5,
        "sentence_pause_secs": 0.35,
    },
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
            "equal_ms": 50,
            "small_delta_ms": 300,
            "large_delta_ms": 2000,
            "small_gap_ms": 200,
            "template_new_best": "Lap {lap}. {time}. New best by {gap}.",
            "new_best_priority": 11,
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
            "pit_window": True,
            "pit_laps": 2.0,
            "pit_priority": 5,
            "template_pit": "Pit this lap.",
        },
        "final_lap": {"enabled": True, "priority": 10, "template": "Final lap."},
        "position": {
            "enabled": True,
            "priority": 12,
            "settle_secs": 3.0,
            "min_interval_secs": 10.0,
            "start_grace_secs": 15.0,
            "template_gained": "Up to {position}.",
            "template_lost": "Down to {position}.",
        },
        "start_brief": {
            "enabled": True,
            "priority": 8,
            "settle_secs": 2.0,
            "announce_track": True,
            "late_track_first_lap_only": True,
            "min_confidence": "probable",
            "template_track": "{track}.",
            "template_laps": "{laps}.",
            "template_laps_to_go": "{laps} to go.",
            "template_timed": "Timed race.",
            "template_position": "P {p} of {total}.",
        },
        "race_summary": {
            "enabled": True,
            "priority": 25,
            "max_age_seconds": 30.0,
            "min_fuel": 1.0,
            "template": "Chequered flag. {position} {best} {fuel}",
            "template_position": "Finished {position}.",
            "template_best": "Best lap {time}.",
            "template_fuel": "Fuel used {fuel}.",
            "quit_kinds": ["solo_timed", "solo_laps"],
            "quit_min_laps": 1,
            "template_quit": "Session done. {laps}. {best}",
        },
        "temps": {
            "enabled": True,
            "priority": 14,
            "sustain_secs": 5.0,
            "cooldown_secs": 60.0,
            "hysteresis_c": 10.0,
            "tyre_hot_c": 120.0,
            "tyre_cold_c": 50.0,
            "cold_settle_secs": 2.0,
            "water_hot_c": 110.0,
            "oil_hot_c": 130.0,
            "template_tyre_hot": "{corners} hot.",
            "template_tyres_cold": "Tyres cold.",
            "template_water": "Water temperature high.",
            "template_oil": "Oil temperature high.",
        },
        # Not a frame rule: driven by the live watchdog, so replay never speaks it.
        "telemetry": {
            "enabled": True,
            "priority": 5,
            "phases": ["in_race", "paused"],
            "template_lost": "Lost telemetry.",
            "template_back": "Telemetry back.",
        },
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
    record_dir: Path | None = None
    record_keep: int = 20
    results_channel_id: int | None = None  # a text channel for results cards; None is off

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        rules_file = e.get("GT7_RULES_FILE")
        return cls(
            ps5_ip=e.get("GT7_PS5_IP") or None,
            discord_token=e.get("DISCORD_BOT_TOKEN") or None,
            discord_channel_id=_int_or_none(e, "DISCORD_VOICE_CHANNEL_ID"),
            rules_file=Path(rules_file) if rules_file else None,
            data_dir=Path(e.get("GT7_DATA_DIR", "./data")),
            voice_model=Path(e.get("GT7_VOICE_MODEL", "voices/en_GB-alba-medium.onnx")),
            metrics_port=int(e.get("GT7_METRICS_PORT", "9850")),
            idle_disconnect_secs=float(e.get("GT7_IDLE_DISCONNECT_SECS", "600")),
            telemetry_timeout_secs=float(e.get("GT7_TELEMETRY_TIMEOUT_SECS", "3")),
            log_level=e.get("LOG_LEVEL", "INFO").upper(),
            record_dir=Path(e["GT7_RECORD_DIR"]) if e.get("GT7_RECORD_DIR") else None,
            record_keep=int(e.get("GT7_RECORD_KEEP", "20")),
            results_channel_id=_int_or_none(e, "DISCORD_RESULTS_CHANNEL_ID") or None,
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


def _int_or_none(env: Mapping[str, str], name: str) -> int | None:
    value = env.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_script() -> dict[str, Any]:
    """The bundled script: phrase variants keyed like the rules config."""
    from importlib.resources import files

    text = files("those_who_run.data").joinpath("script.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def load_rules_config(path: Path | None) -> dict[str, Any]:
    """Defaults, then the bundled script unless ``script: false``, then the YAML
    file, if any. Unknown keys are kept for rules to read."""
    loaded = _read_rules_file(path) if path is not None else {}
    base = DEFAULT_RULES
    if loaded.get("script", DEFAULT_RULES["script"]):
        base = deep_merge(base, load_script())
    return deep_merge(base, loaded)


def _read_rules_file(path: Path) -> Mapping[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"rules file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"rules file is not valid YAML: {path}: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"rules file must be a mapping at the top level: {path}")
    return loaded
