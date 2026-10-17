"""Settings from environment variables and rule configuration from YAML."""

from __future__ import annotations

import copy
import logging
import math
import os
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

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
            "template_fuel_stints": "Fuel used {stints}.",
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


LOG_LEVELS = logging.getLevelNamesMapping()


@dataclass(frozen=True, slots=True)
class LiveSettings:
    """What ``run`` needs on top of :class:`Settings`, with the types narrowed."""

    ps5_ip: str
    discord_token: str
    discord_channel_id: int


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
    web_port: int = 8501  # the pit wall, ``those-who-run web``
    pitwall_url: str | None = None  # where the pit wall is served; results cards link there
    cache_dir: Path | None = None  # the speech cache; None is the XDG cache dir
    cache_max_mb: int = 100

    @property
    def speech_cache_dir(self) -> Path:
        return self.cache_dir if self.cache_dir is not None else default_cache_dir()

    @property
    def cache_max_bytes(self) -> int:
        return self.cache_max_mb * 1024 * 1024

    # Every variable whose value is parsed, and so can be invalid.
    PARSED: ClassVar[tuple[str, ...]] = (
        "DISCORD_VOICE_CHANNEL_ID",
        "DISCORD_RESULTS_CHANNEL_ID",
        "GT7_METRICS_PORT",
        "GT7_IDLE_DISCONNECT_SECS",
        "GT7_TELEMETRY_TIMEOUT_SECS",
        "GT7_RECORD_KEEP",
        "GT7_WEB_PORT",
        "GT7_CACHE_MAX_MB",
        "LOG_LEVEL",
        "GT7_CACHE_DIR",  # not parsed, but checked: it must not be under GT7_DATA_DIR
    )

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, check: Collection[str] | None = None
    ) -> Settings:
        """Settings from the environment. An invalid value raises
        :class:`ConfigError` naming the variable. ``check`` limits that to the
        variables a command uses; an invalid value in any other variable falls
        back to its default, since the command never reads it. None checks all."""
        e = os.environ if env is None else env

        def parsed(name: str, parse: Callable[[Mapping[str, str], str], Any], default: Any) -> Any:
            try:
                return parse(e, name)
            except ConfigError:
                if check is None or name in check:
                    raise
                return default

        rules_file = e.get("GT7_RULES_FILE")
        settings = cls(
            ps5_ip=e.get("GT7_PS5_IP") or None,
            discord_token=e.get("DISCORD_BOT_TOKEN") or None,
            discord_channel_id=parsed("DISCORD_VOICE_CHANNEL_ID", _id_env, None),
            rules_file=Path(rules_file) if rules_file else None,
            data_dir=Path(e.get("GT7_DATA_DIR", "./data")),
            voice_model=Path(e.get("GT7_VOICE_MODEL", "voices/en_GB-alba-medium.onnx")),
            metrics_port=parsed("GT7_METRICS_PORT", _port_env(9850), 9850),
            idle_disconnect_secs=parsed(
                "GT7_IDLE_DISCONNECT_SECS", _float_env(600.0, minimum=0.0), 600.0
            ),
            telemetry_timeout_secs=parsed(
                "GT7_TELEMETRY_TIMEOUT_SECS", _float_env(3.0, above=0.0), 3.0
            ),
            log_level=parsed("LOG_LEVEL", _level_env, "INFO"),
            record_dir=Path(e["GT7_RECORD_DIR"]) if e.get("GT7_RECORD_DIR") else None,
            record_keep=parsed("GT7_RECORD_KEEP", _int_env(20, minimum=0), 20),
            results_channel_id=parsed("DISCORD_RESULTS_CHANNEL_ID", _id_env, None) or None,
            web_port=parsed("GT7_WEB_PORT", _port_env(8501), 8501),
            pitwall_url=e.get("PITWALL_URL") or None,
            cache_dir=Path(e["GT7_CACHE_DIR"]) if e.get("GT7_CACHE_DIR") else default_cache_dir(e),
            cache_max_mb=parsed("GT7_CACHE_MAX_MB", _int_env(100, minimum=0), 100),
        )
        if check is None or "GT7_CACHE_DIR" in check:
            settings.check_cache_dir()
        return settings

    def check_cache_dir(self) -> None:
        """The speech cache must not be under the data dir: the pit wall mounts
        that read-write (ADR 0001), so it could plant clips the engineer plays."""
        cache = self.speech_cache_dir.resolve()
        data = self.data_dir.resolve()
        if cache == data or cache.is_relative_to(data):
            raise ConfigError(
                f"GT7_CACHE_DIR {self.speech_cache_dir} is inside GT7_DATA_DIR {self.data_dir}; "
                "put the speech cache outside the data volume"
            )

    def require_live(self) -> LiveSettings:
        missing = [
            name
            for name, value in (
                ("GT7_PS5_IP", self.ps5_ip),
                ("DISCORD_BOT_TOKEN", self.discord_token),
                ("DISCORD_VOICE_CHANNEL_ID", self.discord_channel_id),
            )
            if not value
        ]
        if missing or not self.ps5_ip or not self.discord_token or not self.discord_channel_id:
            raise ConfigError(f"missing required environment variables: {', '.join(missing)}")
        return LiveSettings(self.ps5_ip, self.discord_token, self.discord_channel_id)


def default_cache_dir(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_CACHE_HOME/those-who-run``, else ``~/.cache/those-who-run``."""
    e = os.environ if env is None else env
    xdg = e.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "those-who-run"
    home = e.get("HOME")
    return (Path(home) if home else Path.home()) / ".cache" / "those-who-run"


def _int_or_none(env: Mapping[str, str], name: str) -> int | None:
    value = env.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def _id_env(env: Mapping[str, str], name: str) -> int | None:
    value = _int_or_none(env, name)
    if value is not None and value < 0:
        raise ConfigError(f"{name} must be a Discord channel id (0 or more), got {value}")
    return value


def _int_env(
    default: int, minimum: int | None = None, maximum: int | None = None
) -> Callable[[Mapping[str, str], str], int]:
    def parse(env: Mapping[str, str], name: str) -> int:
        value = _int_or_none(env, name)
        if value is None:
            return default
        if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
            if maximum is None:
                raise ConfigError(f"{name} must be {minimum} or more, got {value}")
            raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
        return value

    return parse


def _port_env(default: int) -> Callable[[Mapping[str, str], str], int]:
    return _int_env(default, minimum=1, maximum=65535)


def _float_env(
    default: float, minimum: float | None = None, above: float | None = None
) -> Callable[[Mapping[str, str], str], float]:
    def parse(env: Mapping[str, str], name: str) -> float:
        raw = env.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
        if not math.isfinite(value):
            raise ConfigError(f"{name} must be a finite number, got {raw!r}")
        if minimum is not None and value < minimum:
            raise ConfigError(f"{name} must be {minimum:g} or more, got {raw}")
        if above is not None and value <= above:
            raise ConfigError(f"{name} must be more than {above:g}, got {raw}")
        return value

    return parse


def _level_env(env: Mapping[str, str], name: str) -> str:
    raw = env.get(name) or "INFO"
    level = raw.strip().upper()
    if level not in LOG_LEVELS:
        names = ", ".join(n for n in LOG_LEVELS if n not in ("WARN", "FATAL"))
        raise ConfigError(f"{name} must be one of {names}, got {raw!r}")
    return level


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
    cfg = deep_merge(base, loaded)
    validate_templates(cfg)
    return cfg


TEMPLATE_PREFIXES = ("template", "delta_")


def validate_templates(cfg: Mapping[str, Any]) -> None:
    """Every template key (``template*``, ``delta_*``) holds a string, null (the
    built-in phrase) or a list of strings and nulls; anything else would be
    spoken as its Python repr, so it is a ``ConfigError`` naming the key."""
    rules = cfg.get("rules") or {}
    if not isinstance(rules, Mapping):
        raise ConfigError("rules must be a mapping of rule name to settings")
    for rule, settings in rules.items():
        if not isinstance(settings, Mapping):
            continue
        for key, value in settings.items():
            if not str(key).startswith(TEMPLATE_PREFIXES) or value is None:
                continue
            if isinstance(value, str):
                continue
            if isinstance(value, list) and all(v is None or isinstance(v, str) for v in value):
                continue
            raise ConfigError(
                f"rules.{rule}.{key} must be a string or a list of strings, got {value!r}"
            )


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
