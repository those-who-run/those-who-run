"""Pit-stop detection against real stops at three tracks, and every other fixture.

The three stops put the finish line in a different part of the stop: Suzuka
East in the entry cut-scene (2026-10-15), Willow Springs in the exit cut-scene
and Circuit Gilles Villeneuve in the pit lane itself (both 2026-10-17).
"""

from pathlib import Path

import pytest

from tests.conftest import make_state
from those_who_run.pitstop import NO_STOPS, PitDetector, PitStatus
from those_who_run.replay import read_recording
from those_who_run.state import Phase

FIXTURES = Path(__file__).parent / "fixtures"
GILLES = FIXTURES / "real-nuc-gilles-villeneuve-pit-stop-2026-10-17.jsonl.gz"
WILLOW = FIXTURES / "real-nuc-willow-springs-pit-stop-2026-10-17.jsonl.gz"
SUZUKA = FIXTURES / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz"
SUGO = FIXTURES / "real-nuc-sugo-two-stops-2026-10-18.jsonl.gz"
STOPS = (GILLES, WILLOW, SUZUKA)


def detect(frames) -> tuple[PitDetector, list[tuple[int, PitStatus]]]:
    """The detector after ``frames``, and each change with the lap it came on."""
    det = PitDetector()
    changes = []
    for s in frames:
        status = det.observe(s)
        if status is not None:
            changes.append((s.current_lap, status))
    return det, changes


def test_real_gilles_villeneuve_stop_crosses_the_line_in_the_pit_lane():
    """Twelve laps, Mazda RX-VISION GT3: in on lap 6 at 8.7 per cent, a full tank and
    tyres, and the line crossed on the way out of the box at the limiter."""
    frames = list(read_recording(GILLES, strict=True))
    det, changes = detect(frames)
    assert [(lap, st.in_pit_lane, st.stint) for lap, st in changes] == [(6, True, 1), (7, False, 2)]
    (stop,) = det.status.stops
    assert stop.record() == {
        "stop": 1,
        "in_lap": 6,
        "out_lap": 7,
        "pit_lane_secs": 30.22,  # limiter, box and the drive out
        "stationary_secs": 17.13,
        "fuel_before": 8.685,
        "fuel_after": 100.0,
        "fuel_added": 91.315,
        "tyres_changed": True,
        "pit_lane_kph": 60.0,
        "position_before": 5,
        "position_after": 10,
        "evidence": "entry loading cut at 60.0 km/h; exit loading cut",
    }
    # the lap 6 -> 7 crossing is a driving frame inside the pit lane
    det = PitDetector()
    for prev, s in zip(frames, frames[1:], strict=False):
        det.observe(s)
        if prev.current_lap == 6 and s.current_lap == 7:
            assert s.phase is Phase.IN_RACE and s.speed_kph == pytest.approx(60.0, abs=0.1)
            assert det.status.in_pit_lane
            break
    else:
        pytest.fail("no lap 6 -> 7 crossing")


def test_real_willow_springs_stop_crosses_the_line_in_the_exit_cut():
    """Big Willow, Toyota 86 Gr.B: a partial refuel (16 -> 65) with tyres, and lap 7
    posted on the loading frame that puts the car at the pit exit at 80 km/h."""
    det, changes = detect(read_recording(WILLOW, strict=True))
    assert [(lap, st.in_pit_lane) for lap, st in changes] == [(6, True), (7, False)]
    (stop,) = det.status.stops
    assert (stop.in_lap, stop.out_lap) == (6, 7)
    assert stop.fuel_before == pytest.approx(16.01, abs=0.01)
    assert stop.fuel_after == pytest.approx(65.35, abs=0.01)
    assert stop.tyres_changed
    assert stop.pit_lane_secs == pytest.approx(13.11, abs=0.01)
    assert stop.pit_lane_kph == pytest.approx(60.0, abs=0.1)


def test_real_suzuka_east_stop_crosses_the_line_in_the_entry_cut():
    """Lap 3 posted on the entry cut: the in-lap is 3 although the car enters the
    pit lane on lap 4's counter. Fuel only, no tyres."""
    det, changes = detect(read_recording(SUZUKA, strict=True))
    assert [(lap, st.in_pit_lane) for lap, st in changes] == [(4, True), (4, False)]
    (stop,) = det.status.stops
    assert (stop.in_lap, stop.out_lap) == (3, 4)
    assert stop.fuel_added == pytest.approx(77.1, abs=0.01)
    assert not stop.tyres_changed


def test_real_sugo_two_stops_cross_the_line_in_the_pit_lane():
    """Twelve laps, Mazda RX-VISION GT3: in at the end of laps 4 and 8 on 1.5 and
    3.2 per cent, the line crossed at the 60 km/h cut each time, three stints."""
    det, changes = detect(read_recording(SUGO, strict=True))
    assert [(lap, st.in_pit_lane, st.stint) for lap, st in changes] == [
        (5, True, 1),
        (5, False, 2),
        (9, True, 2),
        (9, False, 3),
    ]
    first, second = det.status.stops
    assert [(s.in_lap, s.out_lap, s.tyres_changed) for s in (first, second)] == [
        (4, 5, True),
        (8, 9, True),
    ]
    assert first.fuel_before == pytest.approx(1.52, abs=0.01)
    assert second.fuel_before == pytest.approx(3.24, abs=0.01)
    assert first.pit_lane_secs == pytest.approx(25.79, abs=0.01)
    assert second.pit_lane_secs == pytest.approx(25.63, abs=0.01)
    assert det.status.record()["stints"] == 3


def test_pit_laps_roles_and_stints():
    det, _ = detect(read_recording(GILLES, strict=True))
    status = det.status
    assert [lap for lap in range(1, 13) if status.is_pit_lap(lap)] == [6, 7]
    assert [status.lap_role(lap) for lap in (5, 6, 7, 8)] == [None, "in", "out", None]
    assert (status.stint, status.stint_start_lap) == (2, 7)
    assert status.record()["stints"] == 2
    assert (NO_STOPS.stint, NO_STOPS.stint_start_lap, NO_STOPS.is_pit_lap(1)) == (1, 1, False)


def test_an_open_stop_marks_every_lap_from_the_in_lap():
    frames = [
        f
        for f in read_recording(GILLES, strict=True)
        if f.current_lap < 7 or f.phase is not Phase.IN_RACE
    ]
    det, _ = detect(frames)
    assert det.status.in_pit_lane
    assert det.status.lap_role(6) == "in" and det.status.lap_role(7) == "out"
    assert det.status.stint == 1 and det.status.stops[0].pit_lane_secs is None


@pytest.mark.parametrize("path", STOPS, ids=lambda p: p.stem)
def test_a_lost_cut_frame_is_seen_as_a_teleport(path):
    """Each pit cut is a single packet. Without the loading frames the car still
    jumps 118 to 330 m between two packets, and the same stop is found."""
    _, with_cuts = detect(read_recording(path, strict=True))
    det, _ = detect(
        s
        for s in read_recording(path, strict=True)
        if not (s.phase is Phase.LOADING and s.current_lap >= 1)
    )
    (stop,) = det.status.stops
    (expected,) = with_cuts[-1][1].stops
    assert (stop.in_lap, stop.out_lap) == (expected.in_lap, expected.out_lap)
    assert stop.fuel_after == expected.fuel_after
    assert stop.evidence == "entry teleport at 60.0 km/h; exit teleport"


@pytest.mark.parametrize(
    "path",
    sorted(p for p in FIXTURES.glob("*.jsonl.gz") if p not in (*STOPS, SUGO)),
    ids=lambda p: p.stem,
)
def test_no_stop_in_any_other_recording(path):
    """Races, time trials, qualifying with a restart and a quit, a pit call ignored:
    no loading screen keeps the lap counter, and packets that arrive in a burst
    are not a teleport."""
    det, changes = detect(read_recording(path, strict=True))
    assert changes == [] and det.status == NO_STOPS


def _frame(t, lap=3, speed=150.0, x=0.0, phase=Phase.IN_RACE, fuel=50.0, **over):
    return make_state(
        t=t,
        packet_id=int(t * 60),
        current_lap=lap,
        total_laps=10,
        speed_kph=speed,
        pos_x=x,
        phase=phase,
        fuel_level=fuel,
        **over,
    )


def test_a_quit_or_a_restart_is_not_a_stop():
    det = PitDetector()
    # quitting: the loading frame resets the lap counter
    for s in (
        _frame(0.0, x=0),
        _frame(0.1, lap=0, phase=Phase.LOADING, x=500),
        _frame(0.2, lap=0, phase=Phase.AT_TRACK),
    ):
        det.observe(s)
    # a restart: back on the grid at lap 1, far from where the car was
    for s in (_frame(1.0, x=0), _frame(1.02, lap=1, x=900, speed=0.0)):
        assert det.observe(s) is None
    assert det.status == NO_STOPS


def test_a_stop_whose_exit_cut_was_lost_ends_at_racing_speed():
    det = PitDetector()
    frames = [
        _frame(0.0, x=0),
        _frame(0.02, phase=Phase.LOADING, x=200),
        _frame(0.04, speed=60.0, x=200),
        _frame(5.0, speed=0.0, x=260),
        _frame(10.0, speed=0.0, x=260, fuel=100.0),
        _frame(15.0, speed=80.0, x=300, fuel=100.0),
        _frame(16.0, lap=4, speed=101.0, x=330, fuel=100.0),  # no cut: the packet was lost
    ]
    changes = [det.observe(s) for s in frames]
    assert changes[2] is not None and changes[2].in_pit_lane
    done = changes[-1]
    assert done is not None and not done.in_pit_lane
    (stop,) = done.stops
    assert (stop.in_lap, stop.out_lap, stop.fuel_added) == (3, 4, 50.0)
    assert stop.evidence.endswith("over 100 km/h")


def test_a_pause_in_the_pits_keeps_the_stop_and_is_not_time_at_rest():
    det = PitDetector()
    for s in (
        _frame(0.0, x=0),
        _frame(0.02, phase=Phase.LOADING, x=200),
        _frame(0.04, speed=0.0, x=200),
        _frame(1.04, speed=0.0, x=200),
        _frame(1.06, speed=0.0, x=200, phase=Phase.PAUSED),
        _frame(60.0, speed=0.0, x=200),
    ):
        det.observe(s)
    assert det.status.in_pit_lane
    assert det.status.stops[0].stationary_secs == pytest.approx(1.0)  # 0.04 to 1.04


def _reset_to_track(lap=3, fuel_after=50.0, **over):
    """Off at 150 km/h, put back on track 300 m away, straight back up to speed."""
    hot = (90.0, 90.0, 90.0, 90.0)
    return [
        _frame(0.0, lap=lap, x=0, tire_temp=hot),
        _frame(0.02, lap=lap, phase=Phase.LOADING, x=300, tire_temp=hot),
        _frame(0.04, lap=lap, speed=40.0, x=300, tire_temp=hot),
        _frame(2.0, lap=lap, speed=80.0, x=340, tire_temp=hot),
        _frame(4.0, lap=lap, speed=110.0, x=400, fuel=fuel_after, **{"tire_temp": hot, **over}),
    ]


@pytest.mark.parametrize("cut", ["loading", "teleport"])
def test_a_reset_to_track_is_a_teleport_not_a_stop(cut):
    frames = _reset_to_track()
    if cut == "teleport":
        del frames[1]
    det, changes = detect(frames)
    assert [s.in_pit_lane for _, s in changes] == [True, False]
    assert det.status.stops == () and not det.status.in_pit_lane
    assert det.status.stint == 1 and not det.status.is_pit_lap(3)
    (jump,) = det.status.teleports
    assert (jump.lap, jump.t) == (3, 4.0) and jump.entry_t < jump.t
    assert jump.evidence.endswith("over 100 km/h; never at rest, no fuel, no tyres")


def test_a_stop_without_rest_still_counts_with_fuel_or_tyres():
    det, _ = detect(_reset_to_track(fuel_after=80.0))
    assert len(det.status.stops) == 1 and det.status.teleports == ()
    det, _ = detect(_reset_to_track(tire_temp=(60.0, 60.0, 60.0, 60.0)))
    (stop,) = det.status.stops
    assert stop.tyres_changed and det.status.stint == 2


def test_engine_keeps_the_stint_through_a_reset_to_track(tmp_path):
    from those_who_run.callouts import CalloutQueue
    from those_who_run.config import DEFAULT_RULES
    from those_who_run.engine import Engine
    from those_who_run.metrics import Metrics
    from those_who_run.rules import build_rules
    from those_who_run.rules.fuel import FuelRule
    from those_who_run.store import SessionStore

    rules = build_rules(DEFAULT_RULES["rules"])
    engine = Engine(rules, CalloutQueue(), SessionStore(tmp_path), Metrics())
    engine.process(_frame(-1.0, lap=0, phase=Phase.AT_TRACK, speed=0.0))
    for s in _reset_to_track(lap=1):
        engine.process(s)
    fuel = next(r for r in rules if isinstance(r, FuelRule))
    assert fuel.stint == 1 and not fuel.pits.in_pit_lane and fuel.pits.stops == ()
    assert len(fuel.pits.teleports) == 1
    engine.recorder.close()
