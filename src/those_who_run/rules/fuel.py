"""Estimate laps of fuel remaining and warn at configured thresholds.

Consumption is measured at each line crossing (fuel at lap start minus fuel at
lap end) and averaged over the last ``rolling_laps`` laps. A rise in fuel level
is treated as a pit stop and clears the announced thresholds. Warnings are only
given when the estimate is shorter than the laps left in a lap-count race.

The pit call is the instruction that goes with the numbers: once the estimate
says the lap after this one cannot be completed, "Pit this lap." is spoken once
per stint, ahead of the threshold phrase for the same crossing.

A crossing seen through a loading screen is the car entering the pit lane (GT7
cuts to the pit scene as it crosses the line). The tank is about to be filled,
so that crossing only records consumption and says nothing.
"""

from __future__ import annotations

import math
from collections import deque

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import Phase, RaceState, lap_completed
from those_who_run.verbalise import laps_words


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
        self.pit_announced = False
        self.consumption: deque[float] = deque(maxlen=self.rolling)
        self.announced: set[int] = set()
        self.critical_announced = False
        self.lap_start_fuel: float | None = None
        self.laps_remaining: float | None = None
        self.entering_pits = False

    def on_bridge(self, phase: Phase) -> None:
        self.entering_pits = phase is Phase.LOADING

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if self.lap_start_fuel is None and state.in_race and state.current_lap >= 1:
            self.lap_start_fuel = state.fuel_level
        entering_pits, self.entering_pits = self.entering_pits, False
        if prev is None or not lap_completed(prev, state):
            return []
        assert self.lap_start_fuel is not None

        used = self.lap_start_fuel - state.fuel_level
        if used < -self.refuel_epsilon:
            # Fuel went up: a pit stop happened during that lap.
            self.announced.clear()
            self.critical_announced = False
            self.pit_announced = False
        elif used > 0:
            self.consumption.append(used)
        self.lap_start_fuel = state.fuel_level

        if not self.consumption:
            return []
        avg = sum(self.consumption) / len(self.consumption)
        if avg <= 0:
            return []
        self.laps_remaining = state.fuel_level / avg

        if entering_pits or (state.has_lap_count and state.current_lap > state.total_laps):
            return []
        laps_left = state.laps_left
        if laps_left is not None and self.laps_remaining >= laps_left:
            return []

        out: list[Callout] = []
        if self.pit_window and not self.pit_announced and self.laps_remaining < self.pit_laps:
            self.pit_announced = True
            text = self.template("template_pit", "Pit this lap.")
            out.append(self.callout(text, state, priority=self.pit_priority))

        whole = math.floor(self.laps_remaining)
        if whole < 1:
            if not self.critical_announced:
                self.critical_announced = True
                self.announced.update(self.thresholds)
                text = self.template("template_critical", "Fuel critical. Less than one lap.")
                out.append(self.callout(text, state, priority=self.critical_priority))
            return out

        crossed = [
            t for t in self.thresholds if self.laps_remaining <= t and t not in self.announced
        ]
        if crossed:
            self.announced.update(crossed)
            text = self.template("template", "Fuel. {laps} remaining.").format(
                laps=laps_words(whole)
            )
            out.append(self.callout(text, state))
        return out
