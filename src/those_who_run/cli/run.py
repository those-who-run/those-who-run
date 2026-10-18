"""``those-who-run run``: the live engineer, PS5 telemetry in, Discord voice out.
The engineer itself is :class:`those_who_run.app.App`."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from those_who_run.config import Settings

HELP = "live: PS5 telemetry in, Discord voice out"
SETTINGS: tuple[str, ...] = Settings.PARSED


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record", type=Path, help="also append every telemetry frame to this JSONL file"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.app import App

    return asyncio.run(App(settings, record=args.record).run())
