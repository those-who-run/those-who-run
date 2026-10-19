"""``those-who-run healthcheck``: the container's HEALTHCHECK (see
:mod:`those_who_run.healthcheck`)."""

from __future__ import annotations

import argparse

from those_who_run.config import Settings

HELP = "exit 0 when the engineer or pit wall in this container answers"
SETTINGS: tuple[str, ...] = ("GT7_METRICS_PORT", "GT7_PITWALL_PORT")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=["run", "pitwall"],
        default=None,
        help="which to probe (default: the mode of PID 1, or either)",
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="seconds per probe (default 2)")


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.healthcheck import run_healthcheck

    return run_healthcheck(settings, args.mode, args.timeout)
