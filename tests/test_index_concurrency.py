"""The index shared between the engineer, the pit wall and backfill (#147)."""

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from those_who_run import tracktools
from those_who_run.callouts import CalloutQueue
from those_who_run.engine import Engine
from those_who_run.pitwall import data
from those_who_run.store import SessionStore, StoreBusy
from those_who_run.trackdetect import TrackMatch
from those_who_run.tracktools import backfill

T0 = 1_792_000_000.0


def drive(store: SessionStore, frames, at: float, clock: list[float]) -> Engine:
    first = frames[0].t
    engine = Engine([], CalloutQueue(max_age=None), store)
    for f in frames:
        clock[0] = at + f.t - first
        engine.process(f)
    return engine


def open_store(path: Path) -> tuple[SessionStore, list[float]]:
    clock = [T0]
    return SessionStore(path, clock=lambda: clock[0]), clock


def test_a_reader_holding_a_transaction_does_not_block_a_lap_commit(tmp_path, sim):
    store, clock = open_store(tmp_path)
    s = sim(total_laps=3).menu().at_track()
    s.race([100000], finish=False)
    engine = drive(store, s.frames, T0, clock)
    store.wait()  # session open, lap 1 committed (by the writer thread, #148)
    reader = data.open_index(tmp_path)
    assert reader is not None
    reader.execute("BEGIN")
    assert reader.execute("SELECT count(*) FROM laps").fetchone()[0] == 1

    store._db.execute("PRAGMA busy_timeout = 100")  # fail fast if the commit had to wait
    started = time.monotonic()
    store.end_session(engine.prev)  # commits the partial lap and the session's end
    assert time.monotonic() - started < 1.0
    # The reader still sees its snapshot; a new one sees the commit.
    assert reader.execute("SELECT count(*) FROM laps").fetchone()[0] == 1
    reader.rollback()
    assert reader.execute("SELECT count(*) FROM laps").fetchone()[0] == 2
    reader.close()
    store.close()


def test_a_read_succeeds_while_a_write_transaction_is_open(tmp_path, sim):
    store, clock = open_store(tmp_path)
    drive(store, sim(total_laps=3).menu().at_track().race([100000], finish=False).frames, T0, clock)
    store._db.execute("UPDATE sessions SET best_lap_ms = 1")  # left uncommitted
    assert store._db.in_transaction
    rows = data.list_sessions(tmp_path)
    assert len(rows) == 1
    store._db.rollback()
    store.close()


def test_an_index_from_before_wal_is_converted_on_open(tmp_path):
    db = sqlite3.connect(tmp_path / "index.sqlite")
    db.execute("CREATE TABLE t (x)")
    db.commit()
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    db.close()
    SessionStore(tmp_path).close()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()


def test_index_stamp_changes_after_a_lap_commit(tmp_path, sim):
    store, clock = open_store(tmp_path)
    s = sim(total_laps=3).menu().at_track()
    s.race([100000], finish=False)
    engine = drive(store, s.frames, T0, clock)
    assert (tmp_path / "index.sqlite-wal").exists()
    before = data.index_stamp(tmp_path)
    main_before = (tmp_path / "index.sqlite").stat().st_mtime
    time.sleep(0.02)  # past the file system's timestamp granularity
    store.end_session(engine.prev)
    assert data.index_stamp(tmp_path) > before
    # The commit went to the WAL; the main file alone would not have shown it.
    assert (tmp_path / "index.sqlite").stat().st_mtime == main_before
    store.close()


def test_backfill_refuses_while_a_store_is_open(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(StoreBusy):
        backfill(tmp_path)
    store.close()
    assert backfill(tmp_path) == []


def test_backfill_refuses_while_an_engineer_in_another_process_is_live(tmp_path):
    hold = (
        "import sys, time; from those_who_run.store import SessionStore;"
        " s = SessionStore(sys.argv[1]); print('open', flush=True); time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", hold, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "open"
        with pytest.raises(StoreBusy):
            backfill(tmp_path)
    finally:
        proc.kill()
        proc.wait()
    assert backfill(tmp_path) == []  # the lock went with the process


def test_a_second_store_is_refused_while_the_engineer_runs(tmp_path):
    engineer = SessionStore(tmp_path)
    with pytest.raises(StoreBusy, match="use the pit wall"):
        SessionStore(tmp_path)
    engineer.close()
    SessionStore(tmp_path).close()  # the engineer stopped: the next writer gets the lock


def test_the_engineer_refuses_to_start_while_a_backfill_runs(tmp_path, monkeypatch, capsys):
    from those_who_run.__main__ import main
    from those_who_run.store import exclusive_store

    with exclusive_store(tmp_path), pytest.raises(StoreBusy):
        SessionStore(tmp_path)
    for name, value in (
        ("GT7_DATA_DIR", str(tmp_path)),
        ("GT7_PS5_IP", "192.0.2.1"),
        ("DISCORD_BOT_TOKEN", "x"),
        ("DISCORD_VOICE_CHANNEL_ID", "1"),
    ):
        monkeypatch.setenv(name, value)
    with exclusive_store(tmp_path):
        assert main(["run"]) == 1  # before any socket or Discord connection is opened
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("those-who-run run: ")


def test_post_and_backfill_from_the_cli_are_refused_while_the_engineer_runs(
    tmp_path, monkeypatch, capsys, sim
):
    from those_who_run.__main__ import main

    store, clock = open_store(tmp_path)
    e = drive(
        store, sim(total_laps=3).menu().at_track().race([100000, 99000, 99500]).frames, T0, clock
    )
    store.end_session(e.prev)
    session_id = next((tmp_path / "sessions").iterdir()).name
    store.close()
    for name, value in (
        ("GT7_DATA_DIR", str(tmp_path)),
        ("DISCORD_BOT_TOKEN", "x"),
        ("DISCORD_RESULTS_CHANNEL_ID", "1"),
    ):
        monkeypatch.setenv(name, value)
    engineer = SessionStore(tmp_path)
    try:
        assert main(["tracks", "backfill"]) == 1
        assert "those-who-run tracks: " in capsys.readouterr().err
        assert main(["post", session_id]) == 1  # refused before logging in to Discord
        assert "those-who-run post: " in capsys.readouterr().err
    finally:
        engineer.close()
    assert main(["tracks", "backfill"]) == 0


def test_the_pit_wall_reads_while_the_engineer_holds_the_lock(tmp_path, sim):
    store, clock = open_store(tmp_path)
    drive(store, sim(total_laps=3).menu().at_track().race([100000], finish=False).frames, T0, clock)
    assert len(data.list_sessions(tmp_path)) == 1
    store.close()


def test_backfill_commits_each_session_before_detecting_the_next(tmp_path, sim, monkeypatch):
    store, clock = open_store(tmp_path)
    for i in range(2):
        e = drive(store, sim(total_laps=3).menu().at_track().race([100000]).frames, T0 + i, clock)
        store.end_session(e.prev)
    store.close()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    db.execute("UPDATE sessions SET track_id = NULL, track_confidence = NULL")
    db.commit()
    db.close()
    seen: list[list[tuple]] = []

    def detect(session_dir):
        # What another connection sees while the detector runs.
        db = sqlite3.connect(tmp_path / "index.sqlite")
        seen.append(db.execute("SELECT track_confidence FROM sessions ORDER BY id").fetchall())
        db.close()
        return TrackMatch(7, "Somewhere", "probable", (), "test"), []

    monkeypatch.setattr(tracktools, "detect_session", detect)
    results = backfill(tmp_path)
    assert [r.updated for r in results] == [True, True]
    assert seen == [[(None,), (None,)], [("probable",), (None,)]]
