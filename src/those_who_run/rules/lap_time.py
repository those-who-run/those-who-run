"""Speak each completed lap's time and its delta to the best lap.

The best lap is GT7's own once it has one. In a lap-count race GT7 ignores lap 1
(the grid sits ahead of the line, so the lap is short: 57.1 s against 60 s laps at
Suzuka East, 2026-10-15), and so does the fallback kept here; a timed race or a
time trial counts lap 1. Laps within ``equal_ms`` of the best are "equal", so
identical time-trial laps are not called a new best by zero point zero.

Situational pools, used when configured: ``delta_slower_small`` (under
``small_delta_ms``), ``delta_slower_large`` (over ``large_delta_ms``) and
``template_new_best_small`` (a gap under ``small_gap_ms``).

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
        self.equal_ms = int(self.cfg.get("equal_ms", 50))
        self.small_delta_ms = int(self.cfg.get("small_delta_ms", 300))
        self.large_delta_ms = int(self.cfg.get("large_delta_ms", 2000))
        self.small_gap_ms = int(self.cfg.get("small_gap_ms", 200))

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
        prev_best = prev.best_lap_ms if prev.best_lap_ms > 0 else self.own_best_ms
        counts = not (state.has_lap_count and lap_no == 1)
        if counts and (self.own_best_ms <= 0 or state.last_lap_ms < self.own_best_ms):
            self.own_best_ms = state.last_lap_ms
        if prev_best <= 0:
            delta = self.template("delta_first", "")
        else:
            diff = state.last_lap_ms - prev_best
            if abs(diff) < self.equal_ms:
                diff = 0
            if diff < 0:
                keys = ["template_new_best"]
                if -diff < self.small_gap_ms:
                    keys.insert(0, "template_new_best_small")
                text = self.first_template(keys, "Lap {lap}. {time}. New best by {gap}.").format(
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
                keys = ["delta_slower"]
                if diff < self.small_delta_ms:
                    keys.insert(0, "delta_slower_small")
                elif diff > self.large_delta_ms:
                    keys.insert(0, "delta_slower_large")
                delta = self.first_template(keys, "{delta} over best").format(
                    delta=delta_words(diff)
                )

        text = self.template("template", "Lap {lap}. {time}. {delta}").format(
            lap=number_words(lap_no), time=time_words, delta=delta
        )
        return [self.callout(tidy_sentence(text), state)]
