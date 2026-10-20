"""replay never writes into the live data directory (#145)."""

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from those_who_run.__main__ import build_parser, main

FIXTURE = Path(__file__).parent / "fixtures" / "real-race-2laps-2026-10-14.jsonl.gz"


def test_replay_leaves_the_data_directory_untouched(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setenv("GT7_DATA_DIR", str(live))
    assert main(["replay", str(FIXTURE)]) == 0
    assert list(live.iterdir()) == []
    assert not [t for t in threading.enumerate() if t.name.startswith("lap-writer")]


def test_replay_store_writes_a_complete_store(tmp_path, monkeypatch):
    live = tmp_path / "live"
    out = tmp_path / "out"
    monkeypatch.setenv("GT7_DATA_DIR", str(live))
    assert main(["replay", str(FIXTURE), "--store", str(out)]) == 0
    assert not live.exists()
    sessions = sorted((out / "sessions").iterdir())
    assert sessions
    for sdir in sessions:
        summary = json.loads((sdir / "summary.json").read_text())
        assert summary["ended_at"] is not None
    db = sqlite3.connect(out / "index.sqlite")
    rows = db.execute("SELECT id, ended_at FROM sessions").fetchall()
    db.close()
    assert sorted(r[0] for r in rows) == [p.name for p in sessions]
    assert all(ended is not None for _, ended in rows)
    assert not [t for t in threading.enumerate() if t.name.startswith("lap-writer")]


def test_replay_store_flag_parses():
    args = build_parser().parse_args(["replay", "x.jsonl", "--store", "dbg"])
    assert args.store == Path("dbg")
    assert build_parser().parse_args(["replay", "x.jsonl"]).store is None


def test_replay_store_ends_a_session_still_open_when_the_recording_stops(tmp_path, monkeypatch):
    from those_who_run.replay import read_recording, write_recording
    from those_who_run.state import Phase

    frames = list(read_recording(FIXTURE))
    first_racing = next(i for i, f in enumerate(frames) if f.phase is Phase.IN_RACE and i > 100)
    cut = tmp_path / "cut.jsonl"
    write_recording(cut, frames[: first_racing + 60])  # stops in lap 1 of the 2-lap race
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path / "live"))
    out = tmp_path / "out"
    assert main(["replay", str(cut), "--store", str(out)]) == 0
    sessions = sorted((out / "sessions").iterdir())
    assert sessions and all((s / "summary.json").exists() for s in sessions)
    last = json.loads((sessions[-1] / "summary.json").read_text())
    assert last["ended_at"] is not None and not last["finished"]


def test_replay_store_into_the_live_directory_is_refused_while_the_engineer_runs(
    tmp_path, monkeypatch, capsys
):
    from those_who_run.store import SessionStore

    live = tmp_path / "live"
    monkeypatch.setenv("GT7_DATA_DIR", str(live))
    engineer = SessionStore(live)
    try:
        assert main(["replay", str(FIXTURE), "--store", str(live)]) == 1
        assert "those-who-run replay: " in capsys.readouterr().err
        assert not (live / "sessions").exists()
    finally:
        engineer.close()


def _sessions(store: Path) -> list[tuple[str, float, float]]:
    db = sqlite3.connect(store / "index.sqlite")
    rows = db.execute("SELECT id, started_at, ended_at FROM sessions ORDER BY id").fetchall()
    db.close()
    return rows


def test_replay_store_with_a_clock_is_the_same_on_every_run(tmp_path, monkeypatch):
    """#336: --clock dates the sessions from a fixed time plus the recording's own,
    so two runs, on different days, store the same ids and times."""
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path / "live"))
    clock = "2026-10-18T09:00:00Z"
    args = ["--clock", clock]
    assert main(["replay", str(FIXTURE), "--store", str(tmp_path / "a"), *args]) == 0
    # A day later by the wall clock: nothing stored may follow it.
    later = time.time() + 86_400
    monkeypatch.setattr(time, "time", lambda: later)
    assert main(["replay", str(FIXTURE), "--store", str(tmp_path / "b"), *args]) == 0
    first, second = _sessions(tmp_path / "a"), _sessions(tmp_path / "b")
    assert first == second
    (session_id, started, ended), *_ = first
    assert session_id.startswith("20261018-0900")
    assert 1_792_314_000 <= started < ended < 1_792_314_000 + 3600
    assert sorted(p.name for p in (tmp_path / "a" / "sessions").iterdir()) == [r[0] for r in first]


def test_replay_clock_takes_iso_or_epoch_seconds():
    p = build_parser()
    assert p.parse_args(["replay", "x", "--clock", "1792314000"]).clock == 1_792_314_000
    assert p.parse_args(["replay", "x", "--clock", "2026-10-18T09:00:00"]).clock == 1_792_314_000
    assert p.parse_args(["replay", "x", "--clock", "2026-10-18T10:00:00+01:00"]).clock == (
        1_792_314_000
    )
    assert p.parse_args(["replay", "x"]).clock is None


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "-1", "1969-12-31T23:59:59Z"])
def test_replay_clock_refuses_non_finite_and_negative_times(text, capsys):
    """A typo must not write NaN, infinity or a time before 1970 into the store."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["replay", "x", f"--clock={text}"])
    assert f"not a time from 1970 on: {text!r}" in capsys.readouterr().err


def test_replay_clock_refuses_what_is_not_a_time(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["replay", "x", "--clock", "teatime"])
    assert "not a time: 'teatime'" in capsys.readouterr().err
