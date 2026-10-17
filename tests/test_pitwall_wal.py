"""ADR 0001 (#194): how the pit wall opens the index once it is in WAL mode.

The pit wall mounts ``/data`` read-write, with ``sessions/`` read-only, and opens
the index with ``mode=ro``. These tests pin why: a WAL reader needs to create the
``-shm`` file, which the engineer removes when it closes cleanly.
"""

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.pitwall import data
from those_who_run.rules import build_rules
from those_who_run.store import SessionStore

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes"
)


def stopped_engineer_store(tmp_path: Path, sim) -> Path:
    """A finished race written by the engineer's store in WAL mode, then closed."""
    store = SessionStore(tmp_path)
    # #147 makes the store set this itself; setting it again is harmless.
    store._db.execute("PRAGMA journal_mode=WAL")
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    race = sim(total_laps=2, fuel=100, burn=5).menu().at_track()
    race.race([100000, 99000])
    for f in race.frames:
        engine.process(f)
    if store.session is not None and engine.prev is not None:
        store.end_session(engine.prev)
    store.close()
    return tmp_path


def read_only(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        mode = p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        p.chmod(mode)


def writable(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_wal_index_survives_a_clean_close(tmp_path, sim):
    root = stopped_engineer_store(tmp_path, sim)
    db = sqlite3.connect(root / "index.sqlite")
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()


@needs_non_root
def test_pit_wall_reads_the_index_with_the_engineer_stopped(tmp_path, sim):
    """The decided layout: /data writable, sessions/ read-only, index opened mode=ro."""
    root = stopped_engineer_store(tmp_path, sim)
    assert not (root / "index.sqlite-shm").exists(), "a clean close removes the -shm file"
    read_only(root / "sessions")
    try:
        rows = data.list_sessions(root)
        assert len(rows) == 1 and rows[0].closed
        laps = data.lap_summaries(root, rows[0].session_id)
        assert [lap.lap for lap in laps] == [1, 2]
        db = data.open_index(root)
        assert db is not None
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM sessions")
        db.close()
    finally:
        writable(root / "sessions")


@needs_non_root
def test_a_read_only_mount_cannot_open_a_wal_index_once_the_engineer_stops(tmp_path, sim):
    """Why the pit wall does not mount all of /data read-only (sqlite.org/wal.html)."""
    root = stopped_engineer_store(tmp_path, sim)
    read_only(root)
    try:
        with pytest.raises(sqlite3.OperationalError):
            data.list_sessions(root)
    finally:
        writable(root)
