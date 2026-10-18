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

The **start** is read from the fastest the car goes in the first
``start_window_packets`` of racing (18, 0.3 s of GT7's 60 packets a second): a
grid start is near standstill, anything else is moving. A moving start is
rolling in a lap race (80 to 238 km/h in the recordings, the field behind the
pace until green) and flying otherwise (out of the pits onto a timed lap, 37 to
250 km/h). The window is short because the first racing frames after a loading
screen can read 0 km/h (Nordschleife, 2026-10-15), and no car reaches
``grid_kph`` from a standstill inside it. It counts GT7's packets, not the
clock: packets arrive in bursts, up to 2 s of them in 0.5 s of wall time and
then a gap (Suzuka, 2026-10-15), so a clock window could close on those first
standing frames alone and read a rolling start as a grid one. No grid start has
been recorded yet.

``total_cars`` is -1 in the frames GT7 replays around the results screen and
for the whole of a time trial, so -1 says nothing about the field. GT7 can also
post the lap total a moment after the race starts, so the verdict is kept up to
date like the track detector's: feed every frame, read ``kind``.

A **GT7 race replay** sends driving frames too, and GT7 starts it like a race:
the track screen, then lap 1 (SUGO, 2026-10-18, outing ``20261018-100645``).
What gives it away is the cars-on-track flag together with fuel. Every drive
since 2026-10-16 (races, time trials, practice) has the flag set from its first
driving frame, and it drops only on the last frames of a session. The replay
has it off from the first frame to the last, while the fuel drains as it did in
the race it replays (98.3 to 97.6 within 52 packets). The races GT7 never flags
(2026-10-15, a mode still to be named, #63) are unflagged too, but none of them
has ever used fuel, so fuel use is what tells the two apart.

GT7's **attract-mode demo race**, which plays by itself when the PS5 sits idle
on the menu, is the rest of that unflagged group (#260). Every demo on
2026-10-18 (nine between 10:31 and 13:02) goes from the menu to the track
screen and into lap 1 with no loading screen, has the flag off on every frame
and keeps the fuel at 100. A drive always loads its track first: menu, loading,
track screen, loading, track screen, then lap 1, in every recording with a menu
before the start. The 2026-10-15 group are demos too: the Laguna Seca and
Nordschleife fixtures match the 2026-10-18 demos in the same cars frame for
frame (same positions, speeds and time of day), and Tokyo East and the
Tsukuba drift laps start the same way. A demo can also be joined part way, when
the engineer starts while one plays (2026-10-18 11:01, on lap 2 of 5): with no
menu seen there is nothing to say whether a track was loaded, but GT7 reports
a field of cars there while its cars-on-track flag says there are none, which
no drive has done.

``DriverCheck`` judges a session that starts unflagged. It is a **replay** once
the fuel drops, and a drive once the flag comes on. When ``window_secs`` (or
``window_packets``) pass without either, which is longer than any drive with
fuel on takes to show a drop, or the session ends or pauses first, it is a
**demo** if no loading screen came since the last menu, or if no menu has been
seen and GT7 reports two or more cars; anything else is a drive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from those_who_run.state import Phase, RaceState

Kind = Literal["unknown", "lap_race", "solo_laps", "timed_field", "solo_timed"]
Start = Literal["unknown", "grid", "rolling", "flying"]

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
    start: Start = "unknown"

    @property
    def decision(self) -> tuple[str, bool | None, bool, str]:
        """What callers act on. Evidence wording changes; these do not, often."""
        return (self.kind, self.fuel_use, self.cars_on_track, self.start)

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
            "start": self.start,
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
        start_window_packets: int = 18,
        grid_kph: float = 30.0,
    ) -> None:
        self.fuel_settle = fuel_settle_secs
        self.fuel_drop = fuel_drop
        self.moving_kph = moving_kph
        self.max_step = max_step_secs  # a pause or a gap is not driving time
        self.start_window = start_window_packets
        self.grid_kph = grid_kph
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
        self._start_packet: int | None = None
        self._start_kph = 0.0
        self._start_known = False
        self._joined = False
        self._kind: SessionKind = UNKNOWN

    def join(self) -> None:
        """The session was joined part way through (#265): its start was not seen,
        so the start type stays unknown. Call after ``reset``."""
        self._joined = True

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
        self._observe_start(state)
        new = self._decide()
        changed = new.decision != self._kind.decision
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

    def _observe_start(self, state: RaceState) -> None:
        if self._start_known:
            return
        if self._start_packet is None:
            self._start_packet = state.packet_id
        self._start_kph = max(self._start_kph, state.speed_kph)
        packets = state.packet_id - self._start_packet
        if packets >= self.start_window or packets < 0:  # < 0: GT7's counter started over
            self._start_known = True

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
        start: Start = "unknown"
        if self._joined:
            why += "; joined part way, start not seen"
        elif self._start_known:
            if self._start_kph < self.grid_kph:
                start = "grid"
            else:
                start = "rolling" if kind == "lap_race" else "flying"
            why += f"; {start} start at {self._start_kph:.0f} km/h"
        field = kind in ("lap_race", "timed_field")
        return SessionKind(kind, self._laps, field, self._fuel_use, self._cars_on_track, why, start)


Verdict = Literal["drive", "replay", "demo"]


class DriverCheck:
    """Is a session that starts with GT7's cars-on-track flag off the driver
    driving, a replay or a demo? See the module docstring. Feed ``see`` every
    frame, so it knows whether a track was loaded since the menu. Call ``start``
    with the session's first driving frame, then feed each later frame to
    ``observe`` until it returns a verdict; ``why`` then says what decided it."""

    def __init__(
        self,
        fuel_drop: float = 0.05,
        window_secs: float = 3.0,
        window_packets: int = 180,
        field_cars: int = 2,
    ) -> None:
        self.fuel_drop = fuel_drop
        self.window_secs = window_secs
        self.window_packets = window_packets
        self.field_cars = field_cars
        self.loaded: bool | None = None  # a loading screen since the last menu; None: no menu yet
        self.first: RaceState | None = None
        self.top_fuel = 0.0
        self.cars = -1
        self.why = ""

    def see(self, state: RaceState) -> None:
        if state.phase is Phase.MENU:
            self.loaded = False
        elif state.phase is Phase.LOADING and self.loaded is not None:
            self.loaded = True

    def start(self, state: RaceState) -> None:
        self.first = state
        self.top_fuel = state.fuel_level
        self.cars = state.total_cars
        self.why = ""

    def observe(self, state: RaceState) -> Verdict | None:
        first = self.first
        assert first is not None, "start() first"
        if state.phase is not Phase.IN_RACE:
            return self._settle()  # a pause or an end inside the window
        if state.cars_on_track:
            return "drive"  # nothing a replay or a demo does
        self.cars = max(self.cars, state.total_cars)
        self.top_fuel = max(self.top_fuel, state.fuel_level)
        if state.fuel_capacity > 0 and state.fuel_level < self.top_fuel - self.fuel_drop:
            self.why = (
                f"fuel is draining ({first.fuel_level:.1f} -> {state.fuel_level:.1f}),"
                " which only a replay does"
            )
            return "replay"
        packets = state.packet_id - first.packet_id
        if state.t - first.t >= self.window_secs or not 0 <= packets < self.window_packets:
            return self._settle()
        return None

    def _settle(self) -> Verdict:
        if self.loaded is False:
            self.why = "it came straight from the menu with no loading screen"
            return "demo"
        if self.loaded is None and self.cars >= self.field_cars:
            self.why = f"it was joined part way with no menu seen and GT7 reports {self.cars} cars"
            return "demo"
        return "drive"
