"""Announce gained and lost places.

GT7 updates the position field live. Places change in bursts at the start
and through traffic, so a change is held for ``settle_secs`` and the latest
position is spoken once things calm down, rather than every swap.
"""

from __future__ import annotations

from gt7_race_engineer.callouts import Callout
from gt7_race_engineer.rules.base import Rule
from gt7_race_engineer.state import RaceState
from gt7_race_engineer.verbalise import ordinal_words


class PositionRule(Rule):
    name = "position"
    default_priority = 12

    def reset(self) -> None:
        self.settle_secs = float(self.cfg.get("settle_secs", 2.0))
        self.min_interval = float(self.cfg.get("min_interval_secs", 5.0))
        self.announced: int | None = None
        self.pending_since: float | None = None
        self.last_spoken_at: float | None = None

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if not state.in_race or not state.is_race:
            return []
        pos = state.position
        if pos is None:
            return []
        if self.announced is None:
            # First position seen this race is the grid slot; nothing to say yet.
            self.announced = pos
            return []
        if pos == self.announced:
            self.pending_since = None
            return []
        if self.pending_since is None:
            self.pending_since = state.t
        if state.t - self.pending_since < self.settle_secs:
            return []
        if self.last_spoken_at is not None and state.t - self.last_spoken_at < self.min_interval:
            return []
        gained = pos < self.announced
        self.announced = pos
        self.pending_since = None
        self.last_spoken_at = state.t
        key = "template_gained" if gained else "template_lost"
        default = "Up to {position}." if gained else "Down to {position}."
        text = self.template(key, default).format(position=ordinal_words(pos), p=pos)
        return [self.callout(text, state)]
