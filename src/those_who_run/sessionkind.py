"""Work out what kind of session is running from telemetry.

GT7 sends no mode field. What it does send is enough to sort sessions into a
few kinds, checked against every NUC recording of 2026-10-15:

- **Lap race:** a lap total and at least two cars. A race against one AI car
  reports two (Suzuka East, P1 or P2 of 2).
- **Solo laps:** a lap total and one car (the BRZ drift run at Tsukuba, a one-lap
  Suzuka East outing).
- **Timed with a field:** no lap total and three or more cars. Qualifying and a
  timed race look exactly alike (Nürburgring qualifying, 2026-10-14).
- **Solo timed:** no lap total and one car: a time trial or practice. A second
  car can appear part way through (the ghost, at Fuji and SUGO), so two cars
  only make a field once the driver has been anything but first.

Two more facts ride along. **Fuel use** is on once the level has dropped
``fuel_drop`` below the highest level seen while racing (a refuel raises the
mark), which every recording with fuel on shows within three seconds; it is off
after ``fuel_settle_secs`` of driving without a drop, or at once when the car
has no tank, and turns on again if a drop comes later. **Cars on track** is
GT7's flag as reported; it was never set in the sessions between 18:50 and
19:17 on 2026-10-15, a mode still to be named.

``total_cars`` is -1 in the frames GT7 replays around the results screen and
for the whole of a time trial, so -1 says nothing about the field. GT7 can also
post the lap total a moment after the race starts, so the verdict is kept up to
date like the track detector's: feed every frame, read ``kind``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from those_who_run.state import Phase, RaceState

Kind = Literal["unknown", "lap_race", "solo_laps", "timed_field", "solo_timed"]

LABELS: dict[str, str] = {
    "unknown": "unknown",
    "lap_race": "lap race",
    "solo_laps": "solo laps",
    "timed_field": "timed race or qualifying",
    "solo_timed": "time trial or practice",
}


@dataclass(frozen=True, slots=True)
class SessionKind:
    kind: Kind
    total_laps: int  # 0 for timed sessions
    field: bool  # other cars racing for position
    fuel_use: bool | None  # None until known
    cars_on_track: bool  # GT7's flag, as last reported
    evidence: str

    @property
    def decision(self) -> tuple[str, bool | None, bool]:
        """What callers act on. Evidence wording changes; these do not, often."""
        return (self.kind, self.fuel_use, self.cars_on_track)

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    def record(self) -> dict[str, object]:
        """As stored in summary.json and shown by /healthz."""
        return {
            "kind": self.kind,
            "total_laps": self.total_laps,
            "field": self.field,
            "fuel_use": self.fuel_use,
            "cars_on_track": self.cars_on_track,
            "evidence": self.evidence,
        }


UNKNOWN = SessionKind("unknown", 0, False, None, False, "no race frame yet")


class SessionDetector:
    def __init__(
        self,
        fuel_settle_secs: float = 20.0,
        fuel_drop: float = 0.05,
        moving_kph: float = 20.0,
        max_step_secs: float = 1.0,
    ) -> None:
        self.fuel_settle = fuel_settle_secs
        self.fuel_drop = fuel_drop
        self.moving_kph = moving_kph
        self.max_step = max_step_secs  # a pause or a gap is not driving time
        self.reset()

    def reset(self) -> None:
        """Forget everything: call on a race start or restart."""
        self._valid = False
        self._laps = 0
        self._cars = 0
        self._field = False
        self._cars_on_track = False
        self._fuel_use: bool | None = None
        self._top_fuel: float | None = None
        self._last_t: float | None = None
        self._driving_secs = 0.0
        self._kind: SessionKind = UNKNOWN

    @property
    def kind(self) -> SessionKind:
        return self._kind

    def observe(self, state: RaceState) -> SessionKind | None:
        """Feed one frame. Returns the new verdict when the decision changed."""
        if state.phase is not Phase.IN_RACE:
            self._last_t = None  # the next racing frame starts a new step
            return None
        self._valid = True
        if state.total_cars >= 0:
            self._cars = state.total_cars
            self._cars_on_track = state.cars_on_track
            if state.total_laps > 0:
                self._laps = state.total_laps
            position = state.position
            if self._cars >= 3 or (position is not None and position > 1):
                self._field = True
        self._observe_fuel(state)
        new = self._decide()
        changed = new.decision != self._kind.decision or new.kind != self._kind.kind
        self._kind = new
        return new if changed else None

    def _observe_fuel(self, state: RaceState) -> None:
        if self._fuel_use:
            return
        if state.fuel_capacity <= 0:
            self._fuel_use = False
            return
        if self._top_fuel is None or state.fuel_level > self._top_fuel:
            self._top_fuel = state.fuel_level
        if state.fuel_level < self._top_fuel - self.fuel_drop:
            self._fuel_use = True
            return
        if self._last_t is not None and state.speed_kph >= self.moving_kph:
            self._driving_secs += min(state.t - self._last_t, self.max_step)
        self._last_t = state.t
        if self._driving_secs >= self.fuel_settle:
            self._fuel_use = False

    def _decide(self) -> SessionKind:
        if not self._valid:
            return UNKNOWN
        kind: Kind
        if self._laps > 0:
            kind = "lap_race" if self._cars >= 2 or self._field else "solo_laps"
            why = f"{self._laps} laps, {self._cars} cars"
        else:
            kind = "timed_field" if self._field else "solo_timed"
            why = f"no lap total, {self._cars} cars"
            if self._field and self._cars < 3:
                why += ", not always first"
        if self._fuel_use is None:
            why += "; fuel use not known yet"
        else:
            why += "; fuel use " + ("on" if self._fuel_use else "off")
        field = kind in ("lap_race", "timed_field")
        return SessionKind(kind, self._laps, field, self._fuel_use, self._cars_on_track, why)
