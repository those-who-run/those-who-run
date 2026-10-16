"""Rule interface. Rules are pure: state in, callouts out, no I/O."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any

from those_who_run.callouts import Callout
from those_who_run.phrasing import Phrasebook
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
        self.reset()

    def reset(self) -> None:
        """Forget per-race state. Called on every race start."""
        return None

    def on_track(self, match: TrackMatch) -> None:
        """The engine's track verdict changed (never downgraded within a session)."""
        return None

    def on_session(self, kind: SessionKind) -> None:
        """The engine's session verdict changed: kind, fuel use or the cars-on-track flag."""
        return None

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
