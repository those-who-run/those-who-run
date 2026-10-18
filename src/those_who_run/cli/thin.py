"""``those-who-run thin``: cut a recording down to a test fixture."""

from __future__ import annotations

import argparse
from pathlib import Path

from those_who_run.config import ConfigError, Settings

HELP = "cut a recording down to a test fixture"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path, help="a .jsonl or .jsonl.gz recording")
    parser.add_argument("output", type=Path, help="gzipped: .gz is added unless --plain")
    parser.add_argument("--plain", action="store_true", help="write plain JSONL, not gzip")
    parser.add_argument("--start", type=float, help="seconds from the first frame")
    parser.add_argument("--end", type=float, help="seconds from the first frame")
    parser.add_argument(
        "--every", type=float, default=0.5, help="keep one frame per this many seconds (0.5)"
    )
    parser.add_argument(
        "--window",
        action="append",
        default=[],
        metavar="START:END",
        help="keep every frame in this stretch: seconds (120:180) or laps (lap3:lap5); repeatable",
    )
    parser.add_argument(
        "--stride", type=int, default=0, help="outside windows, keep every Nth frame, not --every"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    return run_thin(
        args.source,
        args.output,
        args.start,
        args.end,
        args.every,
        args.plain,
        windows=args.window,
        stride=args.stride,
    )


def run_thin(
    source: Path,
    output: Path,
    start: float | None,
    end: float | None,
    every: float,
    plain: bool = False,
    windows: list[str] | None = None,
    stride: int = 0,
) -> int:
    from those_who_run.replay import Window, read_recording, thin, write_recording

    try:
        cuts = [Window.parse(w) for w in windows or []]
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if not plain and output.suffix != ".gz":
        output = output.with_name(output.name + ".gz")
    frames = list(read_recording(source))
    kept = write_recording(
        output,
        thin(frames, every=every, start=start, end=end, windows=cuts, stride=stride),
    )
    print(f"{kept} of {len(frames)} frames kept in {output}")
    return 0
