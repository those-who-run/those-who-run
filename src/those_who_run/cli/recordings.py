"""``those-who-run recordings``: list outing recordings, or archive them."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from those_who_run.config import ConfigError, Settings

log = logging.getLogger("those_who_run")

HELP = "one line per session in each outing recording (GT7_RECORD_DIR)"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="recordings or directories; or `archive [OUTING ...]` to archive outings "
        "(ids in GT7_RECORD_DIR, or paths) or, with none, list the archive",
    )
    parser.add_argument("--last", type=int, default=0, help="only the newest N recordings")
    parser.add_argument("--note", default="", help="archive: what the outing shows")
    parser.add_argument(
        "--issue", type=int, action="append", default=[], help="archive: an issue citing it"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    if args.paths[:1] == [Path("archive")]:
        return run_archive(settings, args.paths[1:], args.note, args.issue)
    return run_recordings(settings, args.paths, args.last)


def run_recordings(settings: Settings, paths: list[Path], last: int) -> int:
    from those_who_run.recordtools import list_recordings, summarise_recording

    if not paths:
        if settings.record_dir is None:
            raise ConfigError("give recordings or a directory, or set GT7_RECORD_DIR")
        paths = [settings.record_dir]
    files: list[Path] = []
    for p in paths:
        files.extend(list_recordings(p) if p.is_dir() else [p])
    if last:
        files = files[-last:]
    for f in files:
        try:
            sessions, complete = summarise_recording(f)
        except Exception as exc:  # noqa: BLE001 - one bad file must not end the listing
            log.exception("could not read %s", f)
            print(f"{f.name}  (unreadable: {exc})")
            continue
        print(f.name + ("" if complete else "  (incomplete: still being written or cut off)"))
        for s in sessions:
            print("   " + s.line())
        if not sessions:
            print("   no session")
    return 0


def run_archive(settings: Settings, refs: list[Path], note: str, issues: list[int]) -> int:
    """``recordings archive``: copy outings into GT7_ARCHIVE_DIR, or list it."""
    from those_who_run.archive import archive_dir, archive_outing, find_outing, list_archive

    directory = archive_dir()
    if not refs:
        entries = list_archive(directory)
        for e in entries:
            print(e.line())
            if e.note:
                print("   " + e.note)
        if not entries:
            print(f"nothing archived in {directory}")
        return 0
    for ref in refs:
        try:
            source = find_outing(ref, settings.record_dir)
            entry = archive_outing(source, directory, note=note, issues=issues)
        except (FileNotFoundError, ValueError) as exc:
            raise ConfigError(str(exc)) from exc
        print(f"archived {entry.line()}")
        for line in entry.sessions:
            print("   " + line)
    print(f"in {directory}; `make archive-push` uploads it")
    return 0
