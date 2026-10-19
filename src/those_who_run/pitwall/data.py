"""Pit wall data access: the session index and the lap files, read-only, as plain data.

Plain data with no web framework, so it is tested on its own. The SQLite index is
opened read-only (``mode=ro``) and never created; the Parquet laps are read
through an in-memory DuckDB connection. The engineer may be writing a session
while the pit wall reads it, so a session without ``summary.json`` is still
listed, with its card facts rebuilt from the index.

The session list carries the results card's facts (``results.build_card``), so
the pit wall and the Discord post never disagree about a session. Each row also
carries the same facts as values (``SessionRow.values``, an ``api_models.Session``)
for the data API (#236); ``LapRow`` and ``Trace`` are its models too.

``lap_summaries`` is a stand-in for the lap summary table (#115): it works out
the lap flags from the index and the Parquet frames each time it is called.
When #115 lands, it reads that table instead and the page does not change.
Pit and out laps come from the pit-stop detector (#20, ``laps.pit``); sessions
stored before it fall back to spotting a refuel.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Any

from those_who_run.cars import car_name
from those_who_run.pitwall.api_models import LapRow, Session, Trace, Track
from those_who_run.results import (
    best_lap,
    build_card,
    kind_label,
    paused_result,
    position_shown,
    track_label,
)
from those_who_run.sessionkind import LABELS
from those_who_run.tracks import track_name

# For sessions stored before the pit-stop detector (#20): a rise in fuel this large
# within a lap, in GT7's fuel units, is a refuel, so a pit stop. An electric car's
# level creeps up by a few units over a time trial (Xiaomi VGT at High Speed Ring,
# 2026-10-16), so sessions with fuel use off are never read as stopping.
PIT_REFUEL = 2.0

# Gaps longer than this in a lap's frames (a pause, a telemetry drop) count as
# this long on the time axis, so traces of two laps still line up.
MAX_STEP_SECS = 0.1

# How long a read waits on a busy index before the page shows an error.
READ_TIMEOUT_SECS = 5.0

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class SessionRow:
    """One session in the list, with what its results card would show."""

    session_id: str
    started_at: float
    ended_at: float | None
    track: str  # as the card names it, "Unknown track" when not sure
    kind: str  # session kind key (sessionkind.Kind), "unknown" when not recorded
    car: str | None
    title: str  # the card title: "Sportsland SUGO · 5-lap race"
    result: str  # the card description: "🚩 Finished P3 of 20 in 8:36.182"
    facts: tuple[tuple[str, str], ...]  # the card fields: best lap, car, fuel used
    laps_completed: int
    closed: bool  # summary.json written: the session has ended
    track_id: int | None = None  # only when the detector is sure: probable or confirmed
    driving_ms: int | None = None  # time not paused (#229); None for older sessions
    # engineer restarts the session was continued across (#273): from, to, lap, reason
    gaps: tuple[dict[str, Any], ...] = ()
    # the session as values, for the data API (ADR 0004 point 6); None in tests'
    # hand-made rows
    values: Session | None = field(default=None, compare=False)

    @property
    def kind_name(self) -> str:
        return LABELS.get(self.kind, self.kind)

    @property
    def minutes(self) -> float | None:
        """How long the session ran, pauses left out (#229)."""
        if self.driving_ms is not None:
            return self.driving_ms / 60000
        return None if self.ended_at is None else (self.ended_at - self.started_at) / 60

    def started(self, tz: tzinfo | None = None) -> datetime:
        return datetime.fromtimestamp(self.started_at, tz)


@dataclass(frozen=True, slots=True)
class SessionFilter:
    """None (or an empty value) matches everything."""

    track: str | None = None
    car: str | None = None
    kind: str | None = None
    since: date | None = None  # inclusive, in the viewer's time zone
    until: date | None = None  # inclusive


# the index


def index_path(data_dir: Path) -> Path:
    return Path(data_dir) / "index.sqlite"


def index_stamp(data_dir: Path) -> float:
    """Changes whenever the engineer writes to the index: a cache key for the UI.

    The index is in WAL mode, so a commit lands in ``index.sqlite-wal`` and the
    main file only changes at a checkpoint: the stamp is the later of the two.
    An empty ``-wal`` is left out: a reader creates one when it opens the index
    after the engineer has closed it, and that is not a write (#236).
    """
    path = index_path(data_dir)
    stamps = []
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        if st.st_size or p == path:
            stamps.append(st.st_mtime)
    return max(stamps, default=0.0)


def open_index(data_dir: Path) -> sqlite3.Connection | None:
    """The index, read-only; None when the engineer has not created it yet."""
    path = index_path(data_dir)
    if not path.exists():
        return None
    # A busy timeout on this side too: a WAL reader can briefly wait on recovery
    # or a checkpoint.
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=READ_TIMEOUT_SECS)
    db.row_factory = sqlite3.Row
    return db


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _select(cols: tuple[str, ...], have: set[str], table: str) -> str:
    """``table.col`` for each column the table has, ``NULL AS col`` for the rest:
    older indexes predate some columns (``store._ensure_column``)."""
    return ", ".join(f"{table}.{c}" if c in have else f"NULL AS {c}" for c in cols)


_SESSION_COLS = (
    "id",
    "started_at",
    "ended_at",
    "type",
    "track_id",
    "car_code",
    "total_laps",
    "laps_completed",
    "best_lap_ms",
    "fuel_used",
    "final_position",
    "track_confidence",
    "session_kind",
    "fuel_use",
    "start_type",
    "gaps",
)
_LAP_COLS = (
    "lap",
    "lap_time_ms",
    "complete",
    "fuel_start",
    "fuel_end",
    "fuel_used",
    "position",
    "pit",  # before the pit-stop detector, NULL
    "frames",
    "file",
)


def _query(
    data_dir: Path, table: str, where: str = "", args: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """Rows of ``sessions`` or ``laps`` with every column the pit wall reads, NULL
    where an older index lacks one."""
    cols = {"sessions": _SESSION_COLS, "laps": _LAP_COLS}[table]
    db = open_index(data_dir)
    if db is None:
        return []
    try:
        sql = f"SELECT {_select(cols, _columns(db, table), table)} FROM {table} {where}"
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def safe_name(name: str) -> bool:
    """A session id or lap file name that stays in its directory."""
    return bool(_SAFE_NAME.match(name))


def _session_dir(data_dir: Path, session_id: str) -> Path:
    if not _SAFE_NAME.match(session_id):
        raise ValueError(f"not a session id: {session_id!r}")
    return Path(data_dir) / "sessions" / session_id


def read_summary(data_dir: Path, session_id: str) -> dict[str, Any] | None:
    """The session's summary.json, or None while the session is open (or lost)."""
    path = _session_dir(data_dir, session_id) / "summary.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError:
        return None


def _laps(data_dir: Path, session_id: str) -> list[dict[str, Any]]:
    rows = _query(data_dir, "laps", "WHERE session_id = ? ORDER BY lap", (session_id,))
    for r in rows:
        r["complete"] = bool(r["complete"])
    return rows


def _index_summary(row: dict[str, Any], laps: list[dict[str, Any]]) -> dict[str, Any]:
    """A summary.json look-alike from the index, for a session still being written."""
    track_id = row["track_id"]
    kind = row["session_kind"]
    fuel_use = row["fuel_use"]
    return {
        "session_id": row["id"],
        "type": row["type"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "track_id": track_id,
        "track": None
        if track_id is None
        else {"id": track_id, "name": track_name(track_id), "confidence": row["track_confidence"]},
        "session_kind": None
        if kind is None
        else {
            "kind": kind,
            "fuel_use": None if fuel_use is None else bool(fuel_use),
            "start": row["start_type"],
            # The index does not keep the field or GT7's flag, so no position is
            # shown for an open session.
        },
        "car_code": row["car_code"],
        "car_name": car_name(row["car_code"]),
        "total_laps": row["total_laps"],
        "laps_completed": row["laps_completed"],
        "best_lap_ms": row["best_lap_ms"],
        "finished": False,
        "final_position": row["final_position"],
        "fuel_used": row["fuel_used"],
        "gaps": json.loads(row["gaps"]) if row["gaps"] else [],
        "laps": laps,
    }


def session_summary(data_dir: Path, session_id: str) -> dict[str, Any] | None:
    """summary.json, or the index's view of the session while it is still open."""
    summary = read_summary(data_dir, session_id)
    if summary is not None:
        return summary
    rows = _query(data_dir, "sessions", "WHERE id = ?", (session_id,))
    return _index_summary(rows[0], _laps(data_dir, session_id)) if rows else None


def _row(summary: dict[str, Any], closed: bool) -> SessionRow:
    kind_rec = summary.get("session_kind") or {}
    kind = kind_rec.get("kind") or "unknown"
    total_laps = int(summary.get("total_laps") or 0)
    card = build_card(summary)
    laps = int(summary.get("laps_completed") or 0)
    if card is not None:
        title, result, facts = card.title, card.description, card.fields
        if not closed:  # the card would call a session that is still going "retired"
            result = f"Running, {laps} lap" + ("" if laps == 1 else "s")
    else:
        # No full lap: no card either, but still a row.
        title = f"{track_label(summary.get('track'))} · {kind_label(kind, total_laps, summary)}"
        result = "no full lap" if closed else "Running, no full lap yet"
        if closed and summary.get("ended_paused"):
            position = summary.get("final_position") if position_shown(kind_rec) else None
            result = f"{paused_result(summary, position)}, no full lap"
        car = summary.get("car_name")
        facts = (("Car", car),) if car else ()
    return SessionRow(
        session_id=str(summary["session_id"]),
        started_at=float(summary.get("started_at") or 0.0),
        ended_at=summary.get("ended_at"),
        track=track_label(summary.get("track")),
        kind=kind,
        car=summary.get("car_name"),
        title=title,
        result=result,
        facts=tuple(facts),
        laps_completed=laps,
        closed=closed,
        track_id=sure_track_id(summary.get("track")),
        driving_ms=summary.get("driving_ms"),
        gaps=tuple(summary.get("gaps") or ()),
        values=session_values(summary, closed, title, result),
    )


def session_values(summary: dict[str, Any], closed: bool, title: str, result: str) -> Session:
    """The session as values, from the same summary its card is built from."""
    kind_rec = summary.get("session_kind") or {}
    kind = kind_rec.get("kind") or "unknown"
    total_laps = int(summary.get("total_laps") or 0)
    laps = summary.get("laps") or []
    quickest = best_lap(laps, kind == "lap_race", summary.get("gt7_best_lap_ms"))
    track = summary.get("track") or {}
    track_id = track.get("id", summary.get("track_id"))
    stops = summary.get("pit_stops")
    if stops is None:  # an open session, or one stored before the detector: count in-laps
        stops = [x for x in laps if x.get("pit") in ("in", "in_out")]
    used = summary.get("fuel_burned", summary.get("fuel_used"))
    restarts = [g["lap"] for g in summary.get("gaps") or [] if g.get("lap") is not None]
    return Session(
        session_id=str(summary["session_id"]),
        title=title,
        result=result,
        started_at=float(summary.get("started_at") or 0.0),
        ended_at=summary.get("ended_at"),
        closed=closed,
        kind=kind,
        kind_label=kind_label(kind, total_laps, summary),
        track=Track(
            id=None if track_id is None else int(track_id),
            name=track_label(summary.get("track")),
            sure=sure_track_id(summary.get("track")) is not None,
            evidence=track.get("evidence"),
        ),
        car=summary.get("car_name"),
        car_code=summary.get("car_code"),
        finished=bool(summary.get("finished")),
        final_position=summary.get("final_position"),
        total_cars=summary.get("total_cars"),
        position_shown=position_shown(kind_rec),
        total_time_ms=summary.get("total_time_ms"),
        best_lap_ms=quickest[1] if quickest else None,
        best_lap_no=quickest[0] if quickest else None,
        laps_completed=int(summary.get("laps_completed") or 0),
        total_laps=total_laps,
        fuel_use=kind_rec.get("fuel_use"),
        fuel_used=used,
        fuel_capacity=summary.get("fuel_capacity"),
        fuel_by_stint=list(summary.get("fuel_burned_by_stint") or ([used] if used else [])),
        pit_stops=len(stops),
        driving_ms=summary.get("driving_ms"),
        paused_ms=summary.get("paused_ms"),
        joined_on_lap=summary.get("joined_on_lap"),
        continued=bool(summary.get("gaps")),
        restart_laps=restarts,
    )


def sure_track_id(rec: dict[str, Any] | None) -> int | None:
    """The detector's track id when it is probable or confirmed, else None."""
    if not rec or rec.get("confidence") not in ("probable", "confirmed"):
        return None
    track_id = rec.get("id")
    return None if track_id is None else int(track_id)


def same_track(a: SessionRow, b: SessionRow) -> bool:
    """Both sessions at the same layout, as far as the detector is sure. Two
    sessions it could not place are not the same track."""
    return a.track_id is not None and a.track_id == b.track_id


def same_track_sessions(row: SessionRow, sessions: list[SessionRow]) -> list[SessionRow]:
    """The other sessions at ``row``'s track, for lap B in lap compare."""
    return [s for s in sessions if s.session_id != row.session_id and same_track(row, s)]


def list_sessions(data_dir: Path) -> list[SessionRow]:
    """Every session in the index, newest first."""
    rows = _query(data_dir, "sessions", "ORDER BY started_at DESC")
    out = []
    for r in rows:
        summary = read_summary(data_dir, r["id"])
        if summary is None:
            out.append(_row(_index_summary(r, _laps(data_dir, r["id"])), closed=False))
        else:
            out.append(_row(summary, closed=True))
    return out


def filter_options(sessions: list[SessionRow]) -> dict[str, list[str]]:
    """The values each filter can take, from the sessions there are."""
    return {
        "track": sorted({s.track for s in sessions}),
        "car": sorted({s.car for s in sessions if s.car}),
        "kind": [k for k in LABELS if any(s.kind == k for s in sessions)],
    }


def filter_sessions(
    sessions: list[SessionRow], f: SessionFilter, tz: tzinfo | None = None
) -> list[SessionRow]:
    def keep(s: SessionRow) -> bool:
        day = s.started(tz).date()
        return (
            (not f.track or s.track == f.track)
            and (not f.car or s.car == f.car)
            and (not f.kind or s.kind == f.kind)
            and (f.since is None or day >= f.since)
            and (f.until is None or day <= f.until)
        )

    return [s for s in sessions if keep(s)]


FACETS = ("track", "car", "kind")


def option_counts(
    sessions: list[SessionRow], f: SessionFilter, tz: tzinfo | None = None
) -> dict[str, dict[str, int]]:
    """Per filter, each value it can take (``filter_options``) and how many
    sessions it would leave with the *other* filters as they are (#318): a
    value that would empty the list counts 0, and a filter's own choice never
    hides its alternatives."""
    options = filter_options(sessions)
    out: dict[str, dict[str, int]] = {}
    for key in FACETS:
        rest = filter_sessions(sessions, replace(f, **{key: None}), tz)
        counts = Counter(getattr(s, key) for s in rest)
        out[key] = {value: counts[value] for value in options[key]}
    return out


# laps


def _lap_file(data_dir: Path, session_id: str, file: str) -> Path:
    if not _SAFE_NAME.match(file):
        raise ValueError(f"not a lap file: {file!r}")
    return _session_dir(data_dir, session_id) / file


def _lap_stats(paths: list[Path]) -> dict[str, tuple[float, float]]:
    """Per lap file: top speed, and the largest rise in fuel above the lowest level
    so far in the lap (a refuel)."""
    import duckdb

    if not paths:
        return {}
    con = duckdb.connect()
    try:
        rows = con.execute(
            "WITH f AS (SELECT filename, speed_kph, fuel_level - min(fuel_level) OVER"
            " (PARTITION BY filename ORDER BY t ROWS UNBOUNDED PRECEDING) AS rise"
            " FROM read_parquet(?, filename = true, union_by_name = true))"
            " SELECT filename, max(speed_kph), max(rise) FROM f GROUP BY filename",
            [[str(p) for p in paths]],
        ).fetchall()
    finally:
        con.close()
    return {Path(name).name: (top, rise) for name, top, rise in rows}


def lap_summaries(data_dir: Path, session_id: str) -> list[LapRow]:
    """The lap table for a session, flags included.

    Stand-in for the lap summary table (#115), derived each time:

    - **pit / out lap:** the in-lap and out-lap as the pit-stop detector stored
      them (``laps.pit``), tyres-only stops included. Sessions stored before the
      detector (no ``pit_stops`` in the summary, no lap marked) fall back to a
      refuel: fuel rose by ``PIT_REFUEL`` or more during the lap, in a session
      whose fuel use is not off, and the out lap is the one after it.
    - **invalid:** no lap time: the partial lap at the end of a session, or a
      crossing GT7 gave no time for. GT7 does not report track limits. The lap
      an engineer restart fell in (#273) is partial too, and flagged ``restart``.
    """
    summary = session_summary(data_dir, session_id)
    if summary is None:
        return []
    laps = _laps(data_dir, session_id)
    sdir = _session_dir(data_dir, session_id)
    files = [sdir / r["file"] for r in laps if _SAFE_NAME.match(r["file"])]
    stats = _lap_stats([f for f in files if f.exists()])  # a lap still being written

    kind_rec = summary.get("session_kind") or {}
    fuel_off = kind_rec.get("fuel_use") is False
    show_position = position_shown(kind_rec)
    quickest = best_lap(laps, kind_rec.get("kind") == "lap_race", summary.get("gt7_best_lap_ms"))
    best_no = quickest[0] if quickest else None

    detected = "pit_stops" in summary or any(r["pit"] for r in laps)
    restarts = {g.get("lap") for g in summary.get("gaps") or []}
    out: list[LapRow] = []
    prev_pit = False
    for r in laps:
        top, rise = stats.get(r["file"], (None, None))
        if detected:
            pit = r["pit"] in ("in", "in_out")
            out_lap = r["pit"] in ("out", "in_out")
        else:
            refuelled = (rise or 0.0) >= PIT_REFUEL or (r["fuel_used"] or 0.0) <= -PIT_REFUEL
            pit = refuelled and not fuel_off
            out_lap = prev_pit
        out.append(
            LapRow(
                lap=r["lap"],
                time_ms=r["lap_time_ms"],
                complete=r["complete"],
                fuel_start=r["fuel_start"],
                fuel_end=r["fuel_end"],
                fuel_used=r["fuel_used"],
                position=r["position"] if show_position else None,
                frames=r["frames"],
                file=r["file"],
                top_speed_kph=top,
                pit=pit,
                out_lap=out_lap,
                invalid=not r["complete"] or not r["lap_time_ms"],
                best=r["lap"] == best_no,
                fuel_use=not fuel_off,
                restart=r["lap"] in restarts,
            )
        )
        prev_pit = pit
    return out


def lap_file(data_dir: Path, session_id: str, lap: int) -> tuple[str, int] | None:
    """The lap's file name and frame count from the index, or None for no such lap.
    A lap file never changes once its row is in the index (#148), so these key a
    trace's cache."""
    rows = [r for r in _laps(data_dir, session_id) if r["lap"] == lap]
    return (rows[0]["file"], int(rows[0]["frames"] or 0)) if rows else None


def lap_trace(data_dir: Path, session_id: str, lap: int, max_points: int = 1500) -> Trace | None:
    """Speed, throttle, brake, gear and RPM for one lap against time, thinned to
    at most ``max_points`` frames (a phone does not need 60 Hz). None when the
    lap or its file is missing.

    Thinning keeps peaks (#183 R2): the frames are cut into stretches, and each
    stretch keeps its slowest and its fastest frame, so a braking point's
    minimum and a straight's top speed survive. The first and last frames are
    always kept. Under four points, it takes every n-th frame instead."""
    import duckdb

    found = lap_file(data_dir, session_id, lap)
    if found is None:
        return None
    path = _lap_file(data_dir, session_id, found[0])
    if not path.exists():
        return None
    con = duckdb.connect()
    try:
        row = con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
        n = row[0] if row else 0
        points = max(1, max_points)
        if n <= points:
            size, keep = 1, "true"
        elif points < 4:
            size = math.ceil(n / points)
            keep = f"rn % {size} = 0"
        else:
            size = math.ceil(n / ((points - 2) // 2))  # two frames a stretch, plus the ends
            keep = "lo = 1 OR hi = 1 OR rn = 0 OR rn = n - 1"
        data = con.execute(
            "WITH f AS (SELECT *, row_number() OVER (ORDER BY t) - 1 AS rn, count(*) OVER () AS n,"
            " least(coalesce(t - lag(t) OVER (ORDER BY t), 0), ?) AS dt FROM read_parquet(?)),"
            " g AS (SELECT *, sum(dt) OVER (ORDER BY t ROWS UNBOUNDED PRECEDING) AS el,"
            f" row_number() OVER (PARTITION BY rn // {size} ORDER BY speed_kph, rn) AS lo,"
            f" row_number() OVER (PARTITION BY rn // {size} ORDER BY speed_kph DESC, rn) AS hi"
            " FROM f) SELECT el, speed_kph, throttle * 100.0 / 255, brake * 100.0 / 255, gear,"
            f" engine_rpm FROM g WHERE {keep} ORDER BY t",
            [MAX_STEP_SECS, str(path)],
        ).fetchall()
    finally:
        con.close()
    cols = list(zip(*data, strict=True)) if data else [()] * 6
    return Trace(
        session_id=session_id,
        lap=lap,
        t=tuple(round(v, 3) for v in cols[0]),
        speed_kph=tuple(cols[1]),
        throttle_pct=tuple(round(v, 1) for v in cols[2]),
        brake_pct=tuple(round(v, 1) for v in cols[3]),
        gear=tuple(cols[4]),
        rpm=tuple(cols[5]),
    )
