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
from those_who_run.sessionkind import DriverCheck, SessionDetector
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


# start type


def test_start_type_from_the_speed_in_the_first_moments():
    def start(speeds, **over):
        det = SessionDetector()
        feed(
            det,
            [frame(i / 60, packet_id=i, speed_kph=v, **over) for i, v in enumerate(speeds)],
        )
        return det.kind.start

    stationary = [0.0] * 30 + [5.0, 10.0, 15.0]
    assert start(stationary) == "grid"
    assert start(stationary, total_laps=0, total_cars=1) == "grid"
    leftover = [0.0, 0.0, 0.0] + [100.0] * 30  # a loading-screen frame, then the pace
    assert start(leftover) == "rolling"
    assert start([190.0] * 30, total_laps=0, total_cars=1) == "flying"
    assert start([190.0] * 5) == "unknown", "the window has not closed yet"


def test_start_type_counts_packets_not_the_clock():
    # Two standing frames, then the rest of the burst 0.4 s later on the clock but
    # only a couple of packets on: the window is still open when the pace arrives.
    det = SessionDetector()
    frames = [frame(0.0, packet_id=0, speed_kph=0.0), frame(0.4, packet_id=1, speed_kph=0.0)]
    frames += [frame(0.4 + i / 60, packet_id=2 + i, speed_kph=100.0) for i in range(30)]
    feed(det, frames)
    assert det.kind.start == "rolling"


def test_real_rolling_start_read_through_a_packet_burst():
    """The Nordschleife rolling start (2026-10-15) opens on frames that read 0 km/h
    as the loading screen clears. Delay everything after the first of them by 0.4
    s, as a packet burst does (#157): a clock window would close on the standing
    frames alone and call it a grid start. The packet window still reads rolling."""
    from dataclasses import replace

    frames = list(
        read_recording(FIXTURES / "real-nuc-nordschleife-rolling-start-2026-10-15.jsonl.gz")
    )
    first = next(i for i, f in enumerate(frames) if f.phase is Phase.IN_RACE)
    assert frames[first].speed_kph < 1 and frames[first + 1].speed_kph < 1
    burst = frames[: first + 1] + [replace(f, t=f.t + 0.4) for f in frames[first + 1 :]]
    det = SessionDetector()
    feed(det, burst)
    assert det.kind.start == "rolling"


# real recordings (2026-10-14 and 2026-10-15)


@pytest.mark.parametrize(
    ("fixture", "kind", "fuel_use", "cars_on_track", "start"),
    [
        ("real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz", "lap_race", True, True, "rolling"),
        ("real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz", "lap_race", True, True, "rolling"),
        ("real-nuc-suzuka-east-2026-10-15.jsonl.gz", "solo_laps", True, True, "flying"),
        ("real-nuc-fuji-timed-2026-10-15.jsonl.gz", "solo_timed", False, True, "flying"),
        ("real-nuc-sugo-timed-2026-10-15.jsonl.gz", "solo_timed", False, True, "flying"),
        ("real-n24h-race-lap1-positions-2026-10-14.jsonl.gz", "lap_race", True, True, "rolling"),
    ],
)
def test_real_session_kinds(fixture, kind, fuel_use, cars_on_track, start):
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    for s in read_recording(FIXTURES / fixture, strict=True):
        engine.process(s)
    assert engine.kind.kind == kind
    assert engine.kind.fuel_use is fuel_use
    assert engine.kind.cars_on_track is cars_on_track
    assert engine.kind.start == start


@pytest.mark.parametrize(
    ("fixture", "kind", "start"),
    [
        ("real-nuc-tokyo-east-race-2026-10-15.jsonl.gz", "lap_race", "rolling"),
        ("real-nuc-laguna-seca-race-2026-10-15.jsonl.gz", "lap_race", "rolling"),
        ("real-nuc-tsukuba-brz-drift-2026-10-15.jsonl.gz", "solo_laps", "flying"),
        # 0 km/h on the first racing frames after loading, then 100 behind the pace
        ("real-nuc-nordschleife-rolling-start-2026-10-15.jsonl.gz", "lap_race", "rolling"),
    ],
)
def test_real_demo_kinds(fixture, kind, start):
    """GT7's attract-mode demos (#260; the unnamed mode of #63): the engine ignores
    them, but the detector reads them as it would a drive, with no flag and no fuel."""
    det = SessionDetector()
    feed(det, read_recording(FIXTURES / fixture, strict=True))
    assert det.kind.decision == (kind, False, False, start)


def test_real_qualifying_is_a_timed_field():
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    kinds = set()
    for s in read_recording(FIXTURES / "real-quali-restart-quit-2026-10-14.jsonl.gz", strict=True):
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
    fixture = FIXTURES / "real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz"
    asyncio.run(replay(read_recording(fixture, strict=True), engine, ConsolePlayer()))
    store.close()
    assert spy.seen[-1] == ("lap_race", True)
    db = sqlite3.connect(tmp_path / "index.sqlite")
    rows = db.execute("SELECT session_kind, fuel_use, start_type FROM sessions").fetchall()
    assert rows == [("lap_race", 1, "rolling")]
    summary = json.loads(next((tmp_path / "sessions").glob("*/summary.json")).read_text())
    assert summary["session_kind"]["kind"] == "lap_race"
    assert summary["session_kind"]["fuel_use"] is True
    assert summary["car_name"] == "Honda Civic Si Group A version '87"
    labels = b'fuel_use="on",kind="lap_race",start="rolling"'
    assert b"gt7_session_info{" + labels + b"} 1.0" in metrics.render()


# replays (#243) and demo races (#260)


def check(first, *frames, before=(Phase.MENU, Phase.LOADING)):
    """The verdicts after a start reached through the ``before`` phases (by
    default the loading screen a drive always passes through)."""
    rc = DriverCheck()
    for phase in before:
        rc.see(frame(0, phase=phase))
    rc.start(first)
    verdicts = [rc.observe(f) for f in frames]
    return verdicts


def test_replay_check_reads_draining_fuel_without_the_flag_as_a_replay():
    start = frame(0, packet_id=0, cars_on_track=False, fuel_level=98.3)
    assert check(
        start,
        frame(0.5, packet_id=30, cars_on_track=False, fuel_level=98.3),
        frame(0.9, packet_id=52, cars_on_track=False, fuel_level=97.6),
    ) == [None, "replay"]


@pytest.mark.parametrize(
    ("later", "why"),
    [
        (dict(cars_on_track=True, fuel_level=97.0), "the flag came on"),
        (dict(phase=Phase.PAUSED, fuel_level=97.0), "a pause after a loading screen"),
        (dict(t=3.0, packet_id=60), "three seconds without a drop"),
        (dict(t=1.0, packet_id=180), "180 packets without a drop"),
        (dict(t=1.0, packet_id=-5), "GT7's counter started over"),
        (dict(t=3.0, fuel_capacity=0.0, fuel_level=0.0), "no tank: fuel says nothing"),
    ],
)
def test_replay_check_calls_it_a_drive(later, why):
    start = frame(0, packet_id=0, cars_on_track=False)
    over = dict(t=0.5, packet_id=30, cars_on_track=False)
    over.update(later)
    assert check(start, frame(**over)) == ["drive"], why


def test_replay_check_waits_while_nothing_has_shown():
    start = frame(0, packet_id=0, cars_on_track=False, fuel_level=50.0)
    assert check(start, frame(1.0, packet_id=60, cars_on_track=False, fuel_level=50.0)) == [None]


@pytest.mark.parametrize(
    ("later", "why"),
    [
        (dict(t=3.0, packet_id=60), "three seconds without the flag or a drop"),
        (dict(phase=Phase.MENU, current_lap=-1), "the demo ends inside the window"),
        (dict(phase=Phase.PAUSED), "a pause inside the window"),
    ],
)
def test_driver_check_reads_a_start_straight_from_the_menu_as_a_demo(later, why):
    """2026-10-18: GT7's attract-mode demo goes menu, track screen, lap 1, with no
    loading screen, the flag off and the fuel flat."""
    start = frame(0, packet_id=0, cars_on_track=False, fuel_level=100.0)
    over = dict(t=0.5, packet_id=30, cars_on_track=False, fuel_level=100.0)
    over.update(later)
    rc = DriverCheck()
    for phase in (Phase.LOADING, Phase.MENU, Phase.AT_TRACK):  # loaded once, then the menu
        rc.see(frame(0, phase=phase))
    rc.start(start)
    assert rc.observe(frame(**over)) == "demo", why
    assert rc.why == "it came straight from the menu with no loading screen"


def test_driver_check_still_sees_the_flag_from_the_menu_as_a_drive():
    start = frame(0, packet_id=0, cars_on_track=False)
    later = frame(0.5, packet_id=30, cars_on_track=True)
    assert check(start, later, before=(Phase.MENU, Phase.AT_TRACK)) == ["drive"]


@pytest.mark.parametrize(
    ("cars", "verdict"),
    [
        (12, "demo"),  # the demo joined on lap 2 of 5, 2026-10-18 11:01
        (-1, "drive"),  # 2026-10-14 practice joined on lap 7: no field reported
        (1, "drive"),
    ],
)
def test_driver_check_with_no_menu_seen_goes_by_the_field(cars, verdict):
    start = frame(0, packet_id=0, cars_on_track=False, current_lap=2, total_cars=cars)
    later = frame(3.0, packet_id=180, cars_on_track=False, current_lap=2, total_cars=cars)
    assert check(start, later, before=()) == [verdict]
