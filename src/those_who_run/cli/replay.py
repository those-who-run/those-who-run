"""``those-who-run replay``: run the rules over a recording, no PS5 or Discord."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from those_who_run.config import Settings

if TYPE_CHECKING:
    from those_who_run.state import RaceState

log = logging.getLogger("those_who_run")

HELP = "run the rules over a recording, no PS5 or Discord needed"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("recording", type=Path)
    parser.add_argument(
        "--wav-out", type=Path, help="also synthesise each callout into this directory"
    )
    parser.add_argument(
        "--realtime", action="store_true", help="sleep to match the recording's timing"
    )
    parser.add_argument(
        "--store",
        type=Path,
        help="keep the sessions found in this directory (default: a temporary one, thrown away;"
        " never GT7_DATA_DIR unless named here)",
    )
    parser.add_argument(
        "--clock",
        type=clock_start,
        metavar="TIME",
        help="date the stored sessions from TIME (ISO 8601, UTC unless it says, or epoch"
        " seconds) plus the recording's own time, not the wall clock: the same store on"
        " every run",
    )


def clock_start(text: str) -> float:
    """``--clock``'s value as epoch seconds: a number, or an ISO 8601 time (UTC
    unless it carries an offset)."""
    try:
        return float(text)
    except ValueError:
        pass
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a time: {text!r}") from None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


class RecordingClock:
    """A clock that starts at ``start`` on the first frame and moves with the
    frames' own times, for the store in place of the wall clock (``--clock``)."""

    def __init__(self, start: float) -> None:
        self.start = start
        self.now = start
        self._t0: float | None = None

    def __call__(self) -> float:
        return self.now

    def follow(self, states: Iterable[RaceState]) -> Iterator[RaceState]:
        for state in states:
            if self._t0 is None:
                self._t0 = state.t
            self.now = self.start + (state.t - self._t0)
            yield state


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(
        run_replay(settings, args.recording, args.wav_out, args.realtime, args.store, args.clock)
    )


async def run_replay(
    settings: Settings,
    recording: Path,
    wav_out: Path | None,
    realtime: bool,
    store_dir: Path | None = None,
    clock: float | None = None,
) -> int:
    """Replay a recording. Sessions in it go to ``store_dir``, or to a temporary
    directory thrown away afterwards: never into ``GT7_DATA_DIR`` (the pit wall
    and the results history only ever see real drives) unless named here, and
    then only while the engineer is stopped (the store's writer lock). With
    ``clock``, the store's times start there and follow the recording."""
    import tempfile

    # Here, not at the top: the engine reaches prometheus_client, which the slim
    # pit wall image (#237) does not install, and it loads every command module.
    from those_who_run.audio.player import ConsolePlayer, WavDirPlayer
    from those_who_run.callouts import CalloutQueue
    from those_who_run.config import load_rules_config
    from those_who_run.engine import Engine
    from those_who_run.replay import read_recording, replay, summarise
    from those_who_run.rules import build_rules
    from those_who_run.store import SessionStore

    rules_cfg = load_rules_config(settings.rules_file)
    queue = CalloutQueue(max_age=None)
    if wav_out is not None:
        from those_who_run.speech import PiperSpeech

        speech = PiperSpeech(settings.require_voice_model(), wav_out / ".cache", rules_cfg["voice"])
        player: ConsolePlayer = WavDirPlayer(speech, wav_out)
    else:
        player = ConsolePlayer()
    with tempfile.TemporaryDirectory(prefix="those-who-run-replay-") as tmp:
        frames: Iterable[RaceState] = read_recording(recording)
        if clock is None:
            store = SessionStore(store_dir or Path(tmp))
        else:
            recording_clock = RecordingClock(clock)
            frames = recording_clock.follow(frames)
            store = SessionStore(store_dir or Path(tmp), clock=recording_clock)
        engine = Engine(build_rules(rules_cfg["rules"]), queue, store)
        try:
            spoken = await replay(frames, engine, player, realtime=realtime)
        finally:
            try:
                # A session still open when the recording stops is ended, so the
                # store is complete: every session has its summary.json.
                engine.close_session()
            finally:
                store.close()
    log.info("replay summary: %s", summarise(spoken, queue))
    if store_dir is not None:
        log.info("sessions stored in %s", store_dir)
    return 0
