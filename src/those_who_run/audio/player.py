"""Player interface plus the two offline implementations used by replay and tests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from those_who_run.callouts import Callout
from those_who_run.speech import Speech
from those_who_run.state import Phase

log = logging.getLogger(__name__)


class Player(Protocol):
    async def play(self, callout: Callout) -> None: ...

    async def on_phase(self, phase: Phase, now: float) -> None: ...

    async def close(self) -> None: ...


class ConsolePlayer:
    """Prints callouts. Used by replay and tests."""

    def __init__(self) -> None:
        self.spoken: list[Callout] = []

    async def play(self, callout: Callout) -> None:
        self.spoken.append(callout)
        print(f"[{callout.created_at:9.2f}s] ({callout.rule}) {callout.text}", flush=True)

    async def on_phase(self, phase: Phase, now: float) -> None:
        return None

    async def close(self) -> None:
        return None


class WavDirPlayer(ConsolePlayer):
    """Synthesises every callout into numbered WAV files for listening offline."""

    def __init__(self, speech: Speech, out_dir: Path) -> None:
        super().__init__()
        self.speech = speech
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def play(self, callout: Callout) -> None:
        await super().play(callout)
        src = self.speech.synthesize(callout.text)
        dst = self.out_dir / f"{len(self.spoken):03d}-{callout.rule}.wav"
        dst.write_bytes(src.read_bytes())
