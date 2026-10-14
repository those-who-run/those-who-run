"""Rule interface. Rules are pure: state in, callouts out, no I/O."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from gt7_race_engineer.callouts import Callout
from gt7_race_engineer.state import RaceState


class Rule(ABC):
    name: str = "rule"
    default_priority: int = 50

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg: dict[str, Any] = dict(cfg or {})
        self.priority: int = int(self.cfg.get("priority", self.default_priority))
        self.reset()

    def reset(self) -> None:
        """Forget per-race state. Called on every race start."""
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
        )

    def template(self, key: str, default: str) -> str:
        return str(self.cfg.get(key, default))
