"""Pauses: how long a session has been paused, and the two shapes a pause takes.

GT7 flags most of a pause: its frames are ``PAUSED`` for as long as the pause
menu is up (an hour of them at 60 Hz in outing 20261017-205541). From the pause
menu it can also send a frozen stream instead: frames marked ``IN_RACE`` that do
not change at all, the car stopped in mid-air at racing speed. SUGO 2026-10-18
(outing 20261018-130722) has 1.2 s of ``PAUSED`` and then 45 s of identical
``IN_RACE`` frames at 26.9 km/h until the driver picked Restart; Fuji and SUGO
time trials (2026-10-15) and the Suzuka timed race's results screen (2026-10-16)
show the same freeze before a quit. ``PauseClock`` reads a frame that is identical
to the ones before it for ``FREEZE_SECS``, with the car moving, as paused: a
moving car cannot keep its exact position, speed and revs for a second.

A car standing still can (a grid start, the pit box), so a frozen frame at a
standstill is not a pause: GT7 flags a real pause there anyway. The first second
of a freeze still reads as driving, as it can only be told apart afterwards;
the pause is dated from its first frame all the same (``since``).

The clock counts per session (``reset`` at each start): ``paused_secs`` is the
pauses that ended, ``since`` the start of the one in progress. Frame time
(``RaceState.t``) is used throughout, so a replay gives the same totals.
"""

from __future__ import annotations

from dataclasses import replace

from those_who_run.state import Phase, RaceState

FREEZE_SECS = 1.0  # identical frames for this long, with the car moving, are a pause
FREEZE_MIN_KPH = 1.0  # below this, identical frames are a car standing still


def _still(s: RaceState) -> tuple[float | int, ...]:
    """What changes on every frame while the car is driven (the phase, the lap
    total, the flags and the position can change with the pause menu itself)."""
    return (
        s.pos_x,
        s.pos_y,
        s.pos_z,
        s.vel_x,
        s.vel_y,
        s.vel_z,
        s.speed_kph,
        s.engine_rpm,
        s.throttle,
        s.brake,
        s.fuel_level,
        s.current_lap,
        s.rot_x,
        s.rot_y,
        s.rot_z,
        s.ang_vel_x,
        s.ang_vel_y,
        s.ang_vel_z,
    )


class PauseClock:
    def __init__(self) -> None:
        self._key: tuple[float | int, ...] | None = None
        self._run_t = 0.0  # first frame of the current run of identical frames
        self.paused_secs = 0.0
        self.since: float | None = None

    def reset(self) -> None:
        """A new session: no pause counted yet. A pause in progress stays one."""
        self.paused_secs = 0.0

    @property
    def paused(self) -> bool:
        return self.since is not None

    def paused_for(self, t: float) -> float:
        """Seconds paused this session up to ``t``, the pause in progress included."""
        return self.paused_secs + (0.0 if self.since is None else max(t - self.since, 0.0))

    def observe(self, state: RaceState) -> RaceState:
        """``state``, as ``PAUSED`` when it is a frozen frame; and the clock moved on."""
        key = _still(state)
        if key != self._key:
            self._key, self._run_t = key, state.t
        frozen = (
            state.phase is Phase.IN_RACE
            and state.speed_kph > FREEZE_MIN_KPH
            and state.t - self._run_t >= FREEZE_SECS
        )
        if frozen:
            state = replace(state, phase=Phase.PAUSED)
        if state.phase is Phase.PAUSED:
            if self.since is None:
                self.since = self._run_t if frozen else state.t
        elif self.since is not None:
            self.paused_secs += max(state.t - self.since, 0.0)
            self.since = None
        return state
