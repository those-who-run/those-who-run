"""Spot pit stops from telemetry: entry, the stop, exit, in-laps and out-laps.

GT7 sends no pit flag. What it does is cut the camera: a pit stop is a run of
one-frame loading screens in the middle of a race, with the lap counter never
reset. Every stop recorded so far shows the same three cuts (Suzuka East
2026-10-15, Willow Springs three times 2026-10-16 and 17, Circuit Gilles
Villeneuve 2026-10-17):

1. **Entry.** The car is moved into the pit lane (120 to 330 m in one frame)
   and the next frame reads the pit limiter, 60.0 km/h with no pedals: GT7
   drives the car to its box. At Willow the picture freezes at the pit entry
   for five seconds first (0 km/h, position fixed, still ``IN_RACE``).
2. **The box.** One or two cuts with the car at rest. The fuel then climbs
   about ten per cent a second to what was asked for (20 -> 100 at Gilles
   Villeneuve, 16 -> 65 at Willow), and new tyres show as all four tyre
   temperatures dropping to 60.0 °C in one frame. Tyre radius never changes.
3. **Exit.** After the car has moved off, a cut puts it at the pit exit at
   80 km/h (79.9 on the next frame).

The finish line can be anywhere in that sequence. Suzuka East crosses it in
the entry cut, Willow in the exit cut, and Gilles Villeneuve in the pit lane
itself, after the box, on a driving frame at the limiter. So the detector does
not reason about the line: the **in-lap** is the lap the car entered the pits
on and the **out-lap** the lap it left them on, and every lap from one to the
other is a pit lap (two laps, every time so far).

The cuts are what finds a stop. The rest is recorded, not relied on: the
limiter reading is only there after the entry cut, and cars do 60 km/h on
track; the fuel only jumps if fuel was asked for; positions fall while the car
stands in the box (P5 to P11 at Gilles Villeneuve, P3 to P10 at Willow), as
they do in a spin.

Out-of-race loading screens (menus, quitting, a restart) never keep the lap
counter: the loading frame reads lap 0 and the next frame is the track screen
(every recording of 2026-10-14 to 2026-10-17). A cut whose loading frame keeps
a lap of 1 or more, coming from a racing frame, is the pits; no race without a
stop has one.

A cut is a single packet, so a dropped packet must not hide it. Two fallbacks:
a **teleport** (the car moves faster than ``teleport_kph`` between two
frames, which no car does; the pit cuts imply thousands of km/h) counts as a
cut, and the car going faster than ``exit_kph`` (no pit lane allows it; the
exit cut lands at 80) ends a stop whose exit cut was missed.

Not every cut or teleport is the pits: being put back on track after an off
moves the car too. A "stop" that ends without the car ever coming to rest,
with no fuel added and no tyres changed, was not a stop. It is withdrawn (the
status goes back to what it was before the entry, so no stint starts and no
lap is a pit lap) and kept as a ``Teleport`` instead, for the spin and off
detection to come (#98). No reset to track has been recorded yet; a reset that
leaves the car standing still would still read as a stop.

Feed every frame and read ``status``, like the track and session detectors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Literal

from those_who_run.state import Phase, RaceState

LapRole = Literal["in", "out", "in_out"]

PACKETS_PER_SEC = 60.0


@dataclass(frozen=True, slots=True)
class PitStop:
    number: int  # 1 for the first stop of the session
    in_lap: int
    out_lap: int | None  # None while the car is still in the pit lane
    entry_t: float
    exit_t: float | None
    stationary_secs: float  # at rest in the pit lane, mostly the box
    fuel_before: float
    fuel_after: float  # the level as the car leaves, or now while in the pits
    tyres_changed: bool
    pit_lane_kph: float | None  # first driving frame after the entry cut: the limiter
    position_before: int | None
    position_after: int | None
    evidence: str

    @property
    def done(self) -> bool:
        return self.out_lap is not None

    @property
    def fuel_added(self) -> float:
        return max(self.fuel_after - self.fuel_before, 0.0)

    @property
    def pit_lane_secs(self) -> float | None:
        """Entry cut to exit cut: the limiter, the box and the drive out."""
        return None if self.exit_t is None else self.exit_t - self.entry_t

    def covers(self, lap: int) -> bool:
        return self.in_lap <= lap and (self.out_lap is None or lap <= self.out_lap)

    def record(self) -> dict[str, Any]:
        """As stored in summary.json."""
        lane = self.pit_lane_secs
        return {
            "stop": self.number,
            "in_lap": self.in_lap,
            "out_lap": self.out_lap,
            "pit_lane_secs": None if lane is None else round(lane, 2),
            "stationary_secs": round(self.stationary_secs, 2),
            "fuel_before": round(self.fuel_before, 3),
            "fuel_after": round(self.fuel_after, 3),
            "fuel_added": round(self.fuel_added, 3),
            "tyres_changed": self.tyres_changed,
            "pit_lane_kph": None if self.pit_lane_kph is None else round(self.pit_lane_kph, 1),
            "position_before": self.position_before,
            "position_after": self.position_after,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Teleport:
    """A cut or teleport that opened a stop the car never made: no rest, no service."""

    lap: int
    t: float  # when it was withdrawn: the frame that would have closed the stop
    entry_t: float
    evidence: str


@dataclass(frozen=True, slots=True)
class PitStatus:
    in_pit_lane: bool
    stops: tuple[PitStop, ...]
    teleports: tuple[Teleport, ...] = ()  # withdrawn stops, oldest first

    @property
    def stint(self) -> int:
        """1 until the first stop is done, then one more for every stop."""
        return 1 + sum(1 for s in self.stops if s.done)

    @property
    def stint_start_lap(self) -> int:
        """The lap the current stint began on: the last stop's out-lap, or lap 1."""
        done = [s for s in self.stops if s.done]
        return (done[-1].out_lap or 1) if done else 1

    def is_pit_lap(self, lap: int) -> bool:
        """Any part of ``lap`` was spent in the pit lane (an in-lap or out-lap)."""
        return any(s.covers(lap) for s in self.stops)

    def lap_role(self, lap: int) -> LapRole | None:
        for s in self.stops:
            if not s.covers(lap):
                continue
            if lap == s.in_lap:
                return "in_out" if s.out_lap == lap else "in"
            return "out"
        return None

    def record(self) -> dict[str, Any]:
        return {
            "stints": self.stint,
            "pit_stops": [s.record() for s in self.stops],
        }


NO_STOPS = PitStatus(False, ())


class PitDetector:
    def __init__(
        self,
        teleport_kph: float = 600.0,
        teleport_m: float = 10.0,
        rest_kph: float = 1.0,
        moving_kph: float = 5.0,
        exit_kph: float = 100.0,
        tyre_drop: float = 5.0,
        max_step_secs: float = 1.0,
        refuel_min: float = 0.5,
    ) -> None:
        self.teleport_kph = teleport_kph
        self.teleport_m = teleport_m  # GT7 nudges a car at rest by a few cm
        self.rest_kph = rest_kph
        self.moving_kph = moving_kph  # leaving the box, not creeping
        self.exit_kph = exit_kph
        self.tyre_drop = tyre_drop
        self.max_step = max_step_secs  # a pause or a gap is not time at rest
        self.refuel_min = refuel_min  # fuel added that counts as a service
        self.reset()

    def reset(self) -> None:
        """Forget everything: call on a race start or restart."""
        self._stops: list[PitStop] = []
        self._teleports: list[Teleport] = []
        self._open: PitStop | None = None
        self._last: RaceState | None = None  # last racing frame
        self._cut = False  # the frames since _last include a loading screen
        self._paused = False  # ... or a pause, which is not time at rest
        self._rested = False  # the open stop has seen the car at rest
        self._status = NO_STOPS

    @property
    def status(self) -> PitStatus:
        return self._status

    def observe(self, state: RaceState) -> PitStatus | None:
        """Feed one frame. Returns the new status on a pit entry or exit."""
        if state.phase is Phase.LOADING:
            if self._last is not None and state.current_lap >= 1:
                self._cut = True
            else:
                self._last, self._cut = None, False  # out of the race
            return None
        if state.phase is Phase.PAUSED:
            self._paused = True
            return None
        if state.phase is not Phase.IN_RACE:
            self._last, self._cut = None, False
            return None
        last, loading, paused = self._last, self._cut, self._paused
        self._last, self._cut, self._paused = state, False, False
        if last is None:
            return None
        if state.current_lap < last.current_lap:
            self.reset()  # a restart from the pause menu: back on the grid
            self._last = state
            return None
        if loading:
            cut = "loading cut"
        elif self._teleported(last, state):
            cut = "teleport"
        else:
            cut = None
        if self._open is None:
            return None if cut is None else self._enter(last, state, cut)
        return self._in_pits(last, state, cut, paused)

    def _teleported(self, last: RaceState, state: RaceState) -> bool:
        moved = math.hypot(state.pos_x - last.pos_x, state.pos_z - last.pos_z)
        if moved < self.teleport_m:
            return False
        # Time from the packet counter (60 a second) as well as the clock: packets
        # arrive in bursts, so two frames received 0.4 s apart can be 2 s of
        # driving apart (Suzuka East, 2026-10-15), which the clock alone reads
        # as a car doing 900 km/h.
        elapsed = max(state.t - last.t, (state.packet_id - last.packet_id) / PACKETS_PER_SEC)
        return elapsed <= 0 or moved / elapsed * 3.6 > self.teleport_kph

    def _enter(self, last: RaceState, state: RaceState, evidence: str) -> PitStatus:
        self._rested = False
        self._open = PitStop(
            number=len(self._stops) + 1,
            in_lap=last.current_lap,
            out_lap=None,
            entry_t=state.t,
            exit_t=None,
            stationary_secs=0.0,
            fuel_before=last.fuel_level,
            fuel_after=state.fuel_level,
            tyres_changed=False,
            pit_lane_kph=state.speed_kph,
            position_before=last.position,
            position_after=state.position,
            evidence=f"entry {evidence} at {state.speed_kph:.1f} km/h",
        )
        return self._publish()

    def _in_pits(
        self, last: RaceState, state: RaceState, cut: str | None, paused: bool
    ) -> PitStatus | None:
        stop = self._open
        assert stop is not None
        rest = stop.stationary_secs
        if state.speed_kph < self.rest_kph:
            self._rested = True
            if not paused:
                rest += min(max(state.t - last.t, 0.0), self.max_step)
        tyres = stop.tyres_changed or all(
            before - after > self.tyre_drop
            for before, after in zip(last.tire_temp, state.tire_temp, strict=True)
        )
        stop = replace(
            stop,
            stationary_secs=rest,
            fuel_after=state.fuel_level,
            tyres_changed=tyres,
            position_after=state.position,
        )
        self._open = stop
        out = None
        if cut is not None and self._rested and last.speed_kph >= self.moving_kph:
            out = f"exit {cut}"
        elif state.speed_kph > self.exit_kph:
            out = f"over {self.exit_kph:.0f} km/h"
        if out is None:
            self._status = PitStatus(True, (*self._stops, stop), tuple(self._teleports))
            return None
        self._open = None
        if not self._rested and not stop.tyres_changed and stop.fuel_added < self.refuel_min:
            self._teleports.append(
                Teleport(
                    lap=stop.in_lap,
                    t=state.t,
                    entry_t=stop.entry_t,
                    evidence=f"{stop.evidence}; {out}; never at rest, no fuel, no tyres",
                )
            )
            return self._publish()
        done = replace(stop, out_lap=state.current_lap, exit_t=state.t)
        done = replace(done, evidence=f"{done.evidence}; {out}")
        self._stops.append(done)
        return self._publish()

    def _publish(self) -> PitStatus:
        stops = tuple(self._stops) + ((self._open,) if self._open is not None else ())
        self._status = PitStatus(self._open is not None, stops, tuple(self._teleports))
        return self._status
