"""The command line: one module per command, registered in ``COMMANDS``.

A command module has ``HELP`` (its line in ``--help``), ``SETTINGS`` (the
parsed environment variables it reads), ``configure(parser)`` to add its
arguments and ``run(args, settings)`` returning the exit code. Heavy optional
imports (Discord, Piper, Streamlit, gt-telem) stay inside ``run``, so a command
loads only what it uses.
"""

from __future__ import annotations

import argparse
import errno
import logging
import sys
from typing import Protocol

from those_who_run import __version__, brand
from those_who_run.cli import (
    cars,
    healthcheck,
    post,
    rebuild_best,
    record,
    recordings,
    replay,
    run,
    say,
    thin,
    tracks,
    web,
)
from those_who_run.config import ConfigError, Settings
from those_who_run.store import StoreBusy

log = logging.getLogger("those_who_run")


class Command(Protocol):
    HELP: str
    SETTINGS: tuple[str, ...]

    def configure(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace, settings: Settings) -> int: ...


# Every command, in the order ``--help`` lists them.
COMMANDS: dict[str, Command] = {
    "run": run,
    "say": say,
    "replay": replay,
    "record": record,
    "thin": thin,
    "tracks": tracks,
    "cars": cars,
    "recordings": recordings,
    "post": post,
    "rebuild-best": rebuild_best,
    "web": web,
    "healthcheck": healthcheck,
}

# The parsed environment variables each command reads. An invalid value in any
# other variable does not stop the command. LOG_LEVEL is checked for all.
SETTINGS_USED: dict[str, tuple[str, ...]] = {
    name: command.SETTINGS for name, command in COMMANDS.items() if command.SETTINGS
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="those-who-run", description=f"{brand.NAME} {brand.KANJI}: {brand.TAGLINE}."
    )
    p.add_argument("--version", action="version", version=brand.banner(__version__))
    sub = p.add_subparsers(dest="command", required=True)
    for name, command in COMMANDS.items():
        command.configure(sub.add_parser(name, help=command.HELP))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env(check=("LOG_LEVEL", *SETTINGS_USED.get(args.command, ())))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)  # logging is not set up yet
        return 2
    logging.basicConfig(
        level=logging.getLevelNamesMapping()[settings.log_level],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        return dispatch(args, settings)
    except StoreBusy as exc:  # another process holds the data directory's writer lock
        print(f"those-who-run {args.command}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        known = known_failure(exc)
        if known is None:
            raise
        message, code = known
        log.error("%s", message)
        # One line for the user; the traceback stays one LOG_LEVEL=DEBUG away,
        # so a bug that happens to raise one of these is not hidden for good.
        log.debug("traceback for the error above", exc_info=exc)
        return code


def dispatch(args: argparse.Namespace, settings: Settings) -> int:
    return COMMANDS[args.command].run(args, settings)


def known_failure(exc: BaseException) -> tuple[str, int] | None:
    """A one-line message and exit code for a failure the user can fix, or
    None for a bug, which keeps its traceback. Exit 2 is configuration."""
    if isinstance(exc, ConfigError):
        return f"configuration error: {exc}", 2
    try:
        import discord
    except ImportError:  # pragma: no cover - a core dependency
        discord = None  # type: ignore[assignment]
    if discord is not None and isinstance(exc, discord.LoginFailure):
        return f"Discord rejected DISCORD_BOT_TOKEN: {exc}", 2
    try:
        from gt_telem.errors.playstation_errors import (
            PlayStationNotFoundError,
            PlayStationOnStandbyError,
        )
    except ImportError:  # pragma: no cover - a core dependency
        pass
    else:
        if isinstance(exc, PlayStationNotFoundError):
            return "no PS5 found on the network: set GT7_PS5_IP or pass --ps5-ip", 1
        if isinstance(exc, PlayStationOnStandbyError):
            return f"the PS5 is on standby, wake it and try again: {exc}", 1
    if isinstance(exc, FileNotFoundError):
        return f"file not found: {exc.filename or exc}", 1
    if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
        return f"port already in use, is another engineer running? ({exc})", 1
    if isinstance(exc, PermissionError):
        return f"permission denied: {exc.filename or exc}", 1
    return None
