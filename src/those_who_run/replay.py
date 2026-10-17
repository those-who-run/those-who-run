"""Record RaceState streams to JSONL (plain or gzip) and play them back through the engine."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO

from those_who_run.audio.player import Player
from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.engine import Engine
from those_who_run.state import Phase, RaceState

log = logging.getLogger(__name__)


def _open(path: Path, mode: str) -> TextIO:
    """Text file, gzip-compressed when the name ends in .gz (60 Hz frames shrink ~10x)."""
    if str(path).endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")  # type: ignore[return-value]
    return open(path, mode, encoding="utf-8")  # noqa: SIM115


def write_recording(path: Path, states: Iterable[RaceState]) -> int:
    n = 0
    with _open(path, "w") as fh:
        for state in states:
            fh.write(json.dumps(state.to_dict(), separators=(",", ":")))
            fh.write("\n")
            n += 1
    return n


class RecordingWriter:
    """Append-only JSONL writer used by the ``record`` command."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fh = _open(self.path, "a")
        self.count = 0

    def write(self, state: RaceState) -> None:
        self._fh.write(json.dumps(state.to_dict(), separators=(",", ":")))
        self._fh.write("\n")
        self.count += 1
        if self.count % 600 == 0:
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class OutingRecorder:
    """One gzipped recording per outing in a directory, oldest files pruned.

    A file opens on the first frame that is not a menu (the last menu frame
    seen is written first, so a replay starts from a known state) and closes on
    the next menu frame. Loading screens and the track screen between races
    stay inside the same outing. The newest ``keep`` files are kept.
    """

    def __init__(self, directory: Path, keep: int = 20, clock: Any = time.time) -> None:
        self.directory = Path(directory)
        self.keep = keep
        self.clock = clock
        self.path: Path | None = None
        self.count = 0  # frames written, all outings
        self.outings = 0
        self._writer: RecordingWriter | None = None
        self._last_menu: RaceState | None = None

    def write(self, state: RaceState) -> None:
        if state.phase is Phase.MENU:
            self._last_menu = state
            if self._writer is not None:
                self._write(state)
                self.close()
            return
        if self._writer is None:
            self._start()
            if self._last_menu is not None:
                self._write(self._last_menu)
        self._write(state)

    def _write(self, state: RaceState) -> None:
        assert self._writer is not None
        self._writer.write(state)
        self.count += 1

    def _start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock()))  # UTC, like session ids
        self.path = self.directory / f"{stamp}.jsonl.gz"
        self._writer = RecordingWriter(self.path)
        self.outings += 1
        log.info("recording outing to %s", self.path)
        if self.keep > 0:
            for old in sorted(self.directory.glob("*.jsonl.gz"))[: -self.keep]:
                log.info("pruning old recording %s", old.name)
                old.unlink(missing_ok=True)

    def close(self) -> None:
        if self._writer is None:
            return
        n = self._writer.count
        self._writer.close()
        self._writer = None
        log.info("outing recorded: %d frames in %s", n, self.path)


TRACKED_FIELDS = (
    "phase",
    "current_lap",
    "total_laps",
    "race_start_pos",
    "total_cars",
    "cars_on_track",
    "best_lap_ms",
    "last_lap_ms",
)


def thin(
    states: Iterable[RaceState],
    every: float = 0.5,
    start: float | None = None,
    end: float | None = None,
    tracked: tuple[str, ...] = TRACKED_FIELDS,
) -> Iterator[RaceState]:
    """Cut a 60 Hz recording down to a fixture: every frame where a tracked field
    changed, the frame before and after it, and one frame per ``every`` seconds.
    ``start`` and ``end`` are offsets in seconds from the first frame."""
    prev: RaceState | None = None
    prev_kept = False
    keep_next = False
    last_kept_t: float | None = None
    t0: float | None = None
    for state in states:
        if t0 is None:
            t0 = state.t
        offset = state.t - t0
        if end is not None and offset > end:
            break
        changed = prev is not None and any(getattr(prev, f) != getattr(state, f) for f in tracked)
        keep = (start is None or offset >= start) and (
            changed or keep_next or last_kept_t is None or state.t - last_kept_t >= every
        )
        if keep and changed and prev is not None and not prev_kept:  # noqa: SIM102
            if start is None or prev.t - t0 >= start:
                yield prev  # the frame before the change
        if keep:
            yield state
            last_kept_t = state.t
        keep_next = changed
        prev, prev_kept = state, keep


def read_recording(path: Path) -> Iterator[RaceState]:
    with _open(path, "r") as fh:
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
