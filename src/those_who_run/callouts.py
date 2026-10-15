"""Callouts and the priority queue that feeds the speaker."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Callout:
    text: str
    priority: int  # lower is more urgent
    rule: str
    created_at: float  # seconds on the same clock as RaceState.t
    max_age: float | None = None  # overrides the queue's staleness limit for this callout


class CalloutQueue:
    """Priority queue with staleness. Lower priority value speaks first; ties by age.

    ``max_age`` of None disables staleness, which replay mode uses so every
    callout from a recording is emitted. A callout's own ``max_age`` replaces the
    queue's limit, so a summary that waits behind the final lap time survives.
    """

    def __init__(self, max_age: float | None = 8.0) -> None:
        self.max_age = max_age
        self._heap: list[tuple[int, float, int, Callout]] = []
        self._seq = itertools.count()
        self.dropped = 0
        self.pushed = 0

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, callout: Callout) -> None:
        heapq.heappush(self._heap, (callout.priority, callout.created_at, next(self._seq), callout))
        self.pushed += 1

    def pop(self, now: float) -> Callout | None:
        """Return the most urgent fresh callout, discarding stale ones on the way."""
        while self._heap:
            _, _, _, callout = heapq.heappop(self._heap)
            limit = self.max_age if callout.max_age is None else callout.max_age
            if self.max_age is not None and now - callout.created_at > limit:
                self.dropped += 1
                continue
            return callout
        return None

    def clear(self) -> int:
        n = len(self._heap)
        self._heap.clear()
        return n
