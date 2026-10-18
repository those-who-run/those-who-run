"""Normalised race state derived from a GT7 telemetry packet.

Everything downstream (rules, recorder, metrics, replay files) works on
``RaceState`` so that gt-telem is only touched in one place and recordings
stay stable across gt-telem releases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

STATE_FORMAT_VERSION = 2
SUPPORTED_FORMAT_VERSIONS = {1, 2}

Wheel = tuple[float, float, float, float]


class Phase(StrEnum):
    MENU = "menu"
    LOADING = "loading"
    AT_TRACK = "at_track"
    IN_RACE = "in_race"
    PAUSED = "paused"
    FINISHED = "finished"


def derive_phase(current_lap: int, total_laps: int, is_paused: bool, is_loading: bool) -> Phase:
    """Map GT7's lap counter and flag bits onto a phase.

    Observed from a real session (2026-10-14): ``current_lap`` is ``-1`` in
    menus, ``0`` at a track before the start, ``>= 1`` while driving, and
    ``total_laps + 1`` once the chequered flag falls. Time trials and practice
    report ``total_laps == 0`` and GT7's "cars on track" flag false, so the
    flag is not used to decide whether laps are being driven. After the
    results screen GT7 replays the final frames of the race for a moment;
    those frames are ``FINISHED`` because the lap counter is past the total.
    """
    if is_loading:
        return Phase.LOADING
    if current_lap < 0:
        return Phase.MENU
    if is_paused:
        return Phase.PAUSED
    if total_laps > 0 and current_lap > total_laps:
        return Phase.FINISHED
    if current_lap >= 1:
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
    cars_on_track: bool = False
    # Full-frame fields (format v2). Not used by the rules; kept for the session
    # store and the pit wall. Defaults let v1 recordings load.
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    vel_x: float = 0.0
    vel_y: float = 0.0
    vel_z: float = 0.0
    # Body rotation and spin, raw from the packet (kept from 0.3 for drift
    # detection, #65). rot_* are GT7's rotation components and orientation its
    # heading-like value; which combination gives the car's heading is settled
    # from recordings. ang_vel_* in radians per second; ang_vel_y is yaw rate.
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    orientation: float = 0.0
    ang_vel_x: float = 0.0
    ang_vel_y: float = 0.0
    ang_vel_z: float = 0.0
    throttle: int = 0
    brake: int = 0
    current_gear: int = 0
    suggested_gear: int = 0
    tire_radius: Wheel = (0.0, 0.0, 0.0, 0.0)
    suspension_height: Wheel = (0.0, 0.0, 0.0, 0.0)
    wheel_rps: Wheel = (0.0, 0.0, 0.0, 0.0)
    boost_pressure: float = 0.0
    oil_pressure: float = 0.0
    body_height: float = 0.0
    car_code: int = 0
    time_of_day_ms: int = 0

    @property
    def in_race(self) -> bool:
        return self.phase is Phase.IN_RACE

    @property
    def position(self) -> int | None:
        """Live race position. GT7 (and gt-telem) label this the start position, but
        it updates every time a place changes. -1 outside a race."""
        return self.race_start_pos if self.race_start_pos > 0 else None

    @property
    def is_race(self) -> bool:
        """True for a race against other cars; False for time trial, practice, licences."""
        return self.cars_on_track

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
        tr, sh, wr = tel.tire_radius, tel.suspension_height, tel.wheel_rps
        return cls(
            t=t,
            packet_id=int(tel.packet_id),
            phase=derive_phase(
                int(tel.current_lap),
                int(tel.total_laps),
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
            cars_on_track=bool(tel.cars_on_track),
            pos_x=float(tel.position_x),
            pos_y=float(tel.position_y),
            pos_z=float(tel.position_z),
            vel_x=float(tel.velocity_x),
            vel_y=float(tel.velocity_y),
            vel_z=float(tel.velocity_z),
            rot_x=float(tel.rotation_x),
            rot_y=float(tel.rotation_y),
            rot_z=float(tel.rotation_z),
            orientation=float(tel.orientation),
            ang_vel_x=float(tel.ang_vel_x),
            ang_vel_y=float(tel.ang_vel_y),
            ang_vel_z=float(tel.ang_vel_z),
            throttle=int(tel.throttle),
            brake=int(tel.brake),
            current_gear=int(tel.current_gear),
            suggested_gear=int(tel.suggested_gear),
            tire_radius=(float(tr.fl), float(tr.fr), float(tr.rl), float(tr.rr)),
            suspension_height=(float(sh.fl), float(sh.fr), float(sh.rl), float(sh.rr)),
            wheel_rps=(float(wr.fl), float(wr.fr), float(wr.rl), float(wr.rr)),
            boost_pressure=float(tel.boost_pressure),
            oil_pressure=float(tel.oil_pressure),
            body_height=float(tel.body_height),
            car_code=int(tel.car_code),
            time_of_day_ms=int(tel.time_of_day_ms),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        for k in _WHEEL_FIELDS:
            d[k] = list(getattr(self, k))
        d["v"] = STATE_FORMAT_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RaceState:
        d = dict(d)
        version = d.pop("v", 1)
        if version not in SUPPORTED_FORMAT_VERSIONS:
            raise ValueError(f"unsupported state format version {version}")
        phase = Phase(d["phase"])
        if phase in (Phase.AT_TRACK, Phase.IN_RACE, Phase.FINISHED):
            # Recordings made before the lap-count based phase rules carry the
            # older labels; the lap counters are authoritative, so re-derive.
            phase = derive_phase(int(d["current_lap"]), int(d["total_laps"]), False, False)
        d["phase"] = phase
        for k in _WHEEL_FIELDS:
            if k in d:
                d[k] = tuple(float(x) for x in d[k])
        return cls(**d)


_WHEEL_FIELDS = ("tire_temp", "tire_radius", "suspension_height", "wheel_rps")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


# Transition helpers. Rules and the engine share these so every component
# agrees on what "a lap was completed" means.


def racing_frame(prev: RaceState | None, state: RaceState) -> bool:
    """``state`` continues a race from ``prev``, including the finish-line frame
    where the phase flips to FINISHED on the same packet as the final lap time."""
    return prev is not None and prev.in_race and state.phase in (Phase.IN_RACE, Phase.FINISHED)


def lap_completed(prev: RaceState | None, state: RaceState) -> bool:
    """The lap counter advanced by one while driving."""
    return (
        racing_frame(prev, state)
        and prev is not None
        and prev.current_lap >= 1
        and state.current_lap == prev.current_lap + 1
    )


def lap_time_posted(prev: RaceState | None, state: RaceState) -> bool:
    """A lap time is available for a lap that just finished.

    GT7 publishes the last-lap time in the same frame as the counter bump
    (confirmed from a recording). Both conditions are kept so two identical
    lap times in a row are still announced; the lap-time rule dedupes per lap.
    """
    if not racing_frame(prev, state) or state.last_lap_ms <= 0:
        return False
    assert prev is not None
    return state.last_lap_ms != prev.last_lap_ms or lap_completed(prev, state)


def posted_lap(state: RaceState) -> int:
    """The lap a posted time (``lap_time_posted``) belongs to: the last completed
    lap, one behind the counter. GT7 bumps the counter on the frame it posts the
    time (every real recording, 2026-10-17), so a time that changes on a later
    frame without a bump is a second post for that same lap, not a time for the
    lap in progress. Rules dedupe on this number: each lap counts once."""
    return max(state.current_lap - 1, 1)


def race_started(prev: RaceState | None, state: RaceState) -> bool:
    """First driving frame of a session. Loading screens and pauses are not starts,
    and neither are the replayed frames GT7 shows after the results screen: those
    come from the track screen carrying the finished race's lap counter (lap 6
    after a five-lap timed race, 2026-10-16), while a real start is on lap 1."""
    if not state.in_race:
        return False
    if prev is None:
        return True
    return (
        prev.phase in (Phase.MENU, Phase.AT_TRACK)
        and prev.current_lap < 1
        and state.current_lap <= 1
    )


def race_ended(prev: RaceState | None, state: RaceState) -> bool:
    """The session is over: chequered flag, back to a menu or the track screen, or a
    loading screen with the lap counter reset (quitting from the pause menu goes
    IN_RACE -> PAUSED -> LOADING(lap 0) -> AT_TRACK, seen 2026-10-14). A loading
    blip that keeps the lap counter only suspends the race."""
    if prev is None or prev.phase not in (Phase.IN_RACE, Phase.PAUSED, Phase.LOADING):
        return False
    if prev.current_lap < 1:
        return False
    if state.phase in (Phase.MENU, Phase.AT_TRACK, Phase.FINISHED):
        return True
    return state.phase is Phase.LOADING and state.current_lap < 1


def race_restarted(prev: RaceState | None, state: RaceState) -> bool:
    """GT7 jumped straight back to lap 1 while driving: the restart option in the
    pause menu (seen in qualifying 2026-10-14, with the fuel refilled too)."""
    return (
        prev is not None
        and prev.phase in (Phase.IN_RACE, Phase.PAUSED)
        and state.in_race
        and 1 <= state.current_lap < prev.current_lap
    )
