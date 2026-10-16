import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import make_state
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.metrics import Metrics
from those_who_run.replay import read_recording, replay
from those_who_run.rules import build_rules
from those_who_run.rules.base import Rule
from those_who_run.sessionkind import SessionDetector
from those_who_run.state import Phase
from those_who_run.store import SessionStore

FIXTURES = Path(__file__).parent / "fixtures"


def frame(t: float = 0.0, **over):
    over.setdefault("phase", Phase.IN_RACE)
    return make_state(t=t, **over)


def feed(det: SessionDetector, frames) -> list[str]:
    changes = []
    for f in frames:
        k = det.observe(f)
        if k is not None:
            changes.append(k.kind)
    return changes


# kinds


@pytest.mark.parametrize(
    ("laps", "cars", "kind"),
    [
        (3, 16, "lap_race"),
        (6, 2, "lap_race"),  # one AI opponent, Suzuka East
        (4, 1, "solo_laps"),
        (0, 20, "timed_field"),
        (0, 1, "solo_timed"),
    ],
)
def test_kind_from_the_lap_total_and_the_cars(laps, cars, kind):
    det = SessionDetector()
    det.observe(frame(total_laps=laps, total_cars=cars, race_start_pos=1))
    assert det.kind.kind == kind
    assert det.kind.field == (kind in ("lap_race", "timed_field"))


def test_a_ghost_is_not_a_field_but_being_passed_is():
    det = SessionDetector()
    feed(det, [frame(0, total_laps=0, total_cars=1, race_start_pos=1)])
    feed(det, [frame(1, total_laps=0, total_cars=2, race_start_pos=1)])  # time trial ghost
    assert det.kind.kind == "solo_timed"
    feed(det, [frame(2, total_laps=0, total_cars=2, race_start_pos=2)])
    assert det.kind.kind == "timed_field" and "not always first" in det.kind.evidence


def test_minus_one_cars_says_nothing_and_a_late_lap_total_counts():
    det = SessionDetector()
    det.observe(frame(0, total_laps=3, total_cars=12))
    det.observe(frame(1, total_laps=0, total_cars=-1, race_start_pos=-1, cars_on_track=False))
    assert det.kind.kind == "lap_race" and det.kind.total_laps == 3

    det = SessionDetector()
    det.observe(frame(0, total_laps=0, total_cars=-1, race_start_pos=-1, cars_on_track=False))
    assert det.kind.kind == "solo_timed"  # a time trial reports -1 all the way
    det.observe(frame(1, total_laps=2, total_cars=20))
    assert det.kind.kind == "lap_race"


def test_only_racing_frames_count():
    det = SessionDetector()
    assert det.observe(frame(phase=Phase.AT_TRACK)) is None
    assert det.kind.kind == "unknown"


# fuel use


def test_fuel_use_on_after_a_drop_off_after_driving_without_one():
    det = SessionDetector(fuel_settle_secs=20)
    feed(det, [frame(t * 0.5, fuel_level=100 - t * 0.01) for t in range(10)])  # 0.09 dropped
    assert det.kind.fuel_use is True and "fuel use on" in det.kind.evidence

    det = SessionDetector(fuel_settle_secs=20)
    feed(det, [frame(t * 0.5) for t in range(30)])
    assert det.kind.fuel_use is None  # 14.5 s of driving
    feed(det, [frame(15 + t * 0.5) for t in range(12)])
    assert det.kind.fuel_use is False
    feed(det, [frame(30, fuel_level=99.9)])
    assert det.kind.fuel_use is True, "a drop later still turns it on"


def test_fuel_use_counts_driving_time_not_waiting_or_pausing():
    det = SessionDetector(fuel_settle_secs=20)
    feed(det, [frame(t, speed_kph=0) for t in range(60)])  # sitting on the grid
    assert det.kind.fuel_use is None
    feed(det, [frame(100), frame(200)])  # one 100 s gap counts as a second at most
    assert det.kind.fuel_use is None


def test_a_refuel_raises_the_mark_and_no_tank_means_off():
    det = SessionDetector()
    feed(det, [frame(0, fuel_level=50.0), frame(1, fuel_level=100.0), frame(2, fuel_level=99.9)])
    assert det.kind.fuel_use is True
    det = SessionDetector()
    det.observe(frame(0, fuel_capacity=0.0, fuel_level=0.0))
    assert det.kind.fuel_use is False


# real recordings (2026-10-14 and 2026-10-15)


@pytest.mark.parametrize(
    ("fixture", "kind", "fuel_use", "cars_on_track"),
    [
        ("real-nuc-suzuka-no-stop-2026-10-15.jsonl", "lap_race", True, True),
        ("real-nuc-suzuka-pit-stop-2026-10-15.jsonl", "lap_race", True, True),
        ("real-nuc-suzuka-east-2026-10-15.jsonl", "solo_laps", True, True),
        ("real-nuc-fuji-timed-2026-10-15.jsonl", "solo_timed", False, True),
        ("real-nuc-sugo-timed-2026-10-15.jsonl", "solo_timed", False, True),
        ("real-n24h-race-lap1-positions-2026-10-14.jsonl", "lap_race", True, True),
        # the unnamed mode: no cars-on-track flag, no fuel use (see #63)
        ("real-nuc-tokyo-east-race-2026-10-15.jsonl", "lap_race", False, False),
        ("real-nuc-laguna-seca-race-2026-10-15.jsonl", "lap_race", False, False),
        ("real-nuc-tsukuba-brz-drift-2026-10-15.jsonl", "solo_laps", False, False),
    ],
)
def test_real_session_kinds(fixture, kind, fuel_use, cars_on_track):
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    for s in read_recording(FIXTURES / fixture):
        engine.process(s)
    assert engine.kind.kind == kind
    assert engine.kind.fuel_use is fuel_use
    assert engine.kind.cars_on_track is cars_on_track


def test_real_qualifying_is_a_timed_field():
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    kinds = set()
    for s in read_recording(FIXTURES / "real-quali-restart-quit-2026-10-14.jsonl"):
        engine.process(s)
        kinds.add(engine.kind.kind)
    assert kinds == {"unknown", "timed_field"}


# plumbing


class Spy(Rule):
    name = "spy"

    def reset(self) -> None:
        self.seen = getattr(self, "seen", [])

    def evaluate(self, prev, state):
        return []

    def on_session(self, kind) -> None:
        self.seen.append((kind.kind, kind.fuel_use))


def test_engine_records_the_kind_in_the_session_metrics_and_rules(tmp_path):
    store = SessionStore(tmp_path)
    metrics = Metrics()
    spy = Spy()
    engine = Engine([spy], CalloutQueue(max_age=None), store, metrics)
    fixture = FIXTURES / "real-nuc-suzuka-no-stop-2026-10-15.jsonl"
    asyncio.run(replay(read_recording(fixture), engine, ConsolePlayer()))
    store.close()
    assert spy.seen == [("lap_race", None), ("lap_race", True)]
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT session_kind, fuel_use FROM sessions").fetchall() == [("lap_race", 1)]
    summary = json.loads(next((tmp_path / "sessions").glob("*/summary.json")).read_text())
    assert summary["session_kind"]["kind"] == "lap_race"
    assert summary["session_kind"]["fuel_use"] is True
    assert b'gt7_session_info{fuel_use="on",kind="lap_race"} 1.0' in metrics.render()
