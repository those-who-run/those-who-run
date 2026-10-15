"""Speak each completed lap's time and its delta to the best lap.

A lap that beats the best so far is a "new best" and gets its own template and
priority; it replaces the plain lap-time phrase rather than adding a second one.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import RaceState, lap_time_posted
from those_who_run.verbalise import delta_words, lap_time_words, number_words, tidy_sentence


class LapTimeRule(Rule):
    name = "lap_time"
    default_priority = 20

    def reset(self) -> None:
        self.new_best_priority = int(self.cfg.get("new_best_priority", 11))
        self.last_announced_lap = 0
        self.own_best_ms = 0

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
        # GT7 does not count lap 1 of a race towards its best lap, so its best
        # is empty until lap 2 is done. Track our own best as a fallback so
        # the second lap still gets a delta against the first.
        prev_best = prev.best_lap_ms if prev.best_lap_ms > 0 else self.own_best_ms
        if self.own_best_ms <= 0 or state.last_lap_ms < self.own_best_ms:
            self.own_best_ms = state.last_lap_ms
        if prev_best <= 0:
            delta = self.template("delta_first", "")
        else:
            diff = state.last_lap_ms - prev_best
            if diff < 0:
                text = self.template(
                    "template_new_best", "Lap {lap}. {time}. New best by {gap}."
                ).format(
                    lap=number_words(lap_no),
                    time=time_words,
                    gap=delta_words(diff),
                    delta=self.template("delta_faster", "{delta} under best").format(
                        delta=delta_words(diff)
                    ),
                )
                return [self.callout(tidy_sentence(text), state, priority=self.new_best_priority)]
            if diff == 0:
                delta = self.template("delta_equal", "equal to best")
            else:
                delta = self.template("delta_slower", "{delta} over best").format(
                    delta=delta_words(diff)
                )

        text = self.template("template", "Lap {lap}. {time}. {delta}").format(
            lap=number_words(lap_no), time=time_words, delta=delta
        )
        return [self.callout(tidy_sentence(text), state)]
