"""``those-who-run replay``: run the rules over a recording, no PS5 or Discord."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from those_who_run.config import Settings

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


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(
        run_replay(settings, args.recording, args.wav_out, args.realtime, args.store)
    )


async def run_replay(
    settings: Settings,
    recording: Path,
    wav_out: Path | None,
    realtime: bool,
    store_dir: Path | None = None,
) -> int:
    """Replay a recording. Sessions in it go to ``store_dir``, or to a temporary
    directory thrown away afterwards: never into ``GT7_DATA_DIR`` (the pit wall
    and the results history only ever see real drives) unless named here, and
    then only while the engineer is stopped (the store's writer lock)."""
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
        store = SessionStore(store_dir or Path(tmp))
        engine = Engine(build_rules(rules_cfg["rules"]), queue, store)
        try:
            spoken = await replay(read_recording(recording), engine, player, realtime=realtime)
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
