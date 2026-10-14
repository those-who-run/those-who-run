import json
import sqlite3

import duckdb

from gt7_race_engineer.audio.player import ConsolePlayer
from gt7_race_engineer.callouts import CalloutQueue
from gt7_race_engineer.engine import Engine
from gt7_race_engineer.replay import replay
from gt7_race_engineer.state import RaceState
from gt7_race_engineer.store import FRAME_COLUMNS, SessionStore, frame_row
from tests.conftest import make_state


def test_frame_row_matches_columns():
    row = frame_row(make_state(pos_x=1.5, throttle=200, car_code=42))
    assert len(row) == len(FRAME_COLUMNS)
    named = dict(zip([c for c, _ in FRAME_COLUMNS], row, strict=True))
    assert named["pos_x"] == 1.5 and named["throttle"] == 200 and named["car_code"] == 42


async def test_store_writes_parquet_and_index(tmp_path, sim):
    frames = (
        sim(total_laps=3, fuel=100, burn=5).menu().at_track().race([100000, 99000, 99500]).frames
    )
    store = SessionStore(tmp_path)
    engine = Engine([], CalloutQueue(max_age=None), store)
    await replay(frames, engine, ConsolePlayer())
    store.close()

    (session_dir,) = (tmp_path / "sessions").iterdir()
    files = sorted(p.name for p in session_dir.glob("*.parquet"))
    assert files == ["lap-01.parquet", "lap-02.parquet", "lap-03.parquet"]

    con = duckdb.connect()
    total = con.execute(f"SELECT count(*) FROM '{session_dir}/lap-*.parquet'").fetchone()[0]
    assert total == sum(1 for f in frames if f.in_race or f.phase.value == "finished")
    laps = con.execute(
        f"SELECT lap, count(*), min(fuel_level), max(fuel_level) FROM '{session_dir}/lap-*.parquet'"
        " GROUP BY lap ORDER BY lap"
    ).fetchall()
    # the chequered-flag frame reports lap 4 of 3 and is stored with lap 3's file
    assert [lap for lap, *_ in laps] == [1, 2, 3, 4]
    per_file = con.execute(
        f"SELECT count(*) FROM '{session_dir}/lap-03.parquet' WHERE lap = 4"
    ).fetchone()[0]
    assert per_file == 1
    cols = {
        r[0]
        for r in con.execute(f"DESCRIBE SELECT * FROM '{session_dir}/lap-01.parquet'").fetchall()
    }
    assert {"pos_x", "throttle", "brake", "tire_fl_radius", "car_code", "position"} <= cols

    db = sqlite3.connect(tmp_path / "index.sqlite")
    sess = db.execute(
        "SELECT type, total_laps, laps_completed, best_lap_ms, fuel_used, ended_at FROM sessions"
    ).fetchall()
    assert sess == [("race", 3, 3, 99000, 15.0, sess[0][5])] and sess[0][5] is not None
    rows = db.execute(
        "SELECT lap, lap_time_ms, complete, fuel_used, file FROM laps ORDER BY lap"
    ).fetchall()
    assert rows == [
        (1, 100000, 1, 5.0, "lap-01.parquet"),
        (2, 99000, 1, 5.0, "lap-02.parquet"),
        (3, 99500, 1, 5.0, "lap-03.parquet"),
    ]
    summary = json.loads((session_dir / "summary.json").read_text())
    assert summary["type"] == "race" and summary["laps_completed"] == 3


async def test_quit_mid_lap_keeps_partial_lap(tmp_path, sim):
    s = sim(total_laps=5)
    s.race([100000], finish=False)  # one lap done, then quit during lap 2
    s.menu()
    store = SessionStore(tmp_path)
    await replay(s.frames, Engine([], CalloutQueue(max_age=None), store), ConsolePlayer())
    store.close()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    rows = db.execute("SELECT lap, complete, lap_time_ms FROM laps ORDER BY lap").fetchall()
    assert rows == [(1, 1, 100000), (2, 0, None)]
    assert db.execute("SELECT laps_completed FROM sessions").fetchone() == (1,)


def test_v1_recording_still_loads():
    v1 = {
        "v": 1,
        "t": 0.0,
        "packet_id": 1,
        "phase": "in_race",
        "current_lap": 1,
        "total_laps": 2,
        "best_lap_ms": -1,
        "last_lap_ms": -1,
        "fuel_level": 50.0,
        "fuel_capacity": 100.0,
        "speed_kph": 100.0,
        "engine_rpm": 5000.0,
        "tire_temp": [1, 2, 3, 4],
        "water_temp": 90.0,
        "oil_temp": 95.0,
        "track_id": None,
        "race_start_pos": 3,
        "total_cars": 16,
    }
    s = RaceState.from_dict(v1)
    assert s.pos_x == 0.0 and s.tire_radius == (0.0, 0.0, 0.0, 0.0) and s.car_code == 0
    d = s.to_dict()
    assert d["v"] == 2 and RaceState.from_dict(d) == s
