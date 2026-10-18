"""``those-who-run record``: capture live telemetry to a JSONL file."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time
from pathlib import Path

from those_who_run.config import Settings
from those_who_run.state import RaceState

log = logging.getLogger("those_who_run")

HELP = "capture live telemetry to a JSONL file for later replay"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--ps5-ip", help="override GT7_PS5_IP; omit both to use broadcast discovery"
    )
    parser.add_argument(
        "--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(run_record(settings, args.output, args.ps5_ip, args.seconds))


async def run_record(settings: Settings, output: Path, ps5_ip: str | None, seconds: float) -> int:
    from those_who_run.replay import RecordingWriter
    from those_who_run.telemetry import LiveTelemetry

    ip = ps5_ip or settings.ps5_ip
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(ip, queue, loop, discover=ip is None)
    writer = RecordingWriter(output)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    telem.start()
    deadline = time.monotonic() + seconds if seconds > 0 else None
    log.info("recording to %s (Ctrl-C to stop)", output)
    try:
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            try:
                state = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            writer.write(state)
    finally:
        writer.close()
        await telem.stop()
        log.info("wrote %d states to %s", writer.count, output)
    return 0
