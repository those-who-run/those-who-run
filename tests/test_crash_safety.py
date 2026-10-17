"""Recordings and session summaries after an unclean stop (#149)."""

import gzip
import json
import threading
from pathlib import Path

import pytest

from tests.conftest import make_state
from those_who_run import store as store_mod
from those_who_run.__main__ import main
from those_who_run.engine import Engine
from those_who_run.recordtools import recording_started_at, summarise_recording
from those_who_run.replay import OutingRecorder, read_recording
from those_who_run.state import Phase

FIXTURES = Path(__file__).parent / "fixtures"
FUJI = FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl"


def cut_last_line_in_half(src: Path, dst: Path) -> int:
    """Copy ``src`` with its last line cut in half; returns the number of whole lines."""
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    last = lines[-1].rstrip("\n")
    dst.write_text("".join(lines[:-1]) + last[: len(last) // 2], encoding="utf-8")
    return len(lines) - 1


def test_a_recording_with_its_last_line_cut_in_half_returns_every_whole_frame(tmp_path):
    whole = list(read_recording(FUJI, strict=True))
    cut = tmp_path / "cut.jsonl"
    assert cut_last_line_in_half(FUJI, cut) == len(whole) - 1
    rec = read_recording(cut)
    frames = list(rec)
    assert frames == whole[:-1]
    assert not rec.complete and rec.bad_lines == 1
    assert read_recording(FUJI).complete is True
    with pytest.raises(ValueError, match="bad state record"):
        list(read_recording(cut, strict=True))


def test_a_gzip_recording_cut_off_mid_stream_reads_up_to_the_damage(tmp_path):
    whole = list(read_recording(FUJI))
    data = gzip.compress(FUJI.read_bytes())
    cut = tmp_path / "cut.jsonl.gz"
    cut.write_bytes(data[: len(data) // 2])
    rec = read_recording(cut)
    frames = list(rec)
    assert 0 < len(frames) < len(whole) and frames == whole[: len(frames)]
    assert not rec.complete
    sessions, complete = summarise_recording(cut)
    assert not complete


def test_listing_skips_a_corrupt_gzip_and_keeps_the_good_recording(tmp_path, capsys):
    (tmp_path / "20261016-180000.jsonl.gz").write_bytes(b"not gzip at all" * 100)
    good = tmp_path / "20261016-190000.jsonl"
    good.write_bytes(FUJI.read_bytes())
    sessions, complete = summarise_recording(tmp_path / "20261016-180000.jsonl.gz")
    assert sessions == [] and not complete
    assert main(["recordings", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("20261016-180000.jsonl.gz") and "incomplete" in out[0]
    assert out[2] == "20261016-190000.jsonl" and "time trial" in out[3]


def test_summarising_closes_its_store_when_the_engine_fails(tmp_path, monkeypatch):
    def boom(self, state):
        raise RuntimeError("engine bug")

    monkeypatch.setattr(Engine, "process", boom)
    with pytest.raises(RuntimeError):
        summarise_recording(FUJI)
    assert not [t for t in threading.enumerate() if t.name.startswith("lap-writer")]


def test_listing_goes_on_past_a_recording_that_cannot_be_summarised(tmp_path, capsys, monkeypatch):
    for name in ("20261016-180000.jsonl", "20261016-190000.jsonl"):
        (tmp_path / name).write_bytes(FUJI.read_bytes())
    real = Engine.process
    calls = {"n": 0}

    def flaky(self, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("engine bug")
        return real(self, state)

    monkeypatch.setattr(Engine, "process", flaky)
    assert main(["recordings", str(tmp_path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "20261016-180000.jsonl  (unreadable: engine bug)"
    assert out[1] == "20261016-190000.jsonl" and "time trial" in out[2]


def test_a_summary_write_interrupted_before_the_rename_leaves_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "summary.json"
    store_mod.write_summary(path, {"session_id": "a", "ended_at": 1.0})

    def killed(src, dst):
        raise KeyboardInterrupt  # the process stops between the write and the rename

    monkeypatch.setattr(store_mod.os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        store_mod.write_summary(path, {"session_id": "a", "ended_at": 2.0, "laps": [1] * 1000})
    assert json.loads(path.read_text()) == {"session_id": "a", "ended_at": 1.0}
    assert [p.name for p in tmp_path.iterdir()] == ["summary.json"]


def test_a_second_outing_in_the_same_second_gets_its_own_file(tmp_path):
    rec = OutingRecorder(tmp_path, clock=lambda: 1_792_000_000.0)
    for t0 in (0.0, 10.0):
        rec.write(make_state(t=t0, current_lap=0, phase=Phase.AT_TRACK))
        rec.write(make_state(t=t0 + 1, current_lap=-1, phase=Phase.MENU))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["20261014-174640-2.jsonl.gz", "20261014-174640.jsonl.gz"]
    # The second outing opens with the menu frame that closed the first.
    sizes = [len(list(read_recording(tmp_path / n, strict=True))) for n in names]
    assert sizes == [3, 2]
    assert all(recording_started_at(tmp_path / n) == 1_792_000_000.0 for n in names)


def test_a_same_second_outing_sorts_after_the_first(tmp_path, capsys, monkeypatch):
    from those_who_run.recordtools import list_recordings
    from those_who_run.replay import outing_order

    clock = [1_792_000_000.0]
    rec = OutingRecorder(tmp_path, keep=2, clock=lambda: clock[0])

    def outing(t0: float) -> None:
        rec.write(make_state(t=t0, current_lap=0, phase=Phase.AT_TRACK))
        rec.write(make_state(t=t0 + 1, current_lap=-1, phase=Phase.MENU))

    outing(0.0)
    outing(10.0)  # same second: X-2
    assert [p.name for p in list_recordings(tmp_path)] == [
        "20261014-174640.jsonl.gz",
        "20261014-174640-2.jsonl.gz",
    ]
    outing(20.0)  # X-3, and keep=2 prunes the oldest, X
    assert [p.name for p in list_recordings(tmp_path)] == [
        "20261014-174640-2.jsonl.gz",
        "20261014-174640-3.jsonl.gz",
    ]
    clock[0] += 1
    outing(30.0)  # the next second sorts after every -N of the one before
    assert [p.name for p in list_recordings(tmp_path)][-1] == "20261014-174641.jsonl.gz"
    names = ["b.jsonl", "20261014-174640-10.jsonl.gz", "20261014-174640-9.jsonl.gz"]
    assert sorted(names, key=lambda n: outing_order(Path(n)))[:2] == names[2:0:-1]

    monkeypatch.setenv("GT7_RECORD_DIR", str(tmp_path))
    assert main(["recordings", "--last", "1"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "20261014-174641.jsonl.gz"


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.jsonl")), ids=lambda p: p.name)
def test_every_fixture_reads_whole(fixture):
    """Fixtures are read strictly: a damaged one fails here, loudly, rather than
    being skipped over by the lenient reader the tools use."""
    rec = read_recording(fixture, strict=True)
    assert len(list(rec)) > 0 and rec.complete and rec.bad_lines == 0
