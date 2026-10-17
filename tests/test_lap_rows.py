"""A lap row in the index means its Parquet file is complete (#148)."""

import sqlite3
import threading

from those_who_run import store as store_mod
from those_who_run.callouts import CalloutQueue
from those_who_run.engine import Engine
from those_who_run.pitwall import data
from those_who_run.store import SessionStore


def lap_rows(path) -> list[tuple]:
    db = sqlite3.connect(path / "index.sqlite")
    try:
        return db.execute("SELECT lap, file FROM laps ORDER BY lap").fetchall()
    finally:
        db.close()


def test_no_lap_row_until_its_file_is_written(tmp_path, sim, monkeypatch):
    gate = threading.Event()
    real = store_mod.write_parquet

    def slow(path, rows):
        assert gate.wait(5)
        return real(path, rows)

    monkeypatch.setattr(store_mod, "write_parquet", slow)
    store = SessionStore(tmp_path)
    engine = Engine([], CalloutQueue(max_age=None), store)
    for f in sim(total_laps=3).menu().at_track().race([100000], finish=False).frames:
        engine.process(f)
    assert store.writes_pending == 1
    assert lap_rows(tmp_path) == []  # lap 1 closed, its file not written yet
    gate.set()
    store.wait()
    ((lap, file),) = lap_rows(tmp_path)
    assert lap == 1 and (store.session.dir / file).exists()
    store.close()


def test_a_failed_lap_write_leaves_no_row(tmp_path, sim, monkeypatch):
    def broken(path, rows):
        raise OSError("disk full")

    monkeypatch.setattr(store_mod, "write_parquet", broken)
    store = SessionStore(tmp_path)
    engine = Engine([], CalloutQueue(max_age=None), store)
    for f in sim(total_laps=3).menu().at_track().race([100000], finish=False).frames:
        engine.process(f)
    store.wait()
    assert lap_rows(tmp_path) == []
    store.close()


def test_every_lap_the_pit_wall_lists_has_a_top_speed(tmp_path, sim, monkeypatch):
    real = store_mod.write_parquet
    seen: list[list[data.LapRow]] = []
    sessions: list[str] = []

    def watching(path, rows):
        # What the pit wall shows at the moment a lap closes, before its file exists.
        if sessions:
            seen.append(data.lap_summaries(tmp_path, sessions[0]))
        return real(path, rows)

    monkeypatch.setattr(store_mod, "write_parquet", watching)
    store = SessionStore(tmp_path)
    engine = Engine([], CalloutQueue(max_age=None), store)
    for f in sim(total_laps=3).menu().at_track().race([100000, 99000, 99500]).frames:
        engine.process(f)
        if store.session is not None and not sessions:
            sessions.append(store.session.session_id)
        store.wait()  # each lap's row is in as soon as its writer returns
        if sessions and (laps := data.lap_summaries(tmp_path, sessions[0])):
            assert laps[-1].top_speed_kph is not None
    store.close()
    assert [len(s) for s in seen] == [0, 1, 2]
    assert all(r.top_speed_kph is not None for laps in seen for r in laps)
    final = data.lap_summaries(tmp_path, sessions[0])
    assert [r.lap for r in final] == [1, 2, 3]
    assert all(r.top_speed_kph is not None for r in final)


def test_a_failed_row_insert_is_logged_as_that_not_as_a_failed_write(tmp_path, sim, caplog):
    store = SessionStore(tmp_path)
    store._db.execute("DROP TABLE laps")  # the insert fails; the Parquet write does not
    store._db.commit()
    engine = Engine([], CalloutQueue(max_age=None), store)
    for f in sim(total_laps=3).menu().at_track().race([100000], finish=False).frames:
        engine.process(f)
    store.wait()
    assert (store.session.dir / "lap-01.parquet").exists()
    (msg,) = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert "could not index it" in msg and "failed to write" not in msg
    store.close()
