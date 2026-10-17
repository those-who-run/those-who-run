"""Session store: every frame of every lap as Parquet, plus a SQLite index.

Layout under the data directory::

    index.sqlite                       sessions and laps tables (WAL journal)
    engineer.lock                      held exclusively by the one writer, see writer_lock
    sessions/<id>/lap-NN.parquet       60 Hz frames for lap NN (ZSTD)
    sessions/<id>/summary.json         human-readable session summary

Frames are buffered in memory and written when the lap completes, so a crash
costs at most the lap in progress. Parquet is written through DuckDB, which
the pit wall also uses to read it back; no pandas or pyarrow in the engineer.

The Parquet write runs on a single background thread. An 8-minute Nordschleife
lap is ~28k frames and DuckDB's row-by-row ``executemany`` took over a minute
for it on the event loop (2026-10-14), which starved the Discord heartbeat.
Spooling the rows through a CSV file and ``COPY``-ing it in takes well under
a second for the same lap.

The index is in WAL mode so the pit wall (another process, read-only) never
makes the engineer's commits wait, and the other way round. Commits run on the
event loop, so nothing that writes the index may hold a write transaction for
long: ``tracks backfill`` commits per session.

One writer at a time (ADR 0001, point 1): whatever writes under the data
directory holds an exclusive ``flock`` on ``engineer.lock`` while it does. A
``SessionStore`` takes it when it opens and drops it when it closes, so the live
engineer holds it for as long as ``run`` is up, and ``post``, ``replay --store``
and ``tracks backfill`` refuse (``StoreBusy``) rather than wait while it does.
The engineer refuses to start while one of them holds it. Readers (the pit
wall) never take it.

A lap's ``laps`` row is inserted by that same thread once its Parquet file is
complete, so a reader that finds the row always finds the file (#148). The
SQLite connection is shared between the event loop and the writer thread, so
every use of it holds ``_db_lock``.
"""

from __future__ import annotations

import contextlib
import csv
import fcntl
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from those_who_run.cars import car_name
from those_who_run.pitstop import NO_STOPS, PitStatus
from those_who_run.results import best_lap
from those_who_run.sessionkind import SessionKind
from those_who_run.state import Phase, RaceState, lap_completed, racing_frame
from those_who_run.trackdetect import TrackMatch

log = logging.getLogger(__name__)

FRAME_COLUMNS: tuple[tuple[str, str], ...] = (
    ("t", "DOUBLE"),
    ("packet_id", "BIGINT"),
    ("lap", "INTEGER"),
    ("phase", "VARCHAR"),
    ("pos_x", "DOUBLE"),
    ("pos_y", "DOUBLE"),
    ("pos_z", "DOUBLE"),
    ("vel_x", "DOUBLE"),
    ("vel_y", "DOUBLE"),
    ("vel_z", "DOUBLE"),
    ("speed_kph", "DOUBLE"),
    ("engine_rpm", "DOUBLE"),
    ("gear", "INTEGER"),
    ("suggested_gear", "INTEGER"),
    ("throttle", "INTEGER"),
    ("brake", "INTEGER"),
    ("fuel_level", "DOUBLE"),
    ("tire_fl_temp", "DOUBLE"),
    ("tire_fr_temp", "DOUBLE"),
    ("tire_rl_temp", "DOUBLE"),
    ("tire_rr_temp", "DOUBLE"),
    ("tire_fl_radius", "DOUBLE"),
    ("tire_fr_radius", "DOUBLE"),
    ("tire_rl_radius", "DOUBLE"),
    ("tire_rr_radius", "DOUBLE"),
    ("sus_fl", "DOUBLE"),
    ("sus_fr", "DOUBLE"),
    ("sus_rl", "DOUBLE"),
    ("sus_rr", "DOUBLE"),
    ("wheel_fl_rps", "DOUBLE"),
    ("wheel_fr_rps", "DOUBLE"),
    ("wheel_rl_rps", "DOUBLE"),
    ("wheel_rr_rps", "DOUBLE"),
    ("water_temp", "DOUBLE"),
    ("oil_temp", "DOUBLE"),
    ("oil_pressure", "DOUBLE"),
    ("boost_pressure", "DOUBLE"),
    ("body_height", "DOUBLE"),
    ("position", "INTEGER"),
    ("time_of_day_ms", "BIGINT"),
    ("car_code", "INTEGER"),
    ("track_id", "INTEGER"),
    ("rot_x", "DOUBLE"),
    ("rot_y", "DOUBLE"),
    ("rot_z", "DOUBLE"),
    ("orientation", "DOUBLE"),
    ("ang_vel_x", "DOUBLE"),
    ("ang_vel_y", "DOUBLE"),
    ("ang_vel_z", "DOUBLE"),
)

# How long a write waits for another writer (backfill, a ``post``) before failing.
BUSY_TIMEOUT_SECS = 5.0
LOCK_FILE = "engineer.lock"


class LapNotIndexed(RuntimeError):
    """A lap file was written but its row could not be added to the index."""


class StoreBusy(RuntimeError):
    """Another process (the engineer, or a command such as ``tracks backfill``)
    holds the data directory's writer lock."""


def connect_index(data_dir: Path) -> sqlite3.Connection:
    """Open (or create) the index for writing: WAL journal and a busy timeout.

    ``journal_mode=WAL`` is persistent, so this also converts an index made by
    an earlier version on its first open.
    """
    db = sqlite3.connect(
        Path(data_dir) / "index.sqlite", timeout=BUSY_TIMEOUT_SECS, check_same_thread=False
    )
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECS * 1000)}")
    return db


def writer_lock(data_dir: Path) -> IO[bytes]:
    """Take the data directory's writer lock (an exclusive ``flock`` on
    ``engineer.lock``) without waiting; raises StoreBusy while another process
    holds it. The lock goes when the returned file is closed or the process
    dies, so a crash leaves nothing stale."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    f = (data_dir / LOCK_FILE).open("ab")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise StoreBusy(
            f"{data_dir} is in use by another writer (the engineer, or a command such as"
            " tracks backfill): use the pit wall, or stop that process first"
        ) from None
    return f


@contextlib.contextmanager
def exclusive_store(data_dir: Path) -> Iterator[None]:
    """Hold the writer lock for a block, for a bulk rewrite such as backfill."""
    f = writer_lock(data_dir)
    try:
        yield
    finally:
        f.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    type TEXT NOT NULL,
    track_id INTEGER,
    car_code INTEGER,
    total_laps INTEGER NOT NULL,
    laps_completed INTEGER NOT NULL DEFAULT 0,
    best_lap_ms INTEGER,
    fuel_used REAL,
    final_position INTEGER
);
CREATE TABLE IF NOT EXISTS laps (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    lap INTEGER NOT NULL,
    lap_time_ms INTEGER,
    complete INTEGER NOT NULL,
    fuel_start REAL,
    fuel_end REAL,
    fuel_used REAL,
    position INTEGER,
    frames INTEGER NOT NULL,
    file TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (session_id, lap)
);
"""


def frame_row(state: RaceState) -> tuple[Any, ...]:
    tt, tr, sh, wr = state.tire_temp, state.tire_radius, state.suspension_height, state.wheel_rps
    return (
        state.t,
        state.packet_id,
        state.current_lap,
        state.phase.value,
        state.pos_x,
        state.pos_y,
        state.pos_z,
        state.vel_x,
        state.vel_y,
        state.vel_z,
        state.speed_kph,
        state.engine_rpm,
        state.current_gear,
        state.suggested_gear,
        state.throttle,
        state.brake,
        state.fuel_level,
        *tt,
        *tr,
        *sh,
        *wr,
        state.water_temp,
        state.oil_temp,
        state.oil_pressure,
        state.boost_pressure,
        state.body_height,
        state.position,
        state.time_of_day_ms,
        state.car_code,
        state.track_id,
        state.rot_x,
        state.rot_y,
        state.rot_z,
        state.orientation,
        state.ang_vel_x,
        state.ang_vel_y,
        state.ang_vel_z,
    )


def write_parquet(path: Path, rows: list[tuple[Any, ...]]) -> float:
    """Write ``rows`` (in FRAME_COLUMNS order) to ``path``; returns seconds taken."""
    import duckdb

    started = time.perf_counter()
    cols = ", ".join(f"{name} {typ}" for name, typ in FRAME_COLUMNS)
    tmp_csv = path.with_suffix(".tmp.csv")
    tmp_parquet = path.with_suffix(".tmp.parquet")
    try:
        with tmp_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([name for name, _ in FRAME_COLUMNS])
            writer.writerows(rows)
        con = duckdb.connect()
        try:
            con.execute(f"CREATE TABLE frames ({cols})")
            con.execute(f"COPY frames FROM '{tmp_csv}' (HEADER, NULLSTR '')")
            con.execute(f"COPY frames TO '{tmp_parquet}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            con.close()
        tmp_parquet.replace(path)
    finally:
        tmp_csv.unlink(missing_ok=True)
        tmp_parquet.unlink(missing_ok=True)
    return time.perf_counter() - started


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    """Write summary.json atomically: a temporary file next to it, synced, then
    renamed over it. A crash leaves the old file or the new one, never half of
    one (a truncated summary would show the session as running for ever)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(summary, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def track_record(match: TrackMatch) -> dict[str, Any]:
    """The detector verdict as stored in summary.json."""
    return {
        "id": match.track_id,
        "name": match.name,
        "confidence": match.confidence,
        "family": match.family,
        "evidence": match.evidence,
        "candidates": [
            {"id": c.track.id, "name": c.track.name, "fit": round(c.fit, 3), "line": c.line_crossed}
            for c in match.candidates
        ],
    }


def session_best_lap(
    laps: list[dict[str, Any]], kind: dict[str, Any] | None, gt7_best: int | None
) -> int | None:
    """The session's best lap as the results card, the pit wall and the spoken
    summary give it (``results.best_lap``): GT7's own best when there is one,
    else the quickest complete lap, leaving out lap 1 of a lap race."""
    quickest = best_lap(laps, (kind or {}).get("kind") == "lap_race", gt7_best)
    return quickest[1] if quickest else None


@dataclass(frozen=True, slots=True)
class BestLapFix:
    session_id: str
    before: int | None
    after: int | None


def rebuild_best_laps(data_dir: Path) -> list[BestLapFix]:
    """Recompute ``best_lap_ms`` for every stored session from the laps in its
    ``summary.json`` and correct the index and the summary where they differ.

    A one-off fix for stores written by 0.4.0 and earlier, which counted lap 1
    from a grid start (#185). Safe to run again: a corrected session is left alone.
    Sessions without a summary (still open, or cut short by a crash) are skipped.

    Refuses (``StoreBusy``) while the engineer is running, like ``tracks
    backfill``: it rewrites summary.json files. Each session is committed on its
    own, so no write transaction is held across the store.
    """
    data_dir = Path(data_dir)
    with exclusive_store(data_dir):
        return _rebuild_best_laps(data_dir)


def _rebuild_best_laps(data_dir: Path) -> list[BestLapFix]:
    db = connect_index(data_dir)
    fixes: list[BestLapFix] = []
    try:
        rows = db.execute("SELECT id, best_lap_ms FROM sessions ORDER BY id").fetchall()
        for session_id, stored in rows:
            path = data_dir / "sessions" / session_id / "summary.json"
            if not path.exists():
                continue
            summary = json.loads(path.read_text(encoding="utf-8"))
            laps = summary.get("laps") or []
            best = session_best_lap(
                laps, summary.get("session_kind"), summary.get("gt7_best_lap_ms")
            )
            if (
                best == stored
                and best == summary.get("best_lap_ms")
                and "fastest_lap_ms" in summary
            ):
                continue
            times = [x["lap_time_ms"] for x in laps if x.get("complete") and x.get("lap_time_ms")]
            summary["best_lap_ms"] = best
            summary["fastest_lap_ms"] = min(times) if times else None
            write_summary(path, summary)
            db.execute("UPDATE sessions SET best_lap_ms = ? WHERE id = ?", (best, session_id))
            db.commit()
            if best != stored:
                fixes.append(BestLapFix(session_id, stored, best))
    finally:
        db.close()
    return fixes


def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Additive schema migration: older index files predate the column."""
    cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def session_type(state: RaceState) -> str:
    if state.is_race:
        return "race"
    return "time_trial" if state.total_laps == 0 else "practice"


@dataclass
class Session:
    session_id: str
    dir: Path
    started_at: float
    type: str
    track_id: int | None
    car_code: int
    total_laps: int
    fuel_at_start: float
    lap_start_fuel: float
    buffer: list[tuple[Any, ...]] = field(default_factory=list)
    laps: list[dict[str, Any]] = field(default_factory=list)
    track: dict[str, Any] | None = None  # detector verdict, see SessionStore.set_track
    kind: dict[str, Any] | None = None  # session kind, see SessionStore.set_kind
    fuel_burned: float = 0.0  # every drop added up, so a refuel does not cancel a stint
    last_fuel: float | None = None
    last_position: int | None = None  # a quit's last frame has no position
    last_cars: int | None = None  # nor a car count
    gt7_best_ms: int = 0  # GT7's own best, which leaves out a start lap
    pits: PitStatus = NO_STOPS  # see SessionStore.set_pits


class SessionStore:
    def __init__(
        self,
        data_dir: Path,
        clock: Any = time.time,
        on_end: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.on_end = on_end  # called with each summary once it is written
        self.data_dir = Path(data_dir)
        self.clock = clock
        self.session: Session | None = None
        self._lock: IO[bytes] | None = writer_lock(self.data_dir)  # raises StoreBusy
        self._db_lock = threading.Lock()  # the writer thread inserts lap rows
        try:
            self._db = connect_index(self.data_dir)
        except BaseException:
            self._lock.close()
            raise
        self._db.executescript(_SCHEMA)
        _ensure_column(self._db, "sessions", "track_confidence", "TEXT")
        _ensure_column(self._db, "sessions", "session_kind", "TEXT")
        _ensure_column(self._db, "sessions", "fuel_use", "INTEGER")
        _ensure_column(self._db, "sessions", "start_type", "TEXT")
        _ensure_column(self._db, "sessions", "posted_at", "REAL")
        _ensure_column(self._db, "sessions", "pit_stops", "INTEGER")
        _ensure_column(self._db, "laps", "pit", "TEXT")
        self._db.commit()
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lap-writer")
        self._pending: list[Future[float]] = []

    def close(self) -> None:
        self.wait()
        self._writer.shutdown(wait=True)
        with self._db_lock:
            self._db.close()
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def wait(self) -> None:
        """Block until every queued lap file has been written."""
        pending, self._pending = self._pending, []
        for fut in pending:
            with contextlib.suppress(Exception):  # already logged by _write_lap
                fut.result()

    @property
    def writes_pending(self) -> int:
        return sum(1 for f in self._pending if not f.done())

    def _write(self, sql: str, args: tuple[Any, ...]) -> None:
        """One statement, committed, under the connection's lock."""
        with self._db_lock:
            self._db.execute(sql, args)
            self._db.commit()

    # session lifecycle

    def start_session(self, state: RaceState) -> Session:
        base = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock()))
        session_id, n = base, 1
        while (self.data_dir / "sessions" / session_id).exists():
            n += 1
            session_id = f"{base}-{n}"
        sdir = self.data_dir / "sessions" / session_id
        sdir.mkdir(parents=True)
        self.session = Session(
            session_id=session_id,
            dir=sdir,
            started_at=self.clock(),
            type=session_type(state),
            track_id=None,  # set by the detector, see set_track
            car_code=state.car_code,
            total_laps=state.total_laps,
            fuel_at_start=state.fuel_level,
            lap_start_fuel=state.fuel_level,
        )
        self._write(
            "INSERT INTO sessions (id, started_at, type, track_id, car_code, total_laps)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                self.session.started_at,
                self.session.type,
                None,
                state.car_code,
                state.total_laps,
            ),
        )
        log.info(
            "session %s started (%s, %s, %s laps)",
            session_id,
            self.session.type,
            car_name(state.car_code) or "no car",
            state.total_laps,
        )
        return self.session

    def set_track(self, match: TrackMatch) -> None:
        """Record the track detector's verdict for the open session."""
        s = self.session
        if s is None:
            return
        s.track_id = match.track_id
        s.track = track_record(match)
        self._write(
            "UPDATE sessions SET track_id = ?, track_confidence = ? WHERE id = ?",
            (match.track_id, match.confidence, s.session_id),
        )

    def mark_posted(self, session_id: str, at: float | None = None) -> None:
        """Record that the session's results card reached Discord."""
        self._write(
            "UPDATE sessions SET posted_at = ? WHERE id = ?",
            (self.clock() if at is None else at, session_id),
        )

    def set_kind(self, kind: SessionKind) -> None:
        """Record the session kind for the open session."""
        s = self.session
        if s is None:
            return
        s.kind = kind.record()
        fuel = None if kind.fuel_use is None else int(kind.fuel_use)
        self._write(
            "UPDATE sessions SET session_kind = ?, fuel_use = ?, start_type = ? WHERE id = ?",
            (kind.kind, fuel, kind.start, s.session_id),
        )

    def set_pits(self, status: PitStatus) -> None:
        """Record the pit detector's view for the open session. Laps written from
        now on are marked with their part in a stop (in-lap, out-lap)."""
        s = self.session
        if s is None:
            return
        s.pits = status
        self._write(
            "UPDATE sessions SET pit_stops = ? WHERE id = ?", (len(status.stops), s.session_id)
        )

    def observe(self, prev: RaceState | None, state: RaceState) -> None:
        s = self.session
        if s is None:
            return
        if state.in_race or racing_frame(prev, state):
            s.buffer.append(frame_row(state))
            if s.last_fuel is not None and state.fuel_level < s.last_fuel:
                s.fuel_burned += s.last_fuel - state.fuel_level
            s.last_fuel = state.fuel_level
            if state.position is not None:
                s.last_position = state.position
            if state.total_cars > 0:
                s.last_cars = state.total_cars
            if state.best_lap_ms > 0:
                s.gt7_best_ms = state.best_lap_ms
        if lap_completed(prev, state):
            assert prev is not None
            self._flush_lap(prev.current_lap, state, complete=True)

    def _flush_lap(self, lap_no: int, state: RaceState, complete: bool) -> None:
        s = self.session
        if s is None or not s.buffer:
            return
        rows, s.buffer = s.buffer, []
        # The frame that closed the lap belongs to the next lap's buffer, unless
        # it was the chequered flag and there is no next lap.
        if complete and state.in_race and rows[-1][2] == state.current_lap and len(rows) > 1:
            s.buffer = [rows[-1]]
            rows = rows[:-1]
        path = s.dir / f"lap-{lap_no:02d}.parquet"
        lap = {
            "lap": lap_no,
            "lap_time_ms": state.last_lap_ms if complete and state.last_lap_ms > 0 else None,
            "complete": complete,
            "fuel_start": s.lap_start_fuel,
            "fuel_end": state.fuel_level,
            "fuel_used": round(s.lap_start_fuel - state.fuel_level, 3),
            "position": state.position,
            "pit": s.pits.lap_role(lap_no),
            "frames": len(rows),
            "file": path.name,
            "recorded_at": self.clock(),
        }
        s.lap_start_fuel = state.fuel_level
        s.laps.append(lap)
        lap_row = (
            s.session_id,
            lap_no,
            lap["lap_time_ms"],
            int(complete),
            lap["fuel_start"],
            lap["fuel_end"],
            lap["fuel_used"],
            lap["position"],
            lap["pit"],
            lap["frames"],
            lap["file"],
            lap["recorded_at"],
        )
        session_row = (sum(1 for x in s.laps if x["complete"]), s.track_id, s.session_id)
        fut = self._writer.submit(self._write_lap, path, rows, lap_row, session_row)
        self._pending.append(fut)

    def _write_lap(
        self,
        path: Path,
        rows: list[tuple[Any, ...]],
        lap_row: tuple[Any, ...],
        session_row: tuple[Any, ...],
    ) -> float:
        """On the writer thread: the lap file, then its index row. A lap whose
        file could not be written gets no row (summary.json still lists it).

        The outcome is logged here, before the future resolves, so it is in the
        log by the time ``wait()`` returns. (A done-callback runs after waiters
        are woken, so it could log late.)"""
        try:
            took = self._write_lap_and_row(path, rows, lap_row, session_row)
        except LapNotIndexed as exc:
            log.error("wrote %s (%d frames) but could not index it: %s", path, len(rows), exc)
            raise
        except Exception as exc:
            log.error("failed to write %s (%d frames): %s", path, len(rows), exc)
            raise
        log.info("wrote %s: %d frames in %.2fs", path.name, len(rows), took)
        return took

    def _write_lap_and_row(
        self,
        path: Path,
        rows: list[tuple[Any, ...]],
        lap_row: tuple[Any, ...],
        session_row: tuple[Any, ...],
    ) -> float:
        took = write_parquet(path, rows)
        try:
            with self._db_lock:
                self._db.execute(
                    "INSERT OR REPLACE INTO laps (session_id, lap, lap_time_ms, complete,"
                    " fuel_start, fuel_end, fuel_used, position, pit, frames, file, recorded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    lap_row,
                )
                self._db.execute(
                    "UPDATE sessions SET laps_completed = ?, track_id = COALESCE(track_id, ?)"
                    " WHERE id = ?",
                    session_row,
                )
                self._db.commit()
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error), self._db_lock:
                self._db.rollback()
            raise LapNotIndexed(str(exc)) from exc
        return took

    def end_session(self, state: RaceState, finished: bool = False) -> Path | None:
        """Close the open session. ``finished``: it ended at the line (the engine's
        timed-race finish); a FINISHED frame counts on its own."""
        s = self.session
        if s is None:
            return None
        if s.buffer:
            # Partial lap at the end of a session (quit, or the lap in progress).
            self._flush_lap(s.buffer[-1][2], state, complete=False)
        self.wait()  # the summary marks the session directory as complete
        completed = [x for x in s.laps if x["complete"]]
        times = [x["lap_time_ms"] for x in completed if x["lap_time_ms"]]
        gt7_best = s.gt7_best_ms or None
        finished = finished or state.phase is Phase.FINISHED
        summary = {
            "session_id": s.session_id,
            "type": s.type,
            "started_at": s.started_at,
            "ended_at": self.clock(),
            "track_id": s.track_id,
            "track": s.track,
            "session_kind": s.kind,
            "car_code": s.car_code,
            "car_name": car_name(s.car_code),
            "total_laps": s.total_laps,
            "laps_completed": len(completed),
            "best_lap_ms": session_best_lap(s.laps, s.kind, gt7_best),
            "fastest_lap_ms": min(times) if times else None,  # lap 1 from the grid too
            "finished": finished,  # the chequered flag, not a quit
            "total_time_ms": sum(times) if finished and times else None,
            "final_position": state.position or s.last_position,
            "total_cars": state.total_cars if state.total_cars > 0 else s.last_cars,
            "fuel_burned": round(s.fuel_burned, 3),
            "gt7_best_lap_ms": gt7_best,
            "fuel_capacity": state.fuel_capacity,
            "fuel_at_start": s.fuel_at_start,
            "fuel_at_end": state.fuel_level,
            "fuel_used": round(sum(x["fuel_used"] for x in s.laps), 3),
            **s.pits.record(),  # stints, pit_stops
            "laps": s.laps,
        }
        write_summary(s.dir / "summary.json", summary)
        self._write(
            "UPDATE sessions SET ended_at = ?, laps_completed = ?, best_lap_ms = ?, fuel_used = ?,"
            " final_position = ?, track_id = COALESCE(track_id, ?) WHERE id = ?",
            (
                summary["ended_at"],
                len(completed),
                summary["best_lap_ms"],
                summary["fuel_used"],
                summary["final_position"],
                s.track_id,
                s.session_id,
            ),
        )
        log.info("session %s ended after %d laps", s.session_id, len(completed))
        self.session = None
        if self.on_end is not None:
            try:
                self.on_end(summary)
            except Exception:  # noqa: BLE001
                log.exception("session end hook failed for %s", s.session_id)
        return s.dir / "summary.json"
