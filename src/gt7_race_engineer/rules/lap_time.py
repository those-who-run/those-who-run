"""Speak each completed lap's time and its delta to the best lap."""

from __future__ import annotations

from gt7_race_engineer.callouts import Callout
from gt7_race_engineer.rules.base import Rule
from gt7_race_engineer.state import RaceState, lap_time_posted
from gt7_race_engineer.verbalise import delta_words, lap_time_words, number_words


class LapTimeRule(Rule):
    name = "lap_time"
    default_priority = 20

    def reset(self) -> None:
        self.last_announced_lap = 0

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if not lap_time_posted(prev, state):
            return []
        assert prev is not None
        # The posted time belongs to the lap that just finished. GT7 bumps the lap
        # counter on the same crossing, so the completed lap is one behind, unless
        # the counter has not moved yet in this frame.
        lap_no = state.current_lap - 1 if state.current_lap > prev.current_lap else prev.current_lap
        lap_no = max(lap_no, 1)
        if lap_no <= self.last_announced_lap:
            return []
        self.last_announced_lap = lap_no

        time_words = lap_time_words(state.last_lap_ms)
        prev_best = prev.best_lap_ms
        if prev_best <= 0:
            delta = self.template("delta_first", "")
        else:
            diff = state.last_lap_ms - prev_best
            if diff < 0:
                delta = self.template("delta_faster", "{delta} under best").format(
                    delta=delta_words(diff)
                )
            elif diff == 0:
                delta = self.template("delta_equal", "equal to best")
            else:
                delta = self.template("delta_slower", "{delta} over best").format(
                    delta=delta_words(diff)
                )

        text = self.template("template", "Lap {lap}. {time}. {delta}").format(
            lap=number_words(lap_no), time=time_words, delta=delta
        )
        return [self.callout(_tidy(text), state)]


def _tidy(text: str) -> str:
    text = " ".join(text.split())
    return text.rstrip(" ,.") + "."
