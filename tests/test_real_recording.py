"""Regression test against a slice of a real GT7 session recorded on 2026-10-14.

The fixture keeps every frame where a tracked field changed, its neighbours,
and one frame per second otherwise. It covers: practice laps (time trial mode,
no cars on track), a two-lap race from P10 to P6, the chequered flag at
"lap 3 of 2", the results screen, and the replay blip GT7 emits afterwards.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.rules import FuelRule, build_rules
from those_who_run.state import Phase, race_ended, race_restarted, race_started
from those_who_run.store import SessionStore

FIXTURE = Path(__file__).parent / "fixtures" / "real-race-2laps-2026-10-14.jsonl"
QUALI = Path(__file__).parent / "fixtures" / "real-quali-restart-quit-2026-10-14.jsonl"
PIT_STOP = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl"
NO_STOP = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-no-stop-2026-10-15.jsonl"
GILLES_STOP = (
    Path(__file__).parent / "fixtures" / "real-nuc-gilles-villeneuve-pit-stop-2026-10-17.jsonl"
)
WILLOW_STOP = (
    Path(__file__).parent / "fixtures" / "real-nuc-willow-springs-pit-stop-2026-10-17.jsonl"
)


def test_fixture_phases_cover_the_whole_session():
    phases = {s.phase for s in read_recording(FIXTURE)}
    assert phases == {Phase.MENU, Phase.LOADING, Phase.AT_TRACK, Phase.IN_RACE, Phase.FINISHED}


async def test_real_session_callouts_and_sessions(tmp_path):
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), SessionStore(tmp_path)
    )
    spoken = await replay(read_recording(FIXTURE), engine, ConsolePlayer())
    texts = [c.text for c in spoken]
    assert texts == [
        # practice session: the engineer started mid-session on lap 7, no brief
        "Lap seven. forty-nine point seven.",
        # leaving practice: no flag, so a short summary (GT7's counter, best lap)
        "Session done. Seven laps. Best lap forty-nine point seven.",
        # the race: P10 on the grid (the track was unknown: standing start, lap 1 only)
        "Two laps. P ten of twenty.",
        "Up to ninth.",
        "Final lap.",
        "Lap one. fifty-one point zero.",
        "Up to eighth.",
        "Up to seventh.",
        # lap 1 starts on the grid ahead of the line and is short, so like GT7 the
        # engineer does not count it as a best: no delta for lap 2
        "Lap two. fifty-three point one.",
        # P6 was taken in the last two seconds; the summary reads it off the flag frame
        "Chequered flag. Finished sixth. Best lap fifty-three point one. "
        "Fuel used thirty-eight percent.",
    ]
    # practice + race, and nothing for the post-race replay frames
    assert engine.races_started == 2
    sessions = sorted((tmp_path / "sessions").iterdir())
    assert len(sessions) == 2
    race = sessions[1]
    assert sorted(p.name for p in race.glob("lap-*.parquet")) == [
        "lap-01.parquet",
        "lap-02.parquet",
    ]
    assert (race / "summary.json").exists()


async def test_real_qualifying_restart_and_quit(tmp_path):
    """Nordschleife qualifying, thinned to one frame per two seconds plus every
    transition: a lap, a restart from the pause menu (fuel refilled, counter back
    to 1), two more laps, then quit (PAUSED -> LOADING -> AT_TRACK)."""
    store = SessionStore(tmp_path)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    spoken = await replay(read_recording(QUALI), engine, ConsolePlayer())
    assert [c.text for c in spoken] == [
        # qualifying looks like a timed race to GT7: no lap total, twenty cars
        "Timed race. P one of twenty.",
        "Nurburgring twenty-four hour.",  # probable 78 s in, on the first line crossing
        "Fuel. three laps remaining.",
        "Lap one. eight twenty-six point four.",
        "Timed race. P one of twenty.",  # the restart briefs again
        "Nurburgring twenty-four hour.",
        "Lap one. eight twenty point four.",
        # GT7 left both lap 1s out of its best (out of the pits, then after the
        # restart), so lap 2 has nothing to be measured against
        "Lap two. eight twenty point two.",
        # no summary: the session was quit, not finished
    ]
    assert engine.races_started == 2
    assert store.session is None, "the quit closed the second session"
    store.close()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    sessions = db.execute(
        "SELECT laps_completed, best_lap_ms, ended_at IS NOT NULL FROM sessions ORDER BY id"
    ).fetchall()
    assert sessions == [(1, 506429, 1), (2, 500204, 1)]
    laps = db.execute("SELECT lap, complete FROM laps ORDER BY session_id, lap").fetchall()
    assert laps == [(1, 1), (2, 0), (1, 1), (2, 1), (3, 0)]


def test_real_pause_and_resume_is_neither_a_start_nor_an_end():
    """The qualifying fixture pauses and resumes three times mid-lap (2026-10-14),
    once after the restart. A pause keeps the race: no start, no end, no restart,
    and the paused lap is one lap."""
    states = list(read_recording(QUALI))
    resumes = [
        (prev, cur)
        for prev, cur in zip(states, states[1:], strict=False)
        if prev.phase is Phase.PAUSED and cur.phase is Phase.IN_RACE
    ]
    assert len(resumes) == 3
    for prev, cur in resumes:
        assert cur.current_lap == prev.current_lap and cur.fuel_level == prev.fuel_level
        assert not race_started(prev, cur)
        assert not race_restarted(prev, cur)
        assert not race_ended(prev, cur)


async def _replay_with_store(path, tmp_path, end=False):
    store = SessionStore(tmp_path)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    spoken = await replay(read_recording(path), engine, ConsolePlayer())
    if end and engine.prev is not None:  # the fixture stops mid-race: write the summary
        store.set_pits(engine.pits.status)
        store.end_session(engine.prev)
    store.close()
    laps = (
        sqlite3.connect(tmp_path / "index.sqlite")
        .execute("SELECT lap, lap_time_ms FROM laps ORDER BY lap")
        .fetchall()
    )
    return engine, [c.text for c in spoken], laps


async def test_real_pit_stop_race(tmp_path):
    """Suzuka East, six laps against one car, recorded on the NUC 2026-10-15. Heavy
    fuel wear, the pit call after lap 2, and a stop on lap 3: GT7 posts the pit-in
    lap on a loading frame as the car crosses into the pit cut-scene, then refuels
    behind two more loading screens (22.9 to 100)."""
    engine, texts, laps = await _replay_with_store(PIT_STOP, tmp_path)
    assert texts == [
        "Six laps. P one of two.",
        "Down to second.",
        "Up to first.",
        "Fuel. two laps remaining.",
        "Lap one. fifty-seven point one.",  # from the grid, short: not a best
        "Pit this lap.",
        "Fuel. one lap remaining.",
        "Lap two. one oh zero point five.",
        # the in-lap, posted on the loading frame; no fuel call on the way into the pits
        "Lap three. one twenty-two point five. twenty-two point zero over best.",
        "Lap four. one oh nine point nine. nine point four over best.",
        "Final lap.",
        "Lap five. fifty-nine point five. New best by one point zero.",
        "Lap six. one oh zero point three. zero point eight over best.",
        "Chequered flag. Finished first. Best lap fifty-nine point five. "
        "Fuel used one hundred and thirty percent.",
    ]
    assert engine.races_started == 1
    assert laps == [(1, 57109), (2, 60538), (3, 82544), (4, 69892), (5, 59541), (6, 60310)]
    # the in-lap and the out-lap are not fuel laps: laps 2, 5 and 6 are averaged,
    # not the in-lap's 15.0 (lifting after the pit call) nor the refuelled out-lap
    assert _pit_column(tmp_path) == [None, None, "in", "out", None, None]
    fuel = _fuel_rule(engine)
    assert [round(x, 1) for x in fuel.consumption] == [27.7, 18.7, 19.4]


def _fuel_rule(engine: Engine) -> FuelRule:
    return next(r for r in engine.rules if isinstance(r, FuelRule))


def _pit_column(tmp_path):
    rows = sqlite3.connect(tmp_path / "index.sqlite").execute("SELECT pit FROM laps ORDER BY lap")
    return [pit for (pit,) in rows]


def _summary(tmp_path):
    (path,) = (tmp_path / "sessions").glob("*/summary.json")
    return json.loads(path.read_text(encoding="utf-8"))


async def test_real_pit_stop_in_the_pit_lane_is_left_out_of_the_fuel_average(tmp_path):
    """Circuit Gilles Villeneuve, laps 5 to 8 of twelve, NUC 2026-10-17. The pit call
    comes after lap 5; lap 6 is the in-lap, crossed in the pit lane after a full
    tank, and lap 7 the out-lap, which starts in the pit lane at the limiter and
    used 15.0 against 16.4 for lap 8. Neither is a fuel lap."""
    engine, texts, laps = await _replay_with_store(GILLES_STOP, tmp_path, end=True)
    assert texts == [
        "Eight laps to go. P seven of twenty.",  # the fixture starts on lap 5
        "Pit this lap.",
        "Fuel. one lap remaining.",
        "Lap five. one thirty-eight point four. zero point nine over best.",
        "Up to sixth.",
        "Up to fifth.",
        # quiet in the pit lane while P5 drops to P11 in the box
        "Lap six. two oh zero point one. twenty-two point five over best.",
        "Down to tenth.",  # the net change, once out of the pits
        "Up to ninth.",
        "Lap seven. one forty-two point two. four point seven over best.",
        "Up to sixth.",
        "Lap eight. one thirty-seven point eight. zero point three over best.",
    ]
    assert [lap for lap, _ in laps] == [5, 6, 7, 8, 9]
    assert _pit_column(tmp_path) == [None, "in", "out", None, None]
    fuel = _fuel_rule(engine)
    assert [round(x, 2) for x in fuel.consumption] == [14.34, 16.35]  # laps 5 and 8
    assert fuel.stint == 2
    summary = _summary(tmp_path)
    assert summary["stints"] == 2
    (stop,) = summary["pit_stops"]
    assert (stop["in_lap"], stop["out_lap"], stop["tyres_changed"]) == (6, 7, True)
    assert stop["fuel_added"] == pytest.approx(91.3, abs=0.1)
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT pit_stops FROM sessions").fetchall() == [(1,)]


async def test_real_pit_stop_crossed_in_the_exit_cut(tmp_path):
    """Willow Springs Big Willow, laps 6 to 8 of ten, NUC 2026-10-17. Lap 6 is posted
    on the loading frame that takes the car out of the pits: the crossing out of the
    pits, not into them. The out-lap (13.3) is left out; lap 8 (12.6) is the first
    fuel lap of the new stint."""
    engine, texts, laps = await _replay_with_store(WILLOW_STOP, tmp_path, end=True)
    fuel = [t for t in texts if t.startswith(("Fuel", "Pit", "Lap"))]
    assert fuel == [
        "Lap six. one thirty-six point six. sixteen point six over best.",
        "Lap seven. one twenty-four point two. four point three over best.",
        "Lap eight. one twenty-one point nine. one point nine over best.",
    ]
    assert _pit_column(tmp_path) == ["in", "out", None, None]  # lap 9 is cut short
    assert [round(x, 2) for x in _fuel_rule(engine).consumption] == [12.62]
    (stop,) = _summary(tmp_path)["pit_stops"]
    assert (stop["in_lap"], stop["out_lap"]) == (6, 7)
    assert stop["fuel_after"] == pytest.approx(65.35, abs=0.01)  # a part refuel


async def test_real_race_with_the_pit_call_ignored(tmp_path):
    """Suzuka East, six laps from P10 of twenty, NUC 2026-10-15. The driver ignored
    the pit call and finished on the last litre."""
    _, texts, laps = await _replay_with_store(NO_STOP, tmp_path)
    assert texts == [
        "Six laps. P ten of twenty.",
        # quiet for fifteen seconds while the field shuffles, then one call a settle apart
        "Down to twelfth.",
        "Up to eleventh.",
        "Down to thirteenth.",
        "Lap one. one oh zero point four.",
        # Suzuka East is only certain at the line: no track name a lap in
        "Up to tenth.",
        "Down to eleventh.",
        "Up to tenth.",
        "Up to ninth.",
        "Lap two. one oh four point six.",
        "Up to sixth.",
        "Up to fourth.",
        "Down to fifth.",
        "Up to fourth.",
        "Lap three. one oh three point one. New best by one point five.",
        "Up to third.",
        "Up to second.",
        "Pit this lap.",
        "Lap four. one oh one point two. New best by two point zero.",
        "Fuel. one lap remaining.",
        "Fuel critical. Less than one lap.",
        "Final lap.",
        "Lap five. one oh three point four. two point two over best.",
        "Lap six. one oh four point zero. two point eight over best.",
        "Chequered flag. Finished second. Best lap one oh one point two. "
        "Fuel used ninety-seven percent.",
    ]
    assert [lap for lap, _ in laps] == [1, 2, 3, 4, 5, 6]
