"""Announce the start of the last lap in lap-count races."""

from __future__ import annotations

from gt7_race_engineer.callouts import Callout
from gt7_race_engineer.rules.base import Rule
from gt7_race_engineer.state import RaceState, lap_completed


class FinalLapRule(Rule):
    name = "final_lap"
    default_priority = 10

    def reset(self) -> None:
        self.announced = False

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if self.announced or not state.has_lap_count:
            return []
        if not lap_completed(prev, state) or state.current_lap != state.total_laps:
            return []
        self.announced = True
        return [self.callout(self.template("template", "Final lap."), state)]
