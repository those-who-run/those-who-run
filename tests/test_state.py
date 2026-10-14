from dataclasses import fields

from gt_telem.models.telemetry import Telemetry
from gt_telem.models.telemetry_packet import TelemetryPacket

from gt7_race_engineer.state import (
    STATE_FORMAT_VERSION,
    Phase,
    RaceState,
    derive_phase,
    lap_completed,
    lap_time_posted,
    race_ended,
    race_started,
)
from tests.conftest import make_state


def make_telemetry(**over) -> Telemetry:
    values = {}
    for f in fields(TelemetryPacket):
        if f.default is not None and f.default is not f.default_factory:  # optional tail fields
            continue
        values[f.name] = 0 if f.type in (int, "int") else 0.0
    values.update(over)
    return Telemetry(**values)


def test_derive_phase():
    # (current_lap, total_laps, is_paused, is_loading)
    assert derive_phase(-1, -1, False, False) is Phase.MENU
    assert derive_phase(-1, -1, True, False) is Phase.MENU
    assert derive_phase(0, 0, False, True) is Phase.LOADING
    assert derive_phase(0, 2, False, False) is Phase.AT_TRACK
    assert derive_phase(1, 2, False, False) is Phase.IN_RACE
    assert derive_phase(7, 0, False, False) is Phase.IN_RACE, "time trial laps count"
    assert derive_phase(3, 2, True, False) is Phase.PAUSED
    assert derive_phase(3, 2, False, False) is Phase.FINISHED


def test_from_telemetry_uses_flag_bits():
    tel = make_telemetry(
        packet_id=42,
        current_lap=2,
        total_laps=5,
        best_lap_time_ms=100000,
        last_lap_time_ms=101000,
        fuel_level=55.5,
        fuel_capacity=100.0,
        speed_mps=50.0,
        engine_rpm=7000.0,
        tire_fl_temp=70.0,
        tire_fr_temp=71.0,
        tire_rl_temp=72.0,
        tire_rr_temp=73.0,
        water_temp=90.0,
        oil_temp=95.0,
        race_start_pos=4,
        total_cars=16,
        flags=0b0001,  # cars_on_track
    )
    s = RaceState.from_telemetry(tel, t=12.5)
    assert s.phase is Phase.IN_RACE
    assert s.is_race and s.position == 4
    assert s.t == 12.5
    assert s.packet_id == 42
    assert s.current_lap == 2 and s.total_laps == 5
    assert s.best_lap_ms == 100000 and s.last_lap_ms == 101000
    assert s.fuel_level == 55.5
    assert s.speed_kph == 180.0
    assert s.tire_temp == (70.0, 71.0, 72.0, 73.0)
    assert s.track_id is None  # only set by the live client
    assert s.race_start_pos == 4 and s.total_cars == 16

    paused = make_telemetry(current_lap=2, flags=0b0011)
    assert RaceState.from_telemetry(paused, 0).phase is Phase.PAUSED
    loading = make_telemetry(current_lap=2, flags=0b0101)
    assert RaceState.from_telemetry(loading, 0).phase is Phase.LOADING
    practice = make_telemetry(current_lap=7, total_laps=0, race_start_pos=-1, flags=0)
    ps = RaceState.from_telemetry(practice, 0)
    assert ps.phase is Phase.IN_RACE and not ps.is_race and ps.position is None


def test_dict_roundtrip():
    s = make_state(t=3.25, track_id=None)
    d = s.to_dict()
    assert d["phase"] == "in_race" and d["v"] == STATE_FORMAT_VERSION
    assert RaceState.from_dict(d) == s


def test_laps_left():
    assert make_state(current_lap=3, total_laps=5).laps_left == 3
    assert make_state(current_lap=5, total_laps=5).laps_left == 1
    assert make_state(current_lap=1, total_laps=0).laps_left is None


def test_transitions():
    menu = make_state(phase=Phase.MENU, current_lap=-1, total_laps=-1)
    at_track = make_state(current_lap=0)
    grid = make_state(current_lap=1)
    lap2 = make_state(current_lap=2, last_lap_ms=100000, best_lap_ms=100000)
    paused = make_state(phase=Phase.PAUSED, current_lap=2, last_lap_ms=100000)
    loading = make_state(phase=Phase.LOADING, current_lap=1)
    assert race_started(None, grid)
    assert race_started(menu, grid)
    assert race_started(at_track, grid)
    assert not race_started(grid, lap2)
    assert not race_started(paused, lap2), "resuming from pause is not a start"
    assert not race_started(loading, grid), "a loading blip mid-race is not a start"
    assert lap_completed(grid, lap2)
    assert not lap_completed(lap2, lap2)
    assert lap_time_posted(grid, lap2)
    assert not lap_time_posted(lap2, lap2)
    assert race_ended(lap2, menu)
    assert race_ended(lap2, at_track)
    assert not race_ended(lap2, loading), "loading or pause suspends, it does not end"
    assert not race_ended(menu, grid)
    last = make_state(current_lap=5, total_laps=5, last_lap_ms=100000)
    finished = make_state(current_lap=6, total_laps=5, last_lap_ms=99000)
    assert finished.phase is Phase.FINISHED
    assert lap_completed(last, finished), "the finish-line frame still completes a lap"
    assert lap_time_posted(last, finished)
    assert race_ended(last, finished)
    assert not race_ended(finished, finished)
    # GT7 replays the end of the race after the results screen: not a new start
    assert not race_started(at_track, finished)
