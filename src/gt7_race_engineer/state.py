"""Normalised race state derived from a GT7 telemetry packet.

Everything downstream (rules, recorder, metrics, replay files) works on
``RaceState`` so that gt-telem is only touched in one place and recordings
stay stable across gt-telem releases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

STATE_FORMAT_VERSION = 1


class Phase(StrEnum):
    MENU = "menu"
    LOADING = "loading"
    AT_TRACK = "at_track"
    IN_RACE = "in_race"
    PAUSED = "paused"


def derive_phase(current_lap: int, cars_on_track: bool, is_paused: bool, is_loading: bool) -> Phase:
    """Map GT7's flag bits and lap counter onto a phase.

    GT7 reports ``current_lap == -1`` in menus, ``0`` at a track before the
    race starts, and ``>= 1`` once the race is under way (including the
    countdown). The order of checks matters: a loading screen or a menu wins
    over a stale pause flag.
    """
    if is_loading:
        return Phase.LOADING
    if current_lap < 0:
        return Phase.MENU
    if is_paused:
        return Phase.PAUSED
    if cars_on_track and current_lap >= 1:
        return Phase.IN_RACE
    return Phase.AT_TRACK


@dataclass(frozen=True, slots=True)
class RaceState:
    t: float
    packet_id: int
    phase: Phase
    current_lap: int
    total_laps: int
    best_lap_ms: int
    last_lap_ms: int
    fuel_level: float
    fuel_capacity: float
    speed_kph: float
    engine_rpm: float
    tire_temp: tuple[float, float, float, float]
    water_temp: float
    oil_temp: float
    track_id: int | None
    race_start_pos: int
    total_cars: int

    @property
    def in_race(self) -> bool:
        return self.phase is Phase.IN_RACE

    @property
    def has_lap_count(self) -> bool:
        """True for lap-count races; timed races report ``total_laps == 0``."""
        return self.total_laps > 0

    @property
    def laps_left(self) -> int | None:
        """Laps still to run including the current one, or None for timed races."""
        if not self.has_lap_count:
            return None
        return max(self.total_laps - self.current_lap + 1, 0)

    @classmethod
    def from_telemetry(cls, tel: Any, t: float) -> RaceState:
        """Build from a ``gt_telem.models.telemetry.Telemetry`` instance."""
        tt = tel.tire_temp
        return cls(
            t=t,
            packet_id=int(tel.packet_id),
            phase=derive_phase(
                int(tel.current_lap),
                bool(tel.cars_on_track),
                bool(tel.is_paused),
                bool(tel.is_loading),
            ),
            current_lap=int(tel.current_lap),
            total_laps=int(tel.total_laps),
            best_lap_ms=int(tel.best_lap_time_ms),
            last_lap_ms=int(tel.last_lap_time_ms),
            fuel_level=float(tel.fuel_level),
            fuel_capacity=float(tel.fuel_capacity),
            speed_kph=float(tel.speed_kph),
            engine_rpm=float(tel.engine_rpm),
            tire_temp=(float(tt.fl), float(tt.fr), float(tt.rl), float(tt.rr)),
            water_temp=float(tel.water_temp),
            oil_temp=float(tel.oil_temp),
            track_id=_optional_int(getattr(tel, "track_id", None)),
            race_start_pos=int(tel.race_start_pos),
            total_cars=int(tel.total_cars),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        d["tire_temp"] = list(self.tire_temp)
        d["v"] = STATE_FORMAT_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RaceState:
        d = dict(d)
        version = d.pop("v", STATE_FORMAT_VERSION)
        if version != STATE_FORMAT_VERSION:
            raise ValueError(f"unsupported state format version {version}")
        d["phase"] = Phase(d["phase"])
        d["tire_temp"] = tuple(float(x) for x in d["tire_temp"])
        return cls(**d)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Transition helpers. Rules and the engine share these so every component
# agrees on what "a lap was completed" means.


def lap_completed(prev: RaceState | None, state: RaceState) -> bool:
    """The lap counter advanced by one while racing."""
    return (
        prev is not None
        and state.in_race
        and prev.current_lap >= 1
        and state.current_lap == prev.current_lap + 1
    )


def lap_time_posted(prev: RaceState | None, state: RaceState) -> bool:
    """A lap time is available for a lap that just finished.

    Fires when GT7 publishes a new last-lap time or when the lap counter
    advances with a valid time already present (two identical lap times in a
    row would otherwise be missed). Whether the time lands in the same frame as
    the counter bump or one frame later is to be confirmed from a recording;
    the lap-time rule dedupes per lap number either way.
    """
    if prev is None or not state.in_race or state.last_lap_ms <= 0:
        return False
    return state.last_lap_ms != prev.last_lap_ms or lap_completed(prev, state)


def race_started(prev: RaceState | None, state: RaceState) -> bool:
    """First frame of a race. Resuming from pause is not a start."""
    if not state.in_race or state.current_lap < 1:
        return False
    if prev is None:
        return True
    if prev.phase is Phase.PAUSED:
        return False
    return not prev.in_race or prev.current_lap < 1


def race_ended(prev: RaceState | None, state: RaceState) -> bool:
    """Race is over: the game left the race phase, or the counter passed the last lap."""
    if prev is None or not prev.in_race:
        return False
    if state.phase in (Phase.MENU, Phase.AT_TRACK):
        return True
    return (
        state.in_race
        and state.has_lap_count
        and state.current_lap > state.total_laps
        and prev.current_lap <= prev.total_laps
    )
