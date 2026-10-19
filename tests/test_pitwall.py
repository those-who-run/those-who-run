"""Pit wall phase 1 (#33): the data layer over a store built in tmp_path, and the page."""

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from those_who_run.__main__ import build_parser
from those_who_run.callouts import CalloutQueue
from those_who_run.cli.web import streamlit_flags
from those_who_run.config import DEFAULT_RULES, Settings
from those_who_run.engine import Engine
from those_who_run.pitwall import data
from those_who_run.replay import read_recording
from those_who_run.rules import build_rules
from those_who_run.store import SessionStore

FIXTURES = Path(__file__).parent / "fixtures"
DAY = 86400.0
T0 = datetime(2026, 10, 15, 18, 0, tzinfo=UTC).timestamp()


def drive(tmp_path: Path, frames, at: float = T0, close: bool = True) -> None:
    """Run frames through an engine into the store at ``tmp_path``, starting at ``at``."""
    first = frames[0].t
    clock = [at]
    store = SessionStore(tmp_path, clock=lambda: clock[0])
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    for f in frames:
        clock[0] = at + f.t - first
        engine.process(f)
    if close and store.session is not None and engine.prev is not None:
        store.end_session(engine.prev)
    store.close()


@pytest.fixture
def store_dir(tmp_path, sim):
    """A race with a pit stop after lap 2, a time trial a day later, then one still open."""
    race = sim(total_laps=4, fuel=100, burn=5).menu().at_track()
    race.race([100000, 101000, 99500, 99800], refuel_after_lap=2)
    drive(tmp_path, race.frames)
    tt = sim(total_laps=0, cars=1, position=1, burn=0, is_race=True).menu().at_track()
    tt.race([70000, 69000], finish=False).menu()
    drive(tmp_path, tt.frames, at=T0 + DAY)
    live = sim(total_laps=5, burn=5).menu().at_track().race([98000], finish=False)
    drive(tmp_path, live.frames, at=T0 + 2 * DAY, close=False)
    return tmp_path


def test_sessions_are_listed_newest_first_with_the_card_facts(store_dir):
    rows = data.list_sessions(store_dir)
    assert [r.kind for r in rows] == ["lap_race", "solo_timed", "lap_race"]
    live, tt, race = rows
    assert race.closed and race.title == "Unknown track · 4-lap race"
    assert race.result.startswith("🚩 Finished")
    assert dict(race.facts)["Best lap"] == "1:39.500 (lap 3)"
    assert tt.result == "2 laps" and tt.kind_name == "time trial or practice"
    # The engineer has not closed it: listed from the index, not "retired".
    assert not live.closed and live.ended_at is None
    assert live.result == "Running, 1 lap" and live.laps_completed == 1


def test_filters(store_dir):
    rows = data.list_sessions(store_dir)
    opts = data.filter_options(rows)
    assert opts["kind"] == ["lap_race", "solo_timed"] and opts["track"] == ["Unknown track"]
    pick = data.filter_sessions
    assert len(pick(rows, data.SessionFilter(kind="lap_race"), UTC)) == 2
    assert [r.kind for r in pick(rows, data.SessionFilter(since=date(2026, 10, 16)), UTC)] == [
        "lap_race",
        "solo_timed",
    ]
    one_day = data.SessionFilter(since=date(2026, 10, 16), until=date(2026, 10, 16))
    assert [r.kind for r in pick(rows, one_day, UTC)] == ["solo_timed"]
    assert pick(rows, data.SessionFilter(car="Nope"), UTC) == []
    assert pick(rows, data.SessionFilter(track="Unknown track"), UTC) == rows


def test_filter_by_track_and_car():
    def row(track: str, car: str | None) -> data.SessionRow:
        return data.SessionRow("x", T0, None, track, "lap_race", car, "", "", (), 1, True)

    rows = [row("Suzuka", "Civic"), row("SUGO", "Civic"), row("Suzuka", None)]
    got = data.filter_sessions(rows, data.SessionFilter(track="Suzuka", car="Civic"))
    assert got == rows[:1]
    assert data.filter_options(rows)["car"] == ["Civic"]


def test_option_counts_use_the_other_filters():
    """#318 R3: an option counts what it would leave with the other filters,
    never its own, so a choice that empties the list shows 0."""

    def row(track: str, kind: str, car: str | None, day: int) -> data.SessionRow:
        return data.SessionRow("x", T0 + day * DAY, None, track, kind, car, "", "", (), 1, True)

    rows = [
        row("Suzuka", "lap_race", "Civic", 0),
        row("Suzuka", "solo_timed", "Civic", 0),
        row("SUGO", "lap_race", "GR86", 1),
        row("SUGO", "lap_race", None, 2),
    ]
    races = data.SessionFilter(kind="lap_race")
    counts = data.option_counts(rows, races, UTC)
    assert counts["track"] == {"SUGO": 2, "Suzuka": 1}  # lap races per track
    assert counts["kind"] == {"lap_race": 3, "solo_timed": 1}  # not its own filter
    assert counts["car"] == {"Civic": 1, "GR86": 1}

    f = data.SessionFilter(track="Suzuka", kind="lap_race", since=date(2026, 10, 16))
    counts = data.option_counts(rows, f, UTC)
    assert counts["track"] == {"SUGO": 2, "Suzuka": 0}
    assert counts["kind"] == {"lap_race": 0, "solo_timed": 0}
    assert counts["car"] == {"Civic": 0, "GR86": 0}
    assert data.option_counts(rows, data.SessionFilter(), UTC)["car"] == {"Civic": 2, "GR86": 1}


def test_lap_table_follows_the_pit_detector(store_dir):
    """The sim tops the fuel up after lap 2 without GT7's pit cut-scenes: the pit-stop
    detector (#20) sees no stop, and the table follows it."""
    race = data.list_sessions(store_dir)[-1]
    laps = data.lap_summaries(store_dir, race.session_id)
    assert [(r.lap, r.time, r.flags) for r in laps] == [
        (1, "1:40.000", ""),
        (2, "1:41.000", ""),
        (3, "1:39.500", "best"),
        (4, "1:39.800", ""),
    ]
    assert laps[0].fuel_used == 5.0 and laps[0].top_speed_kph == 150.0
    assert laps[0].position == 5  # a flagged field


def test_lap_table_partial_lap_and_no_position_in_a_time_trial(store_dir):
    tt = data.list_sessions(store_dir)[1]
    laps = data.lap_summaries(store_dir, tt.session_id)
    assert [(r.lap, r.flags) for r in laps] == [(1, ""), (2, "best"), (3, "partial")]
    assert laps[-1].invalid and not laps[-1].complete
    assert all(r.position is None for r in laps)
    assert not any(r.pit or r.out_lap for r in laps)


def test_real_pit_stop_is_flagged(tmp_path):
    frames = list(
        read_recording(FIXTURES / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz", strict=True)
    )
    drive(tmp_path, frames)
    (row,) = data.list_sessions(tmp_path)
    laps = data.lap_summaries(tmp_path, row.session_id)
    # The detector's in-lap and out-lap (#20): in on lap 3, out on lap 4.
    assert [r.lap for r in laps if r.pit] == [3]
    assert [r.lap for r in laps if r.out_lap] == [4]


def test_sessions_from_before_the_pit_detector_fall_back_to_the_refuel(store_dir):
    race = data.list_sessions(store_dir)[-1]
    sdir = store_dir / "sessions" / race.session_id
    summary = json.loads((sdir / "summary.json").read_text())
    summary.pop("pit_stops", None)
    summary.pop("stints", None)
    (sdir / "summary.json").write_text(json.dumps(summary))
    db = sqlite3.connect(store_dir / "index.sqlite")
    db.execute("UPDATE laps SET pit = NULL")
    db.commit()
    db.close()
    laps = data.lap_summaries(store_dir, race.session_id)
    assert [(r.lap, r.flags) for r in laps] == [
        (1, ""),
        (2, "pit"),  # fuel went from 95 to 100 over the lap
        (3, "best, out"),
        (4, ""),
    ]


def test_lap_trace_is_thinned_and_starts_at_zero(store_dir):
    race = data.list_sessions(store_dir)[-1]
    tr = data.lap_trace(store_dir, race.session_id, 1)
    assert tr is not None and len(tr) >= 2
    assert tr.t[0] == 0.0
    assert tr.speed_kph[0] == 150.0 and tr.rpm[0] == 6000.0
    assert all(0 <= v <= 100 for v in tr.throttle_pct + tr.brake_pct)
    # The sim's frames are a second apart: each gap counts as MAX_STEP_SECS.
    assert tr.t[1] == pytest.approx(data.MAX_STEP_SECS)
    thin = data.lap_trace(store_dir, race.session_id, 1, max_points=1)
    assert thin is not None and len(thin) == 1
    assert data.lap_trace(store_dir, race.session_id, 99) is None


def test_reads_only(store_dir, tmp_path_factory):
    db = data.open_index(store_dir)
    assert db is not None
    with pytest.raises(sqlite3.OperationalError):
        db.execute("DELETE FROM sessions")
    db.close()
    empty = tmp_path_factory.mktemp("empty")
    assert data.list_sessions(empty) == [] and data.index_stamp(empty) == 0.0
    assert not (empty / "index.sqlite").exists(), "the pit wall never creates the index"


def test_session_ids_cannot_leave_the_store(store_dir):
    with pytest.raises(ValueError):
        data.lap_summaries(store_dir, "../etc")
    assert data.session_summary(store_dir, "20990101-000000") is None


def test_web_command():
    args = build_parser().parse_args(["web"])
    assert args.command == "web" and args.port is None and args.address == "0.0.0.0"
    assert build_parser().parse_args(["web", "--port", "9000"]).port == 9000
    assert Settings.from_env({}).web_port == 8501
    assert Settings.from_env({"GT7_WEB_PORT": "8600"}).web_port == 8600
    flags = streamlit_flags(8600, "0.0.0.0")
    assert "--server.port=8600" in flags and "--server.headless=true" in flags
    assert "--theme.primaryColor=#D21F1B" in flags


def test_page_renders_both_views(store_dir, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    import those_who_run.pitwall as pitwall

    monkeypatch.setenv("GT7_DATA_DIR", str(store_dir))
    script = str(Path(pitwall.__file__).with_name("app.py"))
    at = testing.AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception
    assert "**Unknown track · 4-lap race**" in [m.value for m in at.markdown]

    race = data.list_sessions(store_dir)[-1]
    at.query_params["session"] = race.session_id
    at.run()
    assert not at.exception
    assert len(at.dataframe[0].value) == 4
    assert [s.label for s in at.selectbox] == ["Lap A", "Lap B"]
    assert at.selectbox[0].value == 3  # the best lap


# old stores, same-track matching and errors (#160)


def _drop_columns(store_dir: Path, table: str, *cols: str) -> None:
    db = sqlite3.connect(store_dir / "index.sqlite")
    for col in cols:
        db.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    db.commit()
    db.close()


def test_old_index_reads_every_column_it_has(store_dir):
    """An index from before the session kind columns and the pit-stop detector:
    ``fuel_used`` is read as it is, not taken for ``fuel_use`` (#160)."""
    race = data.list_sessions(store_dir)[-1]
    (store_dir / "sessions" / race.session_id / "summary.json").unlink()  # read the index
    before = data.session_summary(store_dir, race.session_id)
    assert before is not None and before["fuel_used"] == 10.0
    _drop_columns(store_dir, "sessions", "track_confidence", "session_kind", "fuel_use")
    _drop_columns(store_dir, "sessions", "start_type")
    _drop_columns(store_dir, "laps", "pit")
    after = data.session_summary(store_dir, race.session_id)
    assert after is not None and after["fuel_used"] == 10.0
    assert after["session_kind"] is None
    assert [r.lap for r in data.lap_summaries(store_dir, race.session_id)] == [1, 2, 3, 4]
    assert len(data.list_sessions(store_dir)) == 3


def _row(session_id: str, track_id: int | None, track: str = "Unknown track") -> data.SessionRow:
    return data.SessionRow(session_id, T0, None, track, "lap_race", None, "", "", (), 1, True,
                           track_id)  # fmt: skip


def test_same_track_needs_a_track_id(store_dir):
    rows = data.list_sessions(store_dir)
    assert all(r.track == "Unknown track" and r.track_id is None for r in rows)
    assert data.same_track_sessions(rows[0], rows) == []  # two unknowns are not the same
    suzuka = [_row("a", 351, "Suzuka"), _row("b", 351, "Suzuka"), _row("c", 352, "Suzuka")]
    assert data.same_track_sessions(suzuka[0], suzuka) == [suzuka[1]]


def test_track_id_only_when_the_detector_is_sure():
    assert data.sure_track_id({"id": 351, "confidence": "confirmed"}) == 351
    assert data.sure_track_id({"id": 351, "confidence": "probable"}) == 351
    assert data.sure_track_id({"id": 351, "confidence": "ambiguous"}) is None
    assert data.sure_track_id({"id": None, "confidence": "none"}) is None
    assert data.sure_track_id(None) is None


def test_real_sessions_at_one_track_match(tmp_path):
    frames = list(
        read_recording(FIXTURES / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz", strict=True)
    )
    drive(tmp_path, frames)
    drive(tmp_path, frames, at=T0 + DAY)
    a, b = data.list_sessions(tmp_path)
    assert a.track_id is not None and a.track_id == b.track_id
    assert data.same_track_sessions(a, [a, b]) == [b]


def test_old_and_new_lap_files_read_together(store_dir):
    """Laps from before 0.3 have no rotation columns; a session can hold both."""
    import duckdb

    race = data.list_sessions(store_dir)[-1]
    old = store_dir / "sessions" / race.session_id / "lap-03.parquet"  # after a new one
    tmp = old.with_suffix(".old.parquet")
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT * EXCLUDE (rot_x, rot_y, rot_z, orientation, ang_vel_x, ang_vel_y,"
        f" ang_vel_z) FROM read_parquet('{old}')) TO '{tmp}' (FORMAT PARQUET)"
    )
    con.close()
    tmp.replace(old)
    laps = data.lap_summaries(store_dir, race.session_id)
    assert [r.top_speed_kph for r in laps] == [150.0] * 4


def _app(store_dir: Path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    import those_who_run.pitwall as pitwall

    monkeypatch.setenv("GT7_DATA_DIR", str(store_dir))
    script = str(Path(pitwall.__file__).with_name("app.py"))
    return testing.AppTest.from_file(script, default_timeout=60)


def test_page_renders_an_empty_data_dir(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch).run()
    assert not at.exception
    assert any("No sessions" in i.value for i in at.info)


@pytest.mark.parametrize("session_id", ["../etc", "20990101-000000"])
def test_page_shows_an_error_for_a_bad_session_link(store_dir, monkeypatch, session_id):
    at = _app(store_dir, monkeypatch)
    at.query_params["session"] = session_id
    at.run()
    assert not at.exception
    assert len(at.error) == 1


def test_page_shows_an_error_for_a_corrupt_lap_file(store_dir, monkeypatch):
    race = data.list_sessions(store_dir)[-1]
    (store_dir / "sessions" / race.session_id / "lap-02.parquet").write_bytes(b"not parquet")
    at = _app(store_dir, monkeypatch)
    at.query_params["session"] = race.session_id
    at.run()
    assert not at.exception
    assert len(at.error) == 1 and "Could not read the store" in at.error[0].value


def test_page_shows_an_error_for_a_locked_index(store_dir, monkeypatch):
    # In WAL mode readers go past a writer's transaction; only exclusive locking
    # mode shuts them out.
    monkeypatch.setattr(data, "READ_TIMEOUT_SECS", 0.1)
    db = sqlite3.connect(store_dir / "index.sqlite")
    db.execute("PRAGMA locking_mode=EXCLUSIVE")
    db.execute("BEGIN EXCLUSIVE")
    try:
        at = _app(store_dir, monkeypatch).run()
    finally:
        db.rollback()
        db.close()
    assert not at.exception
    assert len(at.error) == 1 and "Could not read the store" in at.error[0].value


def test_lap_picks_survive_a_new_lap(tmp_path, monkeypatch, sim):
    live = sim(total_laps=6, burn=5).menu().at_track().race([98000, 97000, 99000], finish=False)
    drive(tmp_path, live.frames, close=False)
    (row,) = data.list_sessions(tmp_path)
    at = _app(tmp_path, monkeypatch)
    at.query_params["session"] = row.session_id
    at.run()
    assert [s.value for s in at.selectbox] == [2, 1]  # best, then the next quickest
    at.selectbox[0].set_value(3)
    at.selectbox[1].set_value(2)
    at.run()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    db.execute(
        "INSERT INTO laps (session_id, lap, lap_time_ms, complete, frames, file, recorded_at)"
        " VALUES (?, 4, 96000, 1, 3, 'lap-04.parquet', ?)",
        (row.session_id, T0),
    )
    db.commit()
    db.close()
    at.run()
    assert not at.exception
    assert at.selectbox[0].options[-1].startswith("Lap 4")
    assert [s.value for s in at.selectbox] == [3, 2]
