"""Record RaceState streams to JSONL and play them back through the engine."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from those_who_run.audio.player import Player
from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.engine import Engine
from those_who_run.state import RaceState

log = logging.getLogger(__name__)


def write_recording(path: Path, states: Iterable[RaceState]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for state in states:
            fh.write(json.dumps(state.to_dict(), separators=(",", ":")))
            fh.write("\n")
            n += 1
    return n


class RecordingWriter:
    """Append-only JSONL writer used by the ``record`` command."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        self.count = 0

    def write(self, state: RaceState) -> None:
        self._fh.write(json.dumps(state.to_dict(), separators=(",", ":")))
        self._fh.write("\n")
        self.count += 1
        if self.count % 600 == 0:
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def read_recording(path: Path) -> Iterator[RaceState]:
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield RaceState.from_dict(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{path}:{line_no}: bad state record: {exc}") from exc


async def replay(
    states: Iterable[RaceState],
    engine: Engine,
    player: Player,
    realtime: bool = False,
) -> list[Callout]:
    """Drive the engine with recorded states, speaking through ``player``.

    Staleness is driven by recorded time, so the queue is drained after every
    frame; with ``realtime`` the replay also sleeps to match the recording.
    """
    spoken: list[Callout] = []
    last_t: float | None = None
    for state in states:
        if realtime and last_t is not None and state.t > last_t:
            await asyncio.sleep(min(state.t - last_t, 1.0))
        last_t = state.t
        engine.process(state)
        await player.on_phase(state.phase, state.t)
        while (c := engine.queue.pop(state.t)) is not None:
            await player.play(c)
            spoken.append(c)
    return spoken


def summarise(spoken: list[Callout], queue: CalloutQueue) -> dict[str, Any]:
    by_rule: dict[str, int] = {}
    for c in spoken:
        by_rule[c.rule] = by_rule.get(c.rule, 0) + 1
    return {"spoken": len(spoken), "dropped": queue.dropped, "by_rule": by_rule}
