"""The stored best lap is the card's best lap (#185).

GT7 leaves lap 1 from a grid start out of its best lap, and so do the results
card, the pit wall and the spoken summary. The store used to take the quickest
complete lap of all, so four of the real fixtures stored lap 1.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from those_who_run import store as store_mod
from those_who_run.__main__ import main
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.store import BestLapFix, SessionStore, StoreBusy, rebuild_best_laps

FIXTURES = Path(__file__).parent / "fixtures"
# A replay (#243) or a demo (#260) stores nothing: it has no best lap to compare.
DEMOS = {
    "real-nuc-laguna-seca-demo-2026-10-18",
    "real-nuc-tokyo-east-race-2026-10-15",
    "real-nuc-laguna-seca-race-2026-10-15",
    "real-nuc-nordschleife-rolling-start-2026-10-15",
    "real-nuc-tsukuba-brz-drift-2026-10-15",
}
REAL = sorted(
    p
    for p in FIXTURES.glob("real-*.jsonl.gz")
    if "-replay-" not in p.name and p.name.removesuffix(".jsonl.gz") not in DEMOS
)
PIT_STOP = FIXTURES / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz"


async def _replay(path: Path, data_dir: Path) -> None:
    store = SessionStore(data_dir)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    await replay(read_recording(path), engine, ConsolePlayer())
    if store.session is not None and engine.prev is not None:  # the fixture stops mid-race
        store.set_pits(engine.pits.status)
        store.end_session(engine.prev)
    store.close()


def _stored(data_dir: Path) -> dict[str, int | None]:
    db = sqlite3.connect(data_dir / "index.sqlite")
    try:
        return dict(db.execute("SELECT id, best_lap_ms FROM sessions ORDER BY id"))
    finally:
        db.close()


def _summary(data_dir: Path, session_id: str) -> dict:
    path = data_dir / "sessions" / session_id / "summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _card_best(summary: dict) -> int | None:
    card = build_card(summary)
    best = dict(card.fields).get("Best lap") if card else None
    if best is None:
        return None
    lap_no = int(best.rsplit("lap ", 1)[1].rstrip(")"))
    return next(x["lap_time_ms"] for x in summary["laps"] if x["lap"] == lap_no)


@pytest.mark.parametrize("path", REAL, ids=[p.stem for p in REAL])
async def test_stored_best_lap_is_the_cards(path, tmp_path):
    await _replay(path, tmp_path)
    stored = _stored(tmp_path)
    assert stored
    for session_id, best in stored.items():
        summary = _summary(tmp_path, session_id)
        assert best == summary["best_lap_ms"] == _card_best(summary)


@pytest.mark.parametrize(
    ("name", "bests"),
    [
        ("real-nuc-suzuka-pit-stop-2026-10-15", [59541]),  # not lap 1's 57.109
        ("real-nuc-suzuka-no-stop-2026-10-15", [61186]),  # not 1:00.358
        ("real-nuc-suzuka-timed-race-2026-10-16", [67585]),  # not 1:02.036
        ("real-race-2laps-2026-10-14", [49677, 53108]),  # the lap race: not 50.982
        ("real-nuc-gilles-villeneuve-race-2026-10-17", [97524]),  # lap 1 does count here
    ],
)
async def test_stored_best_lap_leaves_out_a_grid_start(name, bests, tmp_path):
    await _replay(FIXTURES / f"{name}.jsonl.gz", tmp_path)
    assert list(_stored(tmp_path).values()) == bests


async def test_summary_keeps_the_fastest_lap_of_any_kind(tmp_path):
    await _replay(PIT_STOP, tmp_path)
    (session_id,) = _stored(tmp_path)
    summary = _summary(tmp_path, session_id)
    assert summary["best_lap_ms"] == 59541
    assert summary["fastest_lap_ms"] == 57109  # lap 1 from the grid


def _as_written_by_0_4_0(data_dir: Path) -> None:
    """Rewrite the store as 0.4.0 left it: the quickest complete lap of all as the
    best, and no ``fastest_lap_ms``."""
    db = sqlite3.connect(data_dir / "index.sqlite")
    for (session_id,) in db.execute("SELECT id FROM sessions").fetchall():
        path = data_dir / "sessions" / session_id / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        times = [x["lap_time_ms"] for x in summary["laps"] if x["complete"] and x["lap_time_ms"]]
        summary["best_lap_ms"] = min(times) if times else None
        del summary["fastest_lap_ms"]
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        db.execute(
            "UPDATE sessions SET best_lap_ms = ? WHERE id = ?", (summary["best_lap_ms"], session_id)
        )
    db.commit()
    db.close()


async def test_rebuild_corrects_a_store_written_by_0_4_0(tmp_path):
    await _replay(PIT_STOP, tmp_path)
    await _replay(FIXTURES / "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz", tmp_path)
    _as_written_by_0_4_0(tmp_path)
    pit_id, gilles_id = _stored(tmp_path)
    assert _stored(tmp_path) == {pit_id: 57109, gilles_id: 97524}

    assert rebuild_best_laps(tmp_path) == [BestLapFix(pit_id, 57109, 59541)]
    assert _stored(tmp_path) == {pit_id: 59541, gilles_id: 97524}
    pit = _summary(tmp_path, pit_id)
    assert (pit["best_lap_ms"], pit["fastest_lap_ms"]) == (59541, 57109)
    assert _summary(tmp_path, gilles_id)["fastest_lap_ms"] == 97524

    assert rebuild_best_laps(tmp_path) == []  # safe to run again


async def test_rebuild_skips_a_session_without_a_summary(tmp_path):
    await _replay(PIT_STOP, tmp_path)
    (session_id,) = _stored(tmp_path)
    (tmp_path / "sessions" / session_id / "summary.json").unlink()
    assert rebuild_best_laps(tmp_path) == []


async def test_rebuild_best_command(tmp_path, monkeypatch, capsys):
    await _replay(PIT_STOP, tmp_path)
    _as_written_by_0_4_0(tmp_path)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
    assert main(["rebuild-best"]) == 0
    out = capsys.readouterr().out
    assert "57.109 -> 59.541" in out and "1 session(s) corrected" in out


async def test_rebuild_refuses_while_the_engineer_runs(tmp_path, monkeypatch, capsys):
    await _replay(PIT_STOP, tmp_path)
    _as_written_by_0_4_0(tmp_path)
    engineer = SessionStore(tmp_path)  # holds engineer.lock
    try:
        with pytest.raises(StoreBusy):
            rebuild_best_laps(tmp_path)
        monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
        assert main(["rebuild-best"]) == 1
        assert "in use by another writer" in capsys.readouterr().err
    finally:
        engineer.close()
    assert list(_stored(tmp_path).values()) == [57109]  # nothing was touched
    assert len(rebuild_best_laps(tmp_path)) == 1  # the engineer stopped: it runs


async def test_rebuild_commits_each_session_and_writes_summaries_whole(tmp_path, monkeypatch):
    await _replay(PIT_STOP, tmp_path)
    await _replay(FIXTURES / "real-race-2laps-2026-10-14.jsonl.gz", tmp_path)
    _as_written_by_0_4_0(tmp_path)
    written: list[Path] = []
    real_write = store_mod.write_summary

    def write_then_fail(path, summary):
        real_write(path, summary)
        written.append(path)
        if len(written) == 2:
            raise OSError("disk full")

    monkeypatch.setattr(store_mod, "write_summary", write_then_fail)
    with pytest.raises(OSError):
        rebuild_best_laps(tmp_path)
    first = written[0].parent.name
    assert _stored(tmp_path)[first] == _summary(tmp_path, first)["best_lap_ms"]  # committed
    assert not list((tmp_path / "sessions").glob("*/summary.json.tmp"))
