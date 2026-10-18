"""Callouts and the priority queue that feeds the speaker."""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Callout:
    text: str
    priority: int  # lower is more urgent
    rule: str
    created_at: float  # seconds on the same clock as RaceState.t
    max_age: float | None = None  # overrides the queue's staleness limit for this callout
    hold: float = 0.0  # not spoken until this long after created_at, see CalloutQueue

    @property
    def due_at(self) -> float:
        return self.created_at + self.hold


class CalloutQueue:
    """Priority queue with staleness. Lower priority value speaks first; ties by age.

    ``max_age`` of None disables staleness, which replay mode uses so every
    callout from a recording is emitted. A callout's own ``max_age`` replaces the
    queue's limit, so a summary that waits behind the final lap time survives.

    A callout with a ``hold`` waits in the queue until it is due, and more urgent
    callouts that are due go ahead of it. While it waits it can still be taken
    back (``remove``): a position call held for a second is dropped when the pit
    entry is seen in that second (the engine, #244).
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
        """Return the most urgent fresh callout that is due, discarding stale ones on
        the way. Callouts still held stay queued."""
        waiting = []
        found = None
        while self._heap:
            item = heapq.heappop(self._heap)
            callout = item[3]
            limit = self.max_age if callout.max_age is None else callout.max_age
            if self.max_age is not None and limit is not None and now - callout.created_at > limit:
                self.dropped += 1
                continue
            if callout.due_at > now:
                waiting.append(item)
                continue
            found = callout
            break
        for item in waiting:
            heapq.heappush(self._heap, item)
        return found

    def remove(self, match: Callable[[Callout], bool]) -> list[Callout]:
        """Take the queued callouts ``match`` picks out of the queue, oldest first."""
        taken = sorted((item for item in self._heap if match(item[3])), key=lambda i: i[1:3])
        if taken:
            self._heap = [item for item in self._heap if not match(item[3])]
            heapq.heapify(self._heap)
        return [item[3] for item in taken]

    def clear(self) -> int:
        n = len(self._heap)
        self._heap.clear()
        return n
