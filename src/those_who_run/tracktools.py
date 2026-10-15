"""Track detection over stored data: replay a recording or a session's Parquet, and backfill.

Sessions recorded before the detector existed (or while it was wrong) carry
``track_id = NULL``. Every frame of every lap is on disk, so the detector can
be run over them after the fact and the index and summary brought up to date.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from those_who_run.replay import read_recording
from those_who_run.store import track_record
from those_who_run.trackdetect import CONFIDENCE_RANK, TrackDetector, TrackMatch

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Step:
    """One change of the detector's mind, for the ``tracks detect`` report."""

    t: float
    lap: int
    match: TrackMatch


def detect_recording(path: Path) -> tuple[TrackMatch, list[Step]]:
    """Run the detector over a JSONL recording; returns the final match and every change."""
    det = TrackDetector()
    steps: list[Step] = []
    for state in read_recording(path):
        m = det.observe(state)
        if m is not None:
            steps.append(Step(state.t, state.current_lap, m))
    return det.match, steps


def session_points(session_dir: Path) -> Iterator[tuple[float, int, float, float]]:
    """(t, lap, x, z) for every stored frame of a session, in time order."""
    import duckdb

    files = sorted(session_dir.glob("lap-*.parquet"))
    if not files:
        return
    con = duckdb.connect()
    try:
        file_list = ", ".join(f"'{f}'" for f in files)
        rows = con.execute(
            f"SELECT t, lap, pos_x, pos_z FROM read_parquet([{file_list}]) ORDER BY t"
        ).fetchall()
    finally:
        con.close()
    yield from rows


def detect_session(session_dir: Path) -> tuple[TrackMatch, list[Step]]:
    """Run the detector over a stored session. Stored frames are all at-track frames,
    so there is no menu boundary to honour; a restart starts a new session anyway."""
    det = TrackDetector()
    steps: list[Step] = []
    for t, lap, x, z in session_points(session_dir):
        m = det.observe_point(x, z)
        if m is not None:
            steps.append(Step(t, lap, m))
    return det.match, steps


@dataclass(frozen=True, slots=True)
class BackfillResult:
    session_id: str
    before: tuple[int | None, str | None]
    after: TrackMatch
    updated: bool
    note: str


def backfill(data_dir: Path, force: bool = False) -> list[BackfillResult]:
    """Detect the track for every stored session and update index.sqlite and summary.json.

    Sessions already ``confirmed`` are left alone unless ``force``. Sessions
    without Parquet laps (the first JSON-era recordings) are reported and
    skipped. The detector is only applied when it would not lower the stored
    confidence.
    """
    data_dir = Path(data_dir)
    db = sqlite3.connect(data_dir / "index.sqlite")
    results: list[BackfillResult] = []
    try:
        cols = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
        if "track_confidence" not in cols:
            db.execute("ALTER TABLE sessions ADD COLUMN track_confidence TEXT")
        rows = db.execute(
            "SELECT id, track_id, track_confidence FROM sessions ORDER BY id"
        ).fetchall()
        for session_id, track_id, confidence in rows:
            before = (track_id, confidence)
            sdir = data_dir / "sessions" / session_id
            if confidence == "confirmed" and not force:
                results.append(
                    BackfillResult(
                        session_id, before, _unchanged(before), False, "already confirmed"
                    )
                )
                continue
            if not any(sdir.glob("lap-*.parquet")):
                results.append(
                    BackfillResult(session_id, before, _unchanged(before), False, "no parquet laps")
                )
                continue
            match, _ = detect_session(sdir)
            if match.confidence == "none":
                results.append(BackfillResult(session_id, before, match, False, "no layout fits"))
                continue
            if (
                CONFIDENCE_RANK[match.confidence] < CONFIDENCE_RANK[confidence or "none"]
                and not force
            ):
                results.append(
                    BackfillResult(session_id, before, match, False, "stored answer is better")
                )
                continue
            db.execute(
                "UPDATE sessions SET track_id = ?, track_confidence = ? WHERE id = ?",
                (match.track_id, match.confidence, session_id),
            )
            summary_path = sdir / "summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["track_id"] = match.track_id
                summary["track"] = track_record(match)
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            results.append(BackfillResult(session_id, before, match, True, "updated"))
        db.commit()
    finally:
        db.close()
    return results


def _unchanged(before: tuple[int | None, str | None]) -> TrackMatch:
    from those_who_run.tracks import track_name

    return TrackMatch(before[0], track_name(before[0]), before[1] or "none", (), "stored")  # type: ignore[arg-type]
