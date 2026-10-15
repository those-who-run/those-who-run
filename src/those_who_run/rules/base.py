"""Rule interface. Rules are pure: state in, callouts out, no I/O."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from those_who_run.callouts import Callout
from those_who_run.state import Phase, RaceState
from those_who_run.trackdetect import TrackMatch


class Rule(ABC):
    name: str = "rule"
    default_priority: int = 50

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg: dict[str, Any] = dict(cfg or {})
        self.priority: int = int(self.cfg.get("priority", self.default_priority))
        max_age = self.cfg.get("max_age_seconds")
        self.max_age: float | None = float(max_age) if max_age else None
        self.reset()

    def reset(self) -> None:
        """Forget per-race state. Called on every race start."""
        return None

    def on_track(self, match: TrackMatch) -> None:
        """The engine's track verdict changed (never downgraded within a session)."""
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
            text=text,
            priority=self.priority if priority is None else priority,
            rule=self.name,
            created_at=state.t,
            max_age=self.max_age,
        )

    def template(self, key: str, default: str) -> str:
        return str(self.cfg.get(key, default))
