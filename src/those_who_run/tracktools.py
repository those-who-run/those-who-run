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
from those_who_run.state import Phase
from those_who_run.store import track_record
from those_who_run.trackdetect import CONFIDENCE_RANK, LAP_PHASES, TrackDetector, TrackMatch

log = logging.getLogger(__name__)
LAP_VALUES = frozenset(p.value for p in LAP_PHASES)


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


def session_points(
    session_dir: Path,
) -> Iterator[tuple[float, int, str, float, float, float, float]]:
    """(t, lap, phase, x, z, vel_x, vel_z) for every stored frame of a session, in time order."""
    import duckdb

    files = sorted(session_dir.glob("lap-*.parquet"))
    if not files:
        return
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT t, lap, phase, pos_x, pos_z, vel_x, vel_z"
            " FROM read_parquet(?, union_by_name = true) ORDER BY t",
            [[str(f) for f in files]],
        ).fetchall()
    finally:
        con.close()
    yield from rows


def detect_session(session_dir: Path) -> tuple[TrackMatch, list[Step]]:
    """Run the detector over a stored session. Stored frames are all at-track frames,
    so there is no menu boundary to honour; a restart starts a new session anyway."""
    det = TrackDetector()
    steps: list[Step] = []
    for t, lap, phase, x, z, vx, vz in session_points(session_dir):
        m = det.observe_point(x, z, lap=lap if phase in LAP_VALUES else None, velocity=(vx, vz))
        if m is not None:
            steps.append(Step(t, lap, m))
    return det.match, steps


@dataclass(frozen=True, slots=True)
class LearnedTrack:
    """A table row derived from a recorded lap, for layouts the table lacks or gets wrong."""

    line: tuple[tuple[float, float], tuple[float, float]]
    direction: str
    box: tuple[float, float, float, float]
    lap_length_m: float
    laps_used: int
    nearest: list[tuple[float, int, str]]  # (distance to its line, id, name) of existing rows

    def csv_row(self, track_id: int, name: str) -> str:
        (p1x, p1z), (p2x, p2z) = self.line
        minx, minz, maxx, maxz = self.box
        return ",".join(
            [str(track_id), name, self.direction]
            + [f"{v:.3f}" for v in (p1x, p1z, p2x, p2z, minx, minz, maxx, maxz)]
            + [f"{self.lap_length_m:.0f}"]
        )


def learn_track(source: Path, half_width_m: float = 15.0) -> LearnedTrack:
    """Derive finish line, direction and lap box from a recording or stored session.

    The finish line is placed where GT7's lap counter first incremented,
    perpendicular to the direction of travel, ``half_width_m`` either side of
    the car. The box covers every complete lap. Needs at least one completed
    lap; raises ValueError otherwise.
    """
    import math

    from those_who_run.trackdetect import distance_to_segment, travel_direction
    from those_who_run.tracks import load_tracks

    if source.is_dir():
        pts = [
            (lap if phase in LAP_VALUES else None, x, z)
            for _, lap, phase, x, z, _, _ in session_points(source)
        ]
    else:
        pts = [
            (s.current_lap if s.phase in LAP_PHASES else None, s.pos_x, s.pos_z)
            for s in read_recording(source)
            if s.phase in (Phase.IN_RACE, Phase.AT_TRACK, Phase.FINISHED)
        ]
    boundaries: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    last_lap: int | None = None
    prev: tuple[float, float] | None = None
    for lap, x, z in pts:
        if lap is not None and last_lap is not None and lap > last_lap >= 1 and prev is not None:
            boundaries.append((len(boundaries), prev, (x, z)))
        if lap is not None:
            last_lap = lap
        prev = (x, z)
    if not boundaries:
        raise ValueError(f"{source}: no completed lap (the lap counter never incremented)")
    _, a, b = boundaries[0]
    direction = travel_direction(a, b) or "PX"
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / length, dx / length  # perpendicular to travel
    line = (
        (b[0] - nx * half_width_m, b[1] - nz * half_width_m),
        (b[0] + nx * half_width_m, b[1] + nz * half_width_m),
    )
    # Box and length over the complete laps only (between the first and last boundary,
    # or the first boundary and the end of the data if only one lap completed).
    racing = [(x, z) for lap, x, z in pts if lap is not None and lap >= 1]
    xs = [p[0] for p in racing]
    zs = [p[1] for p in racing]
    box = (min(xs), min(zs), max(xs), max(zs))
    lap_pts = [
        (x, z) for lap, x, z in pts if lap is not None and lap == (last_lap or 1) - 1
    ] or racing
    lap_len = sum(
        math.hypot(lap_pts[i][0] - lap_pts[i - 1][0], lap_pts[i][1] - lap_pts[i - 1][1])
        for i in range(1, len(lap_pts))
    )
    nearest = sorted(
        (distance_to_segment(b, *t.line), t.id, t.name) for t in load_tracks() if t.line
    )[:5]
    return LearnedTrack(
        line, direction, box, lap_len, len(boundaries), [(round(d), i, n) for d, i, n in nearest]
    )


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
    skipped. A verdict only replaces the stored one when it is at least as
    confident, with one exception: "nothing fits" (``none``) from a newer
    detector replaces an earlier ``ambiguous`` or ``probable`` guess, because
    a wrong name is worse than no name.
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
            stored = confidence or "none"
            sdir = data_dir / "sessions" / session_id
            if stored == "confirmed" and not force:
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
            if match.confidence == "none" and track_id is None and stored == "none":
                results.append(BackfillResult(session_id, before, match, False, "no layout fits"))
                continue
            if (
                match.confidence != "none"
                and CONFIDENCE_RANK[match.confidence] < CONFIDENCE_RANK[stored]
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
            note = "cleared stale guess" if match.confidence == "none" else "updated"
            results.append(BackfillResult(session_id, before, match, True, note))
        db.commit()
    finally:
        db.close()
    return results


def _unchanged(before: tuple[int | None, str | None]) -> TrackMatch:
    from those_who_run.tracks import track_name

    return TrackMatch(before[0], track_name(before[0]), before[1] or "none", (), "stored")  # type: ignore[arg-type]
