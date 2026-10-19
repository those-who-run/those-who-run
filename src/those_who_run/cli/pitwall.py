"""``those-who-run pitwall``: the pit wall's data API and web app (#236)."""

from __future__ import annotations

import argparse
from pathlib import Path

from those_who_run.config import ConfigError, Settings

HELP = "the pit wall's read-only data API over GT7_DATA_DIR, and the web app with --static"
SETTINGS: tuple[str, ...] = ("GT7_PITWALL_PORT",)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port", type=int, default=None, help="port to listen on (GT7_PITWALL_PORT, default 9852)"
    )
    parser.add_argument(
        "--address", default="0.0.0.0", help="address to listen on (default all, for a container)"
    )
    parser.add_argument(
        "--static",
        type=Path,
        default=None,
        metavar="DIR",
        help="serve the built web app from DIR (web/dist), index.html for client routes",
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.pitwall import server

    if args.static is not None and not (args.static / "index.html").is_file():
        raise ConfigError(f"--static {args.static} has no index.html: build the web app first")
    return server.run(
        settings.data_dir,
        host=args.address,
        port=args.port or settings.pitwall_port,
        engineer_url=settings.engineer_url,
        control_url=settings.engineer_control_url,
        static_dir=args.static,
    )
