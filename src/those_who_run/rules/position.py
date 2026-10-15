"""Announce gained and lost places.

GT7 updates the position field live. Places change in bursts at the start
and through traffic, so a change is held for ``settle_secs`` and the latest
position is spoken once things calm down, rather than every swap. The first
``start_grace_secs`` of a race are quiet apart from that settling: the start
brief has just given the grid slot, and the field shuffles for a while (nine
calls in the first minute at Suzuka East, 2026-10-15). The first call after the
grace compares with the grid slot.

Situational pools, used when configured: ``template_gained_lead`` (into first),
``template_gained_podium`` (into second or third), ``template_lost_lead``.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import RaceState
from those_who_run.verbalise import number_words, ordinal_words


class PositionRule(Rule):
    name = "position"
    default_priority = 12

    def reset(self) -> None:
        self.settle_secs = float(self.cfg.get("settle_secs", 3.0))
        self.min_interval = float(self.cfg.get("min_interval_secs", 10.0))
        self.grace = float(self.cfg.get("start_grace_secs", 15.0))
        self.announced: int | None = None
        self.started_at: float | None = None
        self.pending_since: float | None = None
        self.last_spoken_at: float | None = None

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if not state.in_race or not state.is_race:
            return []
        pos = state.position
        if pos is None:
            return []
        if self.started_at is None:
            self.started_at = state.t
        if self.announced is None or state.t - self.started_at < self.settle_secs:
            # The grid slot takes a moment to settle: qualifying reported P20 on the
            # first driving frame and P1 on the next (2026-10-14). Follow it quietly.
            self.announced = pos
            return []
        if state.t - self.started_at < self.grace:
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
        was = self.announced
        self.announced = pos
        self.pending_since = None
        self.last_spoken_at = state.t
        if gained:
            keys = ["template_gained"]
            if pos == 1:
                keys.insert(0, "template_gained_lead")
            elif pos <= 3:
                keys.insert(0, "template_gained_podium")
            default = "Up to {position}."
        else:
            keys = ["template_lost"]
            if was == 1:
                keys.insert(0, "template_lost_lead")
            default = "Down to {position}."
        text = self.first_template(keys, default).format(
            position=ordinal_words(pos), p=number_words(pos)
        )
        return [self.callout(text, state)]
