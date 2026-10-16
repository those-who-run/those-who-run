from pathlib import Path

from those_who_run.__main__ import main
from those_who_run.recordtools import summarise_recording

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_finished_race():
    (s,), complete = summarise_recording(FIXTURES / "real-nuc-suzuka-no-stop-2026-10-15.jsonl")
    assert complete and s.ended == "flag"
    assert s.line().endswith("lap_race/rolling  flag")
    assert "Suzuka Circuit East Course · 6-lap race" in s.line()
    assert "best 1:01.186 (lap 4)" in s.line()


def test_a_restart_then_a_quit():
    sessions, _ = summarise_recording(FIXTURES / "real-quali-restart-quit-2026-10-14.jsonl")
    assert [s.ended for s in sessions] == ["restart", "quit"]
    assert sessions[1].offset_secs > sessions[0].offset_secs
    assert all("timed_field" in s.line() for s in sessions)


def test_a_time_trial_left_through_the_menu():
    (s,), _ = summarise_recording(FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl")
    assert s.ended == "quit" and "Fuji International Speedway · time trial" in s.line()
    assert "NISMO 400R '95" in s.line() and "solo_timed/flying" in s.line()


def test_recordings_cli(tmp_path, capsys, monkeypatch):
    rec = tmp_path / "20261016-190000.jsonl"
    rec.write_bytes((FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl").read_bytes())
    monkeypatch.setenv("GT7_RECORD_DIR", str(tmp_path))
    assert main(["recordings", "--last", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "20261016-190000.jsonl" and "time trial" in out[1]
