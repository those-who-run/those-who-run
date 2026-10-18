"""``those-who-run tracks``: list the track table, test detection, backfill data."""

from __future__ import annotations

import argparse
from pathlib import Path

from those_who_run.config import ConfigError, Settings

HELP = "track detection: list the table, test it, backfill data"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    trs = parser.add_subparsers(dest="tracks_command", required=True)
    trs.add_parser("list", help="print the track table")
    td = trs.add_parser("detect", help="run the detector over a recording or a stored session")
    td.add_argument(
        "source", type=Path, help="a .jsonl(.gz) recording or a sessions/<id> directory"
    )
    tb = trs.add_parser(
        "backfill", help="detect the track for stored sessions and update the index"
    )
    tb.add_argument("--force", action="store_true", help="re-run even for confirmed sessions")
    tl = trs.add_parser(
        "learn", help="derive a table row (finish line, direction, box) from a recorded lap"
    )
    tl.add_argument("source", type=Path, help="a .jsonl recording or a sessions/<id> directory")
    tl.add_argument("--id", type=int, default=0, help="track id for the printed CSV row")
    tl.add_argument("--name", default="NAME", help="track name for the printed CSV row")


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.tracks import load_tracks
    from those_who_run.tracktools import backfill, detect_recording, detect_session, learn_track

    if args.tracks_command == "list":
        for t in load_tracks():
            geo = (
                f"{t.direction}  box {t.box[2] - t.box[0]:.0f} x {t.box[3] - t.box[1]:.0f} m"
                if t.box
                else "no geometry"
            )
            print(f"{t.id:5d}  {t.name:55s} {geo}")
        return 0
    if args.tracks_command == "detect":
        src: Path = args.source
        if src.is_dir():
            match, steps = detect_session(src)
        elif src.name.endswith((".jsonl", ".jsonl.gz")):
            match, steps = detect_recording(src)
        else:
            raise ConfigError(f"{src}: expected a .jsonl(.gz) recording or a session directory")
        for st in steps:
            cands = ", ".join(
                f"{c.track.name} ({c.fit:.2f}{', line' if c.line_crossed else ''})"
                for c in st.match.candidates[:4]
            )
            m = st.match
            head = f"t={st.t:9.1f} lap {st.lap:2d}  {m.confidence:9s} {m.name}"
            print(f"{head}: {m.evidence}  [{cands}]")
        print(f"\nresult: {match.confidence} {match.name} ({match.track_id})")
        return 0 if match.confidence in ("confirmed", "probable") else 1
    if args.tracks_command == "learn":
        learned = learn_track(args.source)
        print(f"lap length {learned.lap_length_m:.0f} m over {learned.laps_used} completed lap(s)")
        print(f"finish line at {learned.line[0][0]:.0f},{learned.line[0][1]:.0f} .. ", end="")
        print(f"{learned.line[1][0]:.0f},{learned.line[1][1]:.0f}  direction {learned.direction}")
        print(f"box {' '.join(f'{v:.0f}' for v in learned.box)}")
        print("nearest existing lines:", learned.nearest)
        print("\ncsv row:\n" + learned.csv_row(args.id, args.name))
        return 0
    if args.tracks_command == "backfill":
        results = backfill(settings.data_dir, force=args.force)  # StoreBusy: see cli.main
        for r in results:
            flag = "updated" if r.updated else "skipped"
            print(
                f"{r.session_id}  {flag:8s} {r.after.confidence:9s} {r.after.name!s:40s} "
                f"(was {r.before[0]} {r.before[1] or '-'})  {r.note}"
            )
        print(f"\n{sum(r.updated for r in results)} of {len(results)} sessions updated")
        return 0
    return 1
