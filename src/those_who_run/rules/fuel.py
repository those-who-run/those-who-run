"""Estimate laps of fuel remaining and warn at configured thresholds.

Consumption is measured at each line crossing (fuel at lap start minus fuel at
lap end) and averaged over the last ``rolling_laps`` laps. Warnings are only
given when the estimate is shorter than the laps left in a lap-count race, or
covers them only just.

Pit stops come from the engine's pit detector (``those_who_run.pitstop``). The
in-lap and the out-lap are not measured: both include the pit lane at the
limiter, so they read light (the out-lap at Willow Springs used 13.3 against
14.1 to 15.9 for the laps before it, 2026-10-17) or, with the refuel inside
the lap, negative. A completed stop starts a new stint: the thresholds and the
pit call are armed again, and the estimate is redone from the new level at
once. A rise in fuel level over a lap still counts as a stop, for a stop the
detector did not see.

The estimate is spoken as whole laps, rounded up when it is within
``round_up_laps`` of the next one (2.99 is "just under three laps", not "two"),
and the thresholds and the pit calls go by that count too. The rolling average
reads heavy after a stop, from the last stint's laps (SUGO, 2026-10-18: 2.99
laps called "two" with three in the tank, #247).

The pit calls are the instruction that goes with the numbers, ahead of the
threshold phrase for the same crossing, each once per stint: "Box next lap."
when the count is ``pit_laps``, and "Pit this lap." once it is under it (the
lap after this one cannot be completed). The second comes even when the first
was given, so the lap the driver has to box is always called.

When the count covers the race, nothing is said, except once per stint when
the margin is under ``tight_margin_laps``: "Fuel to the flag, just." When fuel
was a worry this stint (a threshold, pit or critical call) and the estimate
covers the final lap, ``template_last_lap_enough`` is spoken as it starts.

A crossing in the pits says nothing: the tank is about to be filled, or has
just been. GT7 can put the line in any part of a stop: in the entry cut-scene
(Suzuka East), in the exit cut-scene (Willow Springs) or in the pit lane
itself (Circuit Gilles Villeneuve). A crossing seen through a loading screen
is one of the first two.

A crossing that falls inside a telemetry gap (no frames for more than
``max_gap_secs``, not a pause) is not measured, and neither is the lap after it:
the first frame back is seconds past the line, so the lap would read heavy and
the next one light (the pit call slipped a lap when only the first was
skipped). The level still moves the estimate on.
"""

from __future__ import annotations

import logging
import math
from collections import deque

from those_who_run.callouts import Callout
from those_who_run.pitstop import PitStatus
from those_who_run.rules.base import Rule
from those_who_run.state import Phase, RaceState, lap_completed
from those_who_run.verbalise import laps_words

log = logging.getLogger(__name__)


class FuelRule(Rule):
    name = "fuel"
    default_priority = 15

    def reset(self) -> None:
        self.thresholds: list[int] = sorted(
            {int(x) for x in self.cfg.get("thresholds_laps", [10, 5, 3, 2, 1])}, reverse=True
        )
        self.rolling = max(int(self.cfg.get("rolling_laps", 3)), 1)
        self.refuel_epsilon = float(self.cfg.get("refuel_epsilon", 0.5))
        self.critical_priority = int(self.cfg.get("critical_priority", 5))
        self.pit_window = bool(self.cfg.get("pit_window", True))
        self.pit_laps = float(self.cfg.get("pit_laps", 2.0))
        self.pit_priority = int(self.cfg.get("pit_priority", 5))
        self.pit_next_announced = False
        self.pit_announced = False
        self.round_up = float(self.cfg.get("round_up_laps", 0.25))
        self.tight_margin = float(self.cfg.get("tight_margin_laps", 0.5))
        self.tight_announced = False
        self.consumption: deque[float] = deque(maxlen=self.rolling)
        self.announced: set[int] = set()
        self.critical_announced = False
        self.lap_start_fuel: float | None = None
        self.laps_remaining: float | None = None
        self.pit_cut = False  # the crossing came through a loading screen
        self.bridged = False
        self.stint = 1
        self.skip_next = False  # the lap in progress started inside a telemetry gap
        self.partial = False  # the lap in progress was joined part way (#265)
        self.max_gap = float(self.cfg.get("max_gap_secs", 1.0))

    def on_bridge(self, phase: Phase) -> None:
        self.pit_cut = phase is Phase.LOADING
        self.bridged = True  # a pause or loading screen, not lost telemetry

    def on_pit(self, status: PitStatus) -> None:
        super().on_pit(status)
        if status.stint == self.stint:
            return
        self.stint = status.stint
        self._new_stint()
        if self.consumption:
            fuel = status.stops[-1].fuel_after
            self.laps_remaining = fuel / (sum(self.consumption) / len(self.consumption))

    def _new_stint(self) -> None:
        self.announced.clear()
        self.critical_announced = False
        self.pit_next_announced = False
        self.pit_announced = False
        self.tight_announced = False

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if self.lap_start_fuel is None and state.in_race and state.current_lap >= 1:
            self.lap_start_fuel = state.fuel_level
            self.partial = self.joined  # joined part way: the first lap is not a whole one
        pit_cut, self.pit_cut = self.pit_cut, False
        bridged, self.bridged = self.bridged, False
        if prev is None or not lap_completed(prev, state):
            return []
        assert self.lap_start_fuel is not None

        used = self.lap_start_fuel - state.fuel_level
        gap = not bridged and state.t - prev.t > self.max_gap
        skip, self.skip_next = self.skip_next, gap
        partial, self.partial = self.partial, False
        if partial and used >= -self.refuel_epsilon:
            log.info("fuel: lap %d was joined part way, not measured", prev.current_lap)
        elif gap and used >= -self.refuel_epsilon:
            log.info(
                "fuel: lap crossed inside a %.1f s telemetry gap, not measured", state.t - prev.t
            )
        elif skip and used >= -self.refuel_epsilon:
            log.info("fuel: lap started inside a telemetry gap, not measured")
        elif used < -self.refuel_epsilon:
            # Fuel went up: a pit stop happened during that lap.
            self._new_stint()
        elif self.pits.is_pit_lap(prev.current_lap):
            log.info("fuel: lap %d was in the pits, not measured", prev.current_lap)
        elif used > 0:
            self.consumption.append(used)
        self.lap_start_fuel = state.fuel_level

        if not self.consumption:
            return []
        avg = sum(self.consumption) / len(self.consumption)
        if avg <= 0:
            return []
        self.laps_remaining = state.fuel_level / avg

        if (
            pit_cut
            or self.pits.in_pit_lane
            or (state.has_lap_count and state.current_lap > state.total_laps)
        ):
            return []
        laps_left = state.laps_left
        whole = math.floor(self.laps_remaining + self.round_up)
        if laps_left is not None and whole >= laps_left:
            if not self.tight_announced and self.laps_remaining - laps_left < self.tight_margin:
                self.tight_announced = True
                text = self.template("template_tight", "Fuel to the flag, just. Save a little.")
                return [self.callout(text, state)]
            warned = bool(self.announced) or self.pit_announced or self.critical_announced
            if warned and laps_left == 1 and self.laps_remaining >= laps_left:
                text = self.template("template_last_lap_enough", "Fuel is fine to the end.")
                return [self.callout(text, state)]
            return []

        out: list[Callout] = []
        if self.pit_window and not self.pit_announced:
            if whole < self.pit_laps:
                self.pit_announced = self.pit_next_announced = True
                text = self.template("template_pit", "Pit this lap.")
                out.append(self.callout(text, state, priority=self.pit_priority))
            elif not self.pit_next_announced and whole < self.pit_laps + 1:
                self.pit_next_announced = True
                text = self.template("template_pit_next", "Box next lap.")
                out.append(self.callout(text, state, priority=self.pit_priority))

        if self.laps_remaining < 1:
            if not self.critical_announced:
                self.critical_announced = True
                self.announced.update(self.thresholds)
                text = self.template("template_critical", "Fuel critical. Less than one lap.")
                out.append(self.callout(text, state, priority=self.critical_priority))
            return out

        crossed = [t for t in self.thresholds if whole <= t and t not in self.announced]
        if crossed:
            self.announced.update(crossed)
            if whole > self.laps_remaining:
                text = self.template("template_short", "Fuel. Just under {laps}.")
            else:
                text = self.template("template", "Fuel. {laps} remaining.")
            out.append(self.callout(text.format(laps=laps_words(whole)), state))
        return out
