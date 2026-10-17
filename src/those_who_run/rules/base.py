"""Rule interface. Rules are pure: state in, callouts out, no I/O."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any

from those_who_run.callouts import Callout
from those_who_run.phrasing import Phrasebook
from those_who_run.pitstop import NO_STOPS, PitStatus
from those_who_run.sessionkind import SessionKind
from those_who_run.state import Phase, RaceState
from those_who_run.trackdetect import TrackMatch
from those_who_run.verbalise import tidy_sentence


class Rule(ABC):
    name: str = "rule"
    default_priority: int = 50

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg: dict[str, Any] = dict(cfg or {})
        self.priority: int = int(self.cfg.get("priority", self.default_priority))
        max_age = self.cfg.get("max_age_seconds")
        self.max_age: float | None = float(max_age) if max_age else None
        self.phrases = Phrasebook(self.cfg, random.Random())
        self.session: SessionKind | None = None  # the engine's verdict, see on_session
        self.pits: PitStatus = NO_STOPS  # the engine's pit detector, see on_pit
        self.reset()

    def reset(self) -> None:
        """Forget per-race state. Called on every race start."""
        return None

    def on_track(self, match: TrackMatch) -> None:
        """The engine's track verdict changed (never downgraded within a session)."""
        return None

    def on_session(self, kind: SessionKind) -> None:
        """The engine's session verdict changed: kind, fuel use, start or the cars-on-track
        flag. Kept on ``self.session``; overrides should call this."""
        self.session = kind

    def on_pit(self, status: PitStatus) -> None:
        """The car entered or left the pit lane: called once on the entry and once on
        the exit, not on the frames between. Kept on ``self.pits``, so
        ``self.pits.in_pit_lane`` holds for the whole stop, but the open stop's
        figures (fuel, time at rest, tyres) are as they were at the entry.
        Overrides should call this."""
        self.pits = status

    def on_end(self, last: RaceState, state: RaceState) -> list[Callout]:
        """The session ended without a chequered flag (quit, or back to the menu).
        ``last`` is the last driving frame. Callouts returned are queued."""
        return []

    def on_finish(self, state: RaceState) -> list[Callout]:
        """A timed race was finished at this crossing (lap races finish on the
        FINISHED frame, which evaluate() sees). Callouts returned are queued."""
        return []

    def has_field(self, state: RaceState) -> bool:
        """Other cars are racing for position, as far as we can be sure: GT7 flags
        cars on track and the session kind (once known) has a field. A time
        trial's ghost is flagged but no field; the races GT7 never flags
        (2026-10-15, a mode still to be named) have a field but no flag, and
        stay quiet about places until we know what they are."""
        if self.session is not None and self.session.kind != "unknown":
            return self.session.field and self.session.cars_on_track
        return state.is_race and state.total_cars > 1

    def on_bridge(self, phase: Phase) -> None:
        """The next evaluate() is compared against the last driving frame, across a
        run of ``phase`` frames (a pause, or a loading screen such as the pit lane)."""
        return None

    @abstractmethod
    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        """Return callouts for this frame. Only called while in a race."""

    def callout(self, text: str, state: RaceState, priority: int | None = None) -> Callout:
        return Callout(
            text=tidy_sentence(text),
            priority=self.priority if priority is None else priority,
            rule=self.name,
            created_at=state.t,
            max_age=self.max_age,
        )

    def template(self, key: str, default: str) -> str:
        """The template for ``key``, or one of its variants when it is a list."""
        return self.phrases.pick(key, default)

    def first_template(self, keys: list[str], default: str) -> str:
        """The first of ``keys`` that is configured, so a situational pool such as
        ``template_gained_lead`` can stand in for the general one."""
        return self.phrases.first(keys, default)
