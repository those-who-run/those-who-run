"""A mid-race engineer restart continues the session it cut short (#273): the
same id, the laps appended, the track carried over, the gap recorded, and one
results card at the real end. Anything that does not match is a new session."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import pytest

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES, Settings
from those_who_run.engine import Engine, carried_track
from those_who_run.pitwall import data
from those_who_run.replay import read_recording
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import RaceState
from those_who_run.store import SessionStore, continue_mismatch

from .conftest import make_state
from .test_app import FakePlayer, make_app, wait_for

FIXTURES = Path(__file__).parent / "fixtures"
BEFORE = FIXTURES / "real-nuc-suzuka-before-restart-2026-10-18.jsonl.gz"
AFTER = FIXTURES / "real-nuc-suzuka-joined-mid-race-2026-10-18.jsonl.gz"
SUZUKA = 10
# Wall-clock time of the old outing's first frame: 2026-10-18 13:21:15 UTC.
WALL0 = 1792329675.0


class Clock:
    """Wall-clock time from the frames: both pods ran on one node, so the frame
    times of the two outings share a base, 8.7 s apart across the kill."""

    def __init__(self, t0: float, offset: float = 0.0) -> None:
        self.t0, self.offset, self.t = t0, offset, t0

    def at(self, state: RaceState) -> None:
        self.t = state.t

    def __call__(self) -> float:
        return WALL0 + self.offset + self.t - self.t0


def lifetime(
    data_dir: Path,
    frames: Iterable[RaceState],
    clock: Clock,
    cards: list[dict[str, Any]],
    shutdown: bool,
) -> tuple[Engine, list[str], list[tuple[int | None, str]]]:
    """One engineer from start to stop on ``data_dir``: the callouts it raised and
    the track it held after each frame. ``shutdown``: it stops as the engineer
    does (``App`` teardown), else the session is closed as the frames end."""
    store = SessionStore(data_dir, clock=clock, on_end=cards.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    said: list[str] = []
    tracks: list[tuple[int | None, str]] = []
    try:
        for s in frames:
            clock.at(s)
            said += [c.text for c in engine.process(s)]
            if store.session is not None and engine.track is not None:
                tracks.append((engine.track.track_id, engine.track.confidence))
        engine.close_session(shutdown=shutdown)
    finally:
        store.close()
    return engine, said, tracks


def first_t(path: Path) -> float:
    return next(iter(read_recording(path, strict=True))).t


def index(data_dir: Path, sql: str) -> list[tuple[Any, ...]]:
    db = sqlite3.connect(data_dir / "index.sqlite")
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


def test_real_restart_mid_race_is_one_session(tmp_path):
    """Suzuka timed race, 2026-10-18: the pod was killed 20 s into lap 7, leading,
    and its replacement was back 8.7 s later (outings 20261018-132115, then
    20261018-134517). Replayed through two engine and store lifetimes on one data
    directory, that is one session at Suzuka: laps 1 to 6, lap 7 incomplete with
    the frames of both pods, then lap 8, and one gap. One card, at the end, says
    the engineer restarted on lap 7 (#273 AC1)."""
    clock = Clock(first_t(BEFORE))
    cards: list[dict[str, Any]] = []
    lifetime(tmp_path, read_recording(BEFORE, strict=True), clock, cards, shutdown=True)
    assert cards == [], "held: the engineer may come back"
    (held,) = index(tmp_path, "SELECT id, engineer_shutdown, card_held, ended_at FROM sessions")
    session_id = held[0]
    assert held[1:3] == (1, 1) and held[3] is not None
    before = json.loads((tmp_path / "sessions" / session_id / "summary.json").read_text())
    assert before["engineer_shutdown"] is True
    assert [(x["lap"], x["complete"]) for x in before["laps"]][-2:] == [(6, True), (7, False)]
    frames_7 = before["laps"][-1]["frames"]

    engine, said, tracks = lifetime(
        tmp_path, read_recording(AFTER, strict=True), clock, cards, shutdown=False
    )
    assert said == [
        "Back with you. Lap seven. P one.",
        "Lap seven. two thirty point five. two point three over best.",
    ]
    assert tracks[0] == (SUZUKA, "confirmed"), "carried over: known from the first frame"
    assert set(tracks) == {(SUZUKA, "confirmed")}

    assert index(tmp_path, "SELECT id, engineer_shutdown, card_held FROM sessions") == [
        (session_id, 0, 0)
    ]
    (card_summary,) = cards
    assert card_summary["session_id"] == session_id
    laps = [(x["lap"], x["complete"]) for x in card_summary["laps"]]
    assert laps == [(n, True) for n in range(1, 7)] + [(7, False), (8, False)]
    lap_7 = card_summary["laps"][6]
    assert lap_7["lap_time_ms"] == 150511, "GT7 timed it"
    assert lap_7["fuel_start"] == before["laps"][-1]["fuel_start"]
    (gap,) = card_summary["gaps"]
    assert gap["reason"] == "engineer restart" and gap["lap"] == 7
    assert 8 < gap["to"] - gap["from"] < 10
    assert card_summary["track"]["id"] == SUZUKA
    assert card_summary["track"]["confidence"] == "confirmed"
    assert card_summary["laps_completed"] == 6
    assert card_summary["joined_on_lap"] is None, "laps 1 to 6 are here"
    assert card_summary["engineer_shutdown"] is False
    assert card_summary["started_at"] == before["started_at"]
    assert card_summary["driving_ms"] > before["driving_ms"] + 160_000
    assert card_summary["paused_ms"] >= before["paused_ms"]
    kind = card_summary["session_kind"]
    assert kind["kind"] == "timed_field" and kind["start"] == before["session_kind"]["start"]
    (stop,) = card_summary["pit_stops"]  # the stop on lap 4, from before the restart
    assert stop["in_lap"] == 4 and card_summary["stints"] == 2

    lap_7_rows = index(tmp_path, "SELECT frames, complete, file FROM laps WHERE lap = 7")
    ((frames, complete, file),) = lap_7_rows
    path = tmp_path / "sessions" / session_id / file
    stored = duckdb.sql(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()
    assert stored is not None and stored[0] == frames > frames_7 and complete == 0

    card = build_card(card_summary)
    assert card is not None
    assert card.title == "Suzuka Circuit · timed race"
    facts = dict(card.fields)
    assert facts["Engineer restarted"] == "on lap 7"
    assert "Joined" not in facts

    # The pit wall: the laps after the gap, and the gap.
    (row,) = data.list_sessions(tmp_path)
    assert row.session_id == session_id and row.gaps == (gap,)
    assert ("Engineer restarted", "on lap 7") in row.facts
    lap_rows = data.lap_summaries(tmp_path, session_id)
    assert [r.lap for r in lap_rows] == list(range(1, 9))
    assert [r.lap for r in lap_rows if r.restart] == [7]
    assert lap_rows[6].flags == "restart, partial"


def test_the_pit_wall_shows_a_continued_session_running_with_its_gap(tmp_path):
    """While the session continues, summary.json is gone (it is open again) and
    the pit wall reads it from the index, gap and all."""
    clock = Clock(first_t(BEFORE))
    cards: list[dict[str, Any]] = []
    lifetime(tmp_path, read_recording(BEFORE, strict=True), clock, cards, shutdown=True)
    store = SessionStore(tmp_path, clock=clock, on_end=cards.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    try:
        for s in list(read_recording(AFTER, strict=True))[:5]:
            clock.at(s)
            engine.process(s)
        (row,) = data.list_sessions(tmp_path)
        assert not row.closed and row.result == "Running, 6 laps"
        assert [g["lap"] for g in row.gaps] == [7]
        assert ("Engineer restarted", "on lap 7") in row.facts
    finally:
        store.close()


def _shifted(path: Path, **change: Any) -> list[RaceState]:
    return [dataclasses.replace(s, **change) for s in read_recording(path, strict=True)]


def test_another_car_or_a_gap_over_the_limit_is_a_new_session(tmp_path):
    """#273 AC2: the same restart in another car, or back after more than the
    window, is two sessions as before, and the held card goes when the second
    session starts."""
    for name, frames, offset in (
        ("car", _shifted(AFTER, car_code=1), 0.0),
        ("late", list(read_recording(AFTER, strict=True)), 601.0),
    ):
        data_dir = tmp_path / name
        cards: list[dict[str, Any]] = []
        lifetime(data_dir, read_recording(BEFORE, strict=True), Clock(first_t(BEFORE)), cards, True)
        assert cards == []
        late = Clock(first_t(BEFORE), offset)
        lifetime(data_dir, frames, late, cards, shutdown=False)
        rows = index(data_dir, "SELECT engineer_shutdown, card_held, joined_on_lap FROM sessions")
        assert sorted(rows) == [(0, 0, 7), (1, 0, None)], name
        first, second = cards
        assert first["engineer_shutdown"] and not first.get("gaps"), name
        assert second["joined_on_lap"] == 7 and not second["gaps"], name
        card = build_card(first)
        assert card is not None and card.description == "Engineer stopped on lap 7, P1"


def test_a_held_card_goes_once_the_window_has_passed(tmp_path):
    """No restart comes, or one that finds the driver in the menus: the card is
    held for the window and then let go (``release_held`` on the watchdog). A
    store opened later lets go of one an earlier store held."""
    clock = Clock(first_t(BEFORE))
    cards: list[dict[str, Any]] = []
    lifetime(tmp_path, read_recording(BEFORE, strict=True), clock, cards, shutdown=True)
    store = SessionStore(tmp_path, clock=clock, on_end=cards.append)
    try:
        assert store.release_held() == 0 and cards == []
        clock.offset += 599
        assert store.release_held() == 0 and cards == []
        clock.offset += 2
        assert store.release_held() == 1
        (summary,) = cards
        assert summary["engineer_shutdown"] is True
        assert store.release_held() == 0 and len(cards) == 1, "once"
    finally:
        store.close()
    assert index(tmp_path, "SELECT card_held FROM sessions") == [(0,)]


def test_a_held_card_whose_summary_is_gone_is_dropped_and_logged(tmp_path, caplog):
    clock = Clock(first_t(BEFORE))
    cards: list[dict[str, Any]] = []
    lifetime(tmp_path, read_recording(BEFORE, strict=True), clock, cards, shutdown=True)
    (path,) = (tmp_path / "sessions").glob("*/summary.json")
    path.unlink()
    store = SessionStore(tmp_path, clock=clock, on_end=cards.append)
    try:
        assert store.release_held(force=True) == 1
    finally:
        store.close()
    assert cards == [] and "not let go" in caplog.text


def test_a_join_without_a_summary_to_continue_is_a_new_session(tmp_path, caplog):
    clock = Clock(first_t(BEFORE))
    cards: list[dict[str, Any]] = []
    lifetime(tmp_path, read_recording(BEFORE, strict=True), clock, cards, shutdown=True)
    (path,) = (tmp_path / "sessions").glob("*/summary.json")
    path.write_text("{", encoding="utf-8")
    lifetime(tmp_path, read_recording(AFTER, strict=True), clock, cards, shutdown=False)
    assert len(index(tmp_path, "SELECT id FROM sessions")) == 2
    assert "cannot be continued" in caplog.text


def test_what_does_not_match_is_said():
    """#273 R5: car, kind (race or not, lap total, field size), lap order, time."""
    before = {
        "car_code": 1689,
        "type": "race",
        "total_laps": 0,
        "total_cars": 16,
        "laps": [{"lap": 6}, {"lap": 7}],
    }
    joined = make_state(
        car_code=1689, total_laps=0, total_cars=16, current_lap=7, cars_on_track=True
    )
    assert continue_mismatch(before, joined, 9.0, 600.0) is None
    assert continue_mismatch(before, dataclasses.replace(joined, current_lap=8), 9, 600) is None
    cases = {
        "over 10.0": (joined, 700.0),
        "another car": (dataclasses.replace(joined, car_code=2), 9.0),
        "5 laps, not 0": (dataclasses.replace(joined, total_laps=5), 9.0),
        "12 cars, not 16": (dataclasses.replace(joined, total_cars=12), 9.0),
        "before its last lap 7": (dataclasses.replace(joined, current_lap=6), 9.0),
    }
    for want, (state, since) in cases.items():
        why = continue_mismatch(before, state, since, 600.0)
        assert why is not None and want in why, (want, why)
    practice = dataclasses.replace(joined, cars_on_track=False)
    assert continue_mismatch(before, practice, 9.0, 600.0) == "a time_trial, not a race"


def test_only_a_sure_track_is_carried_over():
    assert carried_track(None) is None
    assert carried_track({"id": None, "confidence": "confirmed"}) is None
    assert carried_track({"id": 10, "confidence": "ambiguous"}) is None
    match = carried_track({"id": 10, "name": "Suzuka Circuit", "confidence": "probable"})
    assert match is not None and match.decision == (10, "probable")
    # Only the circuit known, as for the Spa twins (#275): the circuit is carried.
    spa = carried_track({"id": None, "confidence": "ambiguous", "family": "Spa-Francorchamps"})
    assert spa is not None and spa.decision == (None, "ambiguous")
    assert spa.family == "Spa-Francorchamps"
    assert carried_track({"id": None, "confidence": "ambiguous", "family": None}) is None


def test_the_window_is_configurable():
    assert Settings.from_env({}).continue_window_secs == 600.0
    assert Settings.from_env({"GT7_CONTINUE_WINDOW_SECS": "120"}).continue_window_secs == 120.0


@pytest.fixture
def live(tmp_path) -> Settings:
    """Settings for the live engineer with fakes, posting cards to channel 7."""
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"")
    return Settings(
        ps5_ip="192.0.2.1",
        discord_token="x",
        discord_channel_id=1,
        rules_file=None,
        data_dir=tmp_path / "data",
        voice_model=model,
        metrics_port=0,
        idle_disconnect_secs=600,
        telemetry_timeout_secs=3,
        log_level="INFO",
        results_channel_id=7,
    )


async def run_app(settings: Settings, frames: list[RaceState]) -> None:
    """Start the engineer, feed it ``frames`` and stop it."""
    app, made = make_app(settings, frames, FakePlayer())
    running = asyncio.create_task(app.run())
    await wait_for(lambda: bool(made) and made[0].packets == len(frames) and app.states.empty())
    await asyncio.sleep(0.05)  # the last frame through the engine
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def test_the_app_holds_the_card_at_shutdown_and_its_restart_continues(live, sim, monkeypatch):
    """The live engineer: stopped on lap 3 of 5, the session is marked as ended by
    the shutdown and no card goes. Started again mid-lap, the next engineer
    continues it, and the one card goes at the flag (#273)."""
    from those_who_run.results import ResultsPoster

    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(ResultsPoster, "submit", lambda self, summary: posted.append(summary))
    settings = live
    frames = sim(total_laps=5).menu().at_track().race([90000, 89000, 88000, 87000, 86000]).frames
    cut = next(i for i, f in enumerate(frames) if f.current_lap == 3)
    await run_app(settings, frames[: cut + 1])
    assert posted == []
    (row,) = index(settings.data_dir, "SELECT engineer_shutdown, card_held FROM sessions")
    assert row == (1, 1)
    await run_app(settings, frames[cut + 1 :])
    (summary,) = posted
    assert summary["finished"] and [g["lap"] for g in summary["gaps"]] == [3]
    assert [(x["lap"], x["complete"]) for x in summary["laps"]] == [
        (1, True),
        (2, True),
        (3, False),
        (4, True),
        (5, True),
    ]
    assert index(settings.data_dir, "SELECT engineer_shutdown, card_held FROM sessions") == [(0, 0)]
