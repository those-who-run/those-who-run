import calendar
import os
import time
from pathlib import Path

from those_who_run.__main__ import main
from those_who_run.recordtools import recording_started_at, summarise_recording
from those_who_run.results import build_card

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_finished_race():
    (s,), complete = summarise_recording(FIXTURES / "real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz")
    assert complete and s.ended == "flag"
    assert s.line().endswith("lap_race/rolling  flag")
    assert "Suzuka Circuit East Course · 6-lap race" in s.line()
    assert "best 1:01.186 (lap 4)" in s.line()


def test_a_restart_then_a_quit():
    sessions, _ = summarise_recording(FIXTURES / "real-quali-restart-quit-2026-10-14.jsonl.gz")
    assert [s.ended for s in sessions] == ["restart", "quit"]
    assert sessions[1].offset_secs > sessions[0].offset_secs
    assert all("timed_field" in s.line() for s in sessions)


def test_a_time_trial_left_through_the_menu():
    (s,), _ = summarise_recording(FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl.gz")
    assert s.ended == "quit" and "Fuji International Speedway · time trial" in s.line()
    assert "NISMO 400R '95" in s.line() and "solo_timed/flying" in s.line()


def test_recordings_cli(tmp_path, capsys, monkeypatch):
    rec = tmp_path / "20261016-190000.jsonl.gz"
    rec.write_bytes((FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl.gz").read_bytes())
    monkeypatch.setenv("GT7_RECORD_DIR", str(tmp_path))
    assert main(["recordings", "--last", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "20261016-190000.jsonl.gz" and "time trial" in out[1]


def test_sessions_get_the_outings_wall_clock_not_the_ps5_clock(tmp_path):
    """Frames carry the PS5 link's clock (March 1970); a session rebuilt from an outing
    recording is dated from the file name, so its id and card match the live ones."""
    rec = tmp_path / "20261016-190000.jsonl.gz"
    rec.write_bytes((FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl.gz").read_bytes())
    (s,), _ = summarise_recording(rec)
    outing = calendar.timegm((2026, 10, 16, 19, 0, 0))
    started = s.summary["started_at"]
    assert outing <= started < outing + 120
    card = build_card(s.summary)
    assert card is not None and card.timestamp is not None and card.timestamp.year == 2026
    assert s.line().startswith(time.strftime("%H:%M", time.localtime(started)) + "  +")


def test_a_recording_not_named_by_the_recorder_is_dated_by_its_file(tmp_path):
    rec = tmp_path / "fuji.jsonl.gz"
    rec.write_bytes((FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl.gz").read_bytes())
    os.utime(rec, (1_790_000_000, 1_790_000_000))
    assert recording_started_at(rec) == 1_790_000_000
    (s,), _ = summarise_recording(rec)
    assert 1_790_000_000 <= s.summary["started_at"] < 1_790_000_000 + 600
