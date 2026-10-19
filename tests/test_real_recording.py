"""Regression test against a slice of a real GT7 session recorded on 2026-10-14.

The fixture keeps every frame where a tracked field changed, its neighbours,
and one frame per second otherwise. It covers: practice laps (time trial mode,
no cars on track), a two-lap race from P10 to P6, the chequered flag at
"lap 3 of 2", the results screen, and the replay blip GT7 emits afterwards.
"""

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.results import build_card
from those_who_run.rules import FuelRule, build_rules
from those_who_run.state import Phase, race_ended, race_restarted, race_started
from those_who_run.store import SessionStore

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "real-race-2laps-2026-10-14.jsonl.gz"
QUALI = Path(__file__).parent / "fixtures" / "real-quali-restart-quit-2026-10-14.jsonl.gz"
PIT_STOP = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz"
NO_STOP = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz"
GILLES_STOP = (
    Path(__file__).parent / "fixtures" / "real-nuc-gilles-villeneuve-pit-stop-2026-10-17.jsonl.gz"
)
WILLOW_STOP = (
    Path(__file__).parent / "fixtures" / "real-nuc-willow-springs-pit-stop-2026-10-17.jsonl.gz"
)
SUGO_STOPS = Path(__file__).parent / "fixtures" / "real-nuc-sugo-two-stops-2026-10-18.jsonl.gz"
SUGO_REPLAY = Path(__file__).parent / "fixtures" / "real-nuc-sugo-replay-2026-10-18.jsonl.gz"
LAGUNA_DEMO = Path(__file__).parent / "fixtures" / "real-nuc-laguna-seca-demo-2026-10-18.jsonl.gz"
SUGO_RESTARTS = Path(__file__).parent / "fixtures" / "real-nuc-sugo-restarts-2026-10-18.jsonl.gz"


def _spoken_when(path):
    """Replay ``path``; each callout with the frame time it was spoken at, and the
    engine. The replay speaks a callout on the frame it is due."""
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    spoken = []
    for s in read_recording(path, strict=True):
        engine.process(s)
        while (c := engine.queue.pop(s.t)) is not None:
            spoken.append((s.t, c))
    return engine, spoken


def _in_the_lane(engine, spoken):
    return [
        c.text
        for t, c in spoken
        for stop in engine.pits.status.stops
        if stop.entry_t <= t < (stop.exit_t or float("inf"))
    ]


@pytest.mark.parametrize(
    "path",
    [SUGO_STOPS, GILLES_STOP, WILLOW_STOP, PIT_STOP],
    ids=["sugo", "gilles", "willow", "suzuka"],
)
def test_real_pit_lane_is_quiet_from_entry_to_exit(path):
    """#244 AC1 (SUGO) and #155 AC1 (Gilles Villeneuve, Willow Springs): nothing is
    spoken between pit entry and pit exit, whether the line is crossed in the entry
    cut, the lane itself or the exit cut."""
    engine, spoken = _spoken_when(path)
    assert engine.pits.status.stops
    assert _in_the_lane(engine, spoken) == []


def test_real_sugo_two_stops_lane_across_the_line():
    """Sportsland SUGO, twelve laps, 2026-10-18 (outing 20261018-094323). The
    lane crosses the line, so the in-laps (4 and 8) end at the entry cut and the
    box falls on the out-laps (5 and 9). Live, "Dropped back to eighth" came 0.6 s
    before the first entry (the car stopped at the lane mouth), lap 4 was called in
    the lane with "slower by seven point nine, let's find the rhythm", and the
    out-laps were "twenty-five point one off best" (#244)."""
    engine, spoken = _spoken_when(SUGO_STOPS)
    first, second = engine.pits.status.stops
    assert [(s.in_lap, s.out_lap) for s in (first, second)] == [(4, 5), (8, 9)]
    # AC1: after each exit, the held in-lap call and then the net position call
    for stop, net in ((first, "Down to eighteenth."), (second, "Down to twentieth.")):
        after = [c.text for t, c in spoken if stop.exit_t <= t < stop.exit_t + 10]
        assert after[1] == net, after
        assert after[0].startswith("In lap, ")
    # R2: the place lost at the lane mouth, 0.7 s before the entry cut, is dropped
    before = [c.text for t, c in spoken if first.entry_t - 5 <= t < first.entry_t]
    assert before == []
    # AC2: laps 4, 5, 8 and 9 hold a stop: no delta to best, no coaching tag
    laps = [c.text for _, c in spoken if c.rule == "lap_time"]
    assert laps[3:9] == [
        "In lap, one thirty point one.",
        "Out lap, one forty-seven point three.",
        "Lap six. one twenty-two point nine. zero point seven over best.",
        "Lap seven. one twenty-three point two. one point zero over best.",
        "In lap, one forty-seven point seven.",
        "Out lap, one forty-seven point five.",
    ]


def test_fixture_phases_cover_the_whole_session():
    phases = {s.phase for s in read_recording(FIXTURE, strict=True)}
    assert phases == {Phase.MENU, Phase.LOADING, Phase.AT_TRACK, Phase.IN_RACE, Phase.FINISHED}


async def test_real_session_callouts_and_sessions(tmp_path):
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), SessionStore(tmp_path)
    )
    spoken = await replay(read_recording(FIXTURE, strict=True), engine, ConsolePlayer())
    texts = [c.text for c in spoken]
    assert texts == [
        # practice session: the engineer started mid-session on lap 7 (#265)
        "Back with you. Lap seven.",
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
        "Chequered flag. Finished sixth. Best lap fifty-three point one.",
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
    spoken = await replay(read_recording(QUALI, strict=True), engine, ConsolePlayer())
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


def test_real_restart_goes_straight_back_to_lap_1():
    """The restart in qualifying (2026-10-14) takes the counter from lap 2 to lap 1
    in one frame: no lap 0 between, with the car moved and the tank refilled on
    that frame. A race restart goes through a loading screen at lap 0 instead,
    on lap 1 as on lap 2 (SUGO 2026-10-18, see the next test), so lap 1 -> lap 1
    is never seen (#157)."""
    states = list(read_recording(QUALI))
    (i,) = [i for i, s in enumerate(states) if i and race_restarted(states[i - 1], s)]
    before, after = states[i - 1], states[i]
    assert (before.current_lap, after.current_lap) == (2, 1)
    assert before.phase is after.phase is Phase.IN_RACE
    assert after.fuel_level == 100.0 > before.fuel_level
    driving = [s for s in states[: i + 1] if s.phase is not Phase.MENU][-60:]
    assert all(s.current_lap >= 1 for s in driving), "no lap 0 frame before the restart"


def test_real_race_entered_from_a_loading_screen():
    """Nordschleife, 2026-10-15: GT7 goes MENU -> LOADING (lap 1) -> IN_RACE at 0
    km/h with no field, then shows the menu for two frames before the race proper.
    LOADING -> IN_RACE is not a start (a pit stop on lap 1 looks the same); the
    start is judged once, on the frame after the menu blip (#157). It is GT7's
    attract-mode demo (#260; the 2026-10-18 demo matches it frame for frame), so
    the check that judges it calls it a demo and no session opens."""
    path = (
        Path(__file__).parent
        / "fixtures"
        / "real-nuc-nordschleife-rolling-start-2026-10-15.jsonl.gz"
    )
    states = list(read_recording(path))
    loading_to_race = [
        cur
        for prev, cur in zip(states, states[1:], strict=False)
        if prev.phase is Phase.LOADING and cur.phase is Phase.IN_RACE
    ]
    assert [s.packet_id for s in loading_to_race] == [473613]
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    judged = []
    start = engine.driver.start

    def spy(s):
        judged.append(s)
        start(s)

    engine.driver.start = spy  # type: ignore[method-assign]
    for s in states:
        engine.process(s)
    assert [(s.packet_id, round(s.speed_kph), s.total_cars) for s in judged] == [(473620, 100, 20)]
    assert engine.races_started == 0


def test_real_pause_and_resume_is_neither_a_start_nor_an_end():
    """The qualifying fixture pauses and resumes three times mid-lap (2026-10-14),
    once after the restart. A pause keeps the race: no start, no end, no restart,
    and the paused lap is one lap."""
    states = list(read_recording(QUALI, strict=True))
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
    spoken = await replay(read_recording(path, strict=True), engine, ConsolePlayer())
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
    """Suzuka East, six laps against one car, recorded 2026-10-15. Heavy
    fuel wear, the pit call after lap 2, and a stop on lap 3: GT7 posts the pit-in
    lap on a loading frame as the car crosses into the pit cut-scene, then refuels
    behind two more loading screens (22.9 to 100)."""
    engine, texts, laps = await _replay_with_store(PIT_STOP, tmp_path)
    assert texts == [
        "Six laps. P one of two.",
        "Down to second.",
        "Up to first.",
        "Box next lap.",  # 2.11 laps of fuel: lap 3 is the in-lap
        "Fuel. two laps remaining.",
        "Lap one. fifty-seven point one.",  # from the grid, short: not a best
        "Pit this lap.",
        "Fuel. one lap remaining.",
        "Lap two. one oh zero point five.",
        # the in-lap, posted on the loading frame; no fuel call on the way into the
        # pits, and no delta for a lap that holds a stop (#244): held to the exit
        "In lap, one twenty-two point five.",
        "Out lap, one oh nine point nine.",
        "Final lap.",
        "Lap five. fifty-nine point five. New best by one point zero.",
        "Lap six. one oh zero point three. zero point eight over best.",
        # no fuel by stint (#245): the results card has it
        "Chequered flag. Finished first. Best lap fifty-nine point five.",
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
    """Circuit Gilles Villeneuve, laps 5 to 8 of twelve, 2026-10-17. The pit call
    comes after lap 5; lap 6 is the in-lap, crossed in the pit lane after a full
    tank, and lap 7 the out-lap, which starts in the pit lane at the limiter and
    used 15.0 against 16.4 for lap 8. Neither is a fuel lap. The fixture starts
    part way through lap 5, as when the engineer starts mid-race, so lap 5 is not
    a fuel lap either (it read 14.34, and called the pit before the stop, #265)."""
    engine, texts, laps = await _replay_with_store(GILLES_STOP, tmp_path, end=True)
    assert texts == [
        "Back with you. Lap five of twelve. P seven.",  # joined part way (#265)
        "Lap five. one thirty-eight point four. zero point nine over best.",
        "Up to sixth.",
        "Up to fifth.",
        # quiet in the pit lane while P5 drops to P11 in the box; lap 6 ends in the
        # lane, so its call waits for the exit (#244)
        "In lap, two oh zero point one.",
        "Down to tenth.",  # the net change, once out of the pits
        "Up to ninth.",
        "Out lap, one forty-two point two.",
        "Up to sixth.",
        "Fuel to the flag, just. Save a little.",  # the last four, on lap 8 alone
        "Lap eight. one thirty-seven point eight. zero point three over best.",
    ]
    assert [lap for lap, _ in laps] == [5, 6, 7, 8, 9]
    assert _pit_column(tmp_path) == [None, "in", "out", None, None]
    fuel = _fuel_rule(engine)
    assert [round(x, 2) for x in fuel.consumption] == [16.35]  # lap 8
    assert fuel.stint == 2
    summary = _summary(tmp_path)
    assert summary["stints"] == 2
    (stop,) = summary["pit_stops"]
    assert (stop["in_lap"], stop["out_lap"], stop["tyres_changed"]) == (6, 7, True)
    assert stop["fuel_added"] == pytest.approx(91.3, abs=0.1)
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT pit_stops FROM sessions").fetchall() == [(1,)]


async def test_real_pit_stop_crossed_in_the_exit_cut(tmp_path):
    """Willow Springs Big Willow, laps 6 to 8 of ten, 2026-10-17. Lap 6 is posted
    on the loading frame that takes the car out of the pits: the crossing out of the
    pits, not into them. The out-lap (13.3) is left out; lap 8 (12.6) is the first
    fuel lap of the new stint."""
    engine, texts, laps = await _replay_with_store(WILLOW_STOP, tmp_path, end=True)
    fuel = [t for t in texts if t.startswith(("Fuel", "Pit", "Lap", "In lap", "Out lap"))]
    assert fuel == [
        "In lap, one thirty-six point six.",
        "Out lap, one twenty-four point two.",
        "Lap eight. one twenty-one point nine. two point zero over best.",
    ]
    assert _pit_column(tmp_path) == ["in", "out", None, None]  # lap 9 is cut short
    assert [round(x, 2) for x in _fuel_rule(engine).consumption] == [12.62]
    (stop,) = _summary(tmp_path)["pit_stops"]
    assert (stop["in_lap"], stop["out_lap"]) == (6, 7)
    assert stop["fuel_after"] == pytest.approx(65.35, abs=0.01)  # a part refuel


async def test_real_fuel_calls_through_two_stops(tmp_path):
    """SUGO, twelve laps, two stops (in at the end of laps 4 and 8), 2026-10-18.
    After the first stop the old floor said "two laps" on 2.99, "Box this lap" a
    lap early on 1.83, then nothing on the real box lap, and nothing in a last
    stint that made the flag by 0.13 of a lap (#247)."""
    _, texts, _ = await _replay_with_store(SUGO_STOPS, tmp_path)
    calls = [t for t in texts if t.startswith(("Fuel", "Pit", "Box", "Lap", "In lap", "Out lap"))]
    assert calls == [
        # stint 1, as before, and "box next lap" with 2.06 laps (in on lap 4)
        "Fuel. three laps remaining.",  # 3.51
        "Lap one. one thirty-four point one.",
        "Box next lap.",
        "Fuel. two laps remaining.",  # 2.06
        "Lap two. one twenty-two point two.",
        "Pit this lap.",
        "Fuel critical. Less than one lap.",  # 0.89
        "Lap three. one twenty-three point seven. one point five over best.",
        "In lap, one thirty point one.",  # due in the lane, held to the exit (#244)
        # stint 2: the out-lap is not measured, stint 1's laps still weigh in
        "Fuel. Just under three laps.",  # 2.99, laps 6, 7 and 8
        "Out lap, one forty-seven point three.",
        "Box next lap.",
        "Fuel. Just under two laps.",  # 1.83
        "Lap six. one twenty-two point nine. zero point seven over best.",
        "Pit this lap.",  # lap 8, the in-lap
        "Fuel. one lap remaining.",  # 1.06
        "Lap seven. one twenty-three point two. one point zero over best.",
        "In lap, one forty-seven point seven.",
        # stint 3: 3.17 laps for three, then quiet to the flag on 3.3 per cent
        "Fuel to the flag, just. Save a little.",
        "Out lap, one forty-seven point five.",
        "Lap ten. one twenty-three point six. one point four over best.",
        "Lap eleven. one twenty-two point eight. zero point six over best.",
        "Lap twelve. one twenty-three point four. one point two over best.",
    ]


async def test_real_race_finished_on_the_last_litre(tmp_path):
    """Suzuka East, six laps from P10 of twenty, 2026-10-15. The driver did not
    stop and finished on the last litre: 3.26 laps of fuel for the last three is
    tight, not a pit call (the old floor said "Pit this lap." after lap 4, #247)."""
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
        "Fuel to the flag, just. Save a little.",
        "Up to third.",
        "Up to second.",
        "Lap four. one oh one point two. New best by one point nine.",
        "Final lap.",
        "Lap five. one oh three point four. two point two over best.",
        "Lap six. one oh four point zero. two point eight over best.",
        "Chequered flag. Finished second. Best lap one oh one point two.",
    ]
    assert [lap for lap, _ in laps] == [1, 2, 3, 4, 5, 6]


async def test_real_race_replay_is_ignored(tmp_path, caplog):
    """SUGO, 2026-10-18: the driver watched the replay of the race just run. GT7
    starts it like a race (track screen, then lap 1) but never flags cars on track
    while it plays, and the fuel drains as it did in the race. The engineer says
    nothing, stores nothing and posts no card, and says why once in the log (#243)."""
    states = list(read_recording(SUGO_REPLAY, strict=True))
    driving = [s for s in states if s.in_race]
    assert not any(s.cars_on_track for s in driving)
    assert driving[0].fuel_level > 98 and driving[-1].fuel_level < 3
    cards: list[dict] = []
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]),
        CalloutQueue(max_age=None),
        SessionStore(tmp_path, on_end=cards.append),
    )
    with caplog.at_level(logging.INFO, logger="those_who_run"):
        spoken = await replay(states, engine, ConsolePlayer())
    assert spoken == []
    assert engine.races_started == 0
    assert cards == []
    assert not list(tmp_path.glob("sessions/*"))
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)
    db.close()
    replays = [r.getMessage() for r in caplog.records if "replay" in r.getMessage()]
    assert replays == [
        "ignoring a replay: GT7's cars-on-track flag is off from the start and fuel is"
        " draining (98.3 -> 97.6), which only a replay does"
    ]


async def _ignored(path, tmp_path, caplog) -> list[str]:
    """Replay ``path`` with a store: assert nothing was said, started, stored or
    posted, and return the log lines about what was ignored."""
    cards: list[dict] = []
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]),
        CalloutQueue(max_age=None),
        SessionStore(tmp_path, on_end=cards.append),
    )
    with caplog.at_level(logging.INFO, logger="those_who_run"):
        spoken = await replay(read_recording(path, strict=True), engine, ConsolePlayer())
    assert spoken == []
    assert engine.races_started == 0
    assert cards == []
    assert not list(tmp_path.glob("sessions/*"))
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)
    db.close()
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("ignoring")]


async def test_real_demo_race_is_ignored(tmp_path, caplog):
    """Laguna Seca, 2026-10-18 11:01: GT7's attract-mode demo, playing on the idle
    PS5 when the engineer started, on lap 2 of 5. The flag is off and the fuel
    stays at 100 throughout. With no menu seen there is no telling whether a track
    was loaded, but GT7 reports 12 cars while its flag says none: no drive does
    that. No callouts, no session, no card, and one log line (#260)."""
    states = list(read_recording(LAGUNA_DEMO, strict=True))
    driving = [s for s in states if s.in_race]
    assert states[0].in_race and states[0].current_lap == 2
    assert not any(s.cars_on_track for s in driving)
    assert {s.fuel_level for s in driving} == {100.0}
    assert await _ignored(LAGUNA_DEMO, tmp_path, caplog) == [
        "ignoring a demo race: GT7's cars-on-track flag is off from the start and it was"
        " joined part way with no menu seen and GT7 reports 12 cars"
    ]


@pytest.mark.parametrize(
    "name",
    [
        "real-nuc-tokyo-east-race-2026-10-15",
        "real-nuc-laguna-seca-race-2026-10-15",
        "real-nuc-nordschleife-rolling-start-2026-10-15",
        "real-nuc-tsukuba-brz-drift-2026-10-15",
    ],
)
async def test_real_2026_10_15_unflagged_group_are_demos(name, tmp_path, caplog):
    """The races GT7 never flagged (#63) start as the demos do: from the menu with
    no loading screen, the flag off, the fuel flat. Laguna Seca and Nordschleife are
    the 2026-10-18 demos in the same cars frame for frame. All four are ignored."""
    assert await _ignored(FIXTURES / f"{name}.jsonl.gz", tmp_path, caplog) == [
        "ignoring a demo race: GT7's cars-on-track flag is off from the start and it came"
        " straight from the menu with no loading screen"
    ]


async def test_real_restart_during_lap_1_ends_the_session_and_starts_a_clean_one(tmp_path):
    """Three two-lap races at SUGO, 2026-10-18 (outing 20261018-130722): the
    driver restarts from the pause menu on lap 2, then on lap 1, then finishes P2.
    Both restarts reset the lap counter through a loading screen at lap 0, with the
    car back on the rolling-start line and the tank refilled, so each ends its
    session (as a quit would) and the next race starts a new one: lap 1 -> lap 1
    never happens (#157 AC1). The lap-1 restart's session has no full lap and gets
    no card; the race after it starts clean: briefed again from P10, its own rolling
    start, no stops, and SUGO confirmed from its own laps."""
    states = list(read_recording(SUGO_RESTARTS, strict=True))
    resets = [
        (prev, cur)
        for prev, cur in zip(states, states[1:], strict=False)
        if prev.current_lap >= 1 and cur.phase is Phase.LOADING and cur.current_lap == 0
    ]
    assert [(p.current_lap, round(p.t - states[0].t)) for p, _ in resets] == [(2, 282), (1, 336)]
    for prev, cur in resets:
        assert round(cur.fuel_level) == 100 > prev.fuel_level
        assert race_ended(prev, cur) and not race_restarted(prev, cur)

    cards: list[dict] = []
    store = SessionStore(tmp_path, on_end=cards.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    tracks = []
    for s in states:
        engine.process(s)
        if store.session is not None and engine.track is not None:
            tracks.append((store.session.session_id, engine.track.confidence))
    store.close()
    assert engine.races_started == 3
    assert [(c["laps_completed"], c["finished"]) for c in cards] == [
        (1, False),
        (0, False),
        (2, True),
    ]
    assert [build_card(c) is None for c in cards] == [False, True, False]
    assert (cards[1]["laps"][0]["lap"], cards[1]["laps"][0]["complete"]) == (1, False)
    last = cards[2]
    assert last["session_kind"]["start"] == "rolling"
    assert last["pit_stops"] == []
    assert last["track"]["name"] == "Sportsland SUGO"
    assert last["track"]["confidence"] == "confirmed"
    assert (last["final_position"], last["total_time_ms"]) == (2, 169772)
    # the lap-1 restart's lap is not carried over: two laps, both its own
    assert [x["lap"] for x in last["laps"]] == [1, 2]
