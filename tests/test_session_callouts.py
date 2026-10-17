"""Callouts shaped by the session kind (#64)."""

from pathlib import Path

from tests.conftest import make_state
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.rules import build_rules
from those_who_run.rules.position import PositionRule
from those_who_run.rules.race_summary import RaceSummaryRule
from those_who_run.sessionkind import SessionKind

FIXTURES = Path(__file__).parent / "fixtures"


def kind(name: str, field: bool, laps: int = 0) -> SessionKind:
    return SessionKind(name, laps, field, None, True, "test")  # type: ignore[arg-type]


def engine() -> Engine:
    return Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))


async def spoken(frames) -> list[str]:
    return [c.text for c in await replay(frames, engine(), ConsolePlayer())]


# who is racing


def test_the_session_kind_decides_the_field_once_known():
    rule = PositionRule()
    ghost = make_state(total_laps=0, total_cars=2, cars_on_track=True)
    unflagged = make_state(total_laps=3, total_cars=16, cars_on_track=False)
    assert rule.has_field(ghost) and not rule.has_field(unflagged), "GT7's flag until known"
    rule.on_session(kind("solo_timed", field=False))
    assert not rule.has_field(ghost)
    rule.on_session(kind("lap_race", field=True, laps=3))
    assert rule.has_field(make_state(total_laps=3, total_cars=16))
    unflagged_race = SessionKind("lap_race", 3, True, None, False, "test")
    rule.on_session(unflagged_race)
    assert not rule.has_field(unflagged), "a field GT7 does not flag is not called"
    rule.on_session(kind("unknown", field=False))
    assert rule.has_field(ghost), "an unknown kind falls back to the flag"


async def test_time_trial_ghost_gets_no_position_calls(sim):
    """A time trial can report a second car, the ghost, and P2 behind it."""
    s = sim(total_laps=0, cars=1, position=1)
    s.race([100000], finish=False)
    for _ in range(40):
        s._push(current_lap=2, total_cars=2, race_start_pos=2, best_lap_ms=s.best)
    s.loading(0).at_track()
    texts = await spoken(s.frames)
    assert not any("Up to" in t or "Down to" in t or " P " in f" {t}" for t in texts), texts


async def test_a_race_gt7_does_not_flag_gets_no_grid_slot_or_places(sim):
    """Races in the mode with no cars-on-track flag (Tokyo East, Laguna Seca,
    2026-10-15), probably Arcade or Missions: until we know what they are, no
    position talk (decided 2026-10-16)."""
    s = sim(total_laps=3, cars=16, position=9, is_race=False)
    s.race([], finish=False).drive(20)
    for _ in range(20):
        s._push(current_lap=1, race_start_pos=7, cars_on_track=False)
    texts = await spoken(s.frames)
    assert texts[0] == "Three laps."
    assert not any("Up to" in t or " P " in f" {t}" for t in texts), texts


# leaving a session with no flag


async def test_leaving_a_time_trial_sums_it_up(sim):
    s = sim(total_laps=0, cars=1, position=1)
    s.race([102300, 101900, 103000], finish=False)
    s.loading(0).at_track()
    texts = await spoken(s.frames)
    assert texts[-1] == "Session done. Three laps. Best lap one forty-one point nine."


async def test_retiring_from_a_race_is_quiet_unless_configured(sim):
    s = sim(total_laps=5, cars=16)
    s.race([100000, 99000], finish=False)
    s.loading(0).at_track()
    assert not any(t.startswith("Session done") for t in await spoken(s.frames))

    rule = RaceSummaryRule({"quit_kinds": ["lap_race"]})
    rule.on_session(kind("lap_race", field=True, laps=5))
    last = make_state(current_lap=3, best_lap_ms=99000)
    out = rule.on_end(last, make_state(current_lap=0))
    assert [c.text for c in out] == ["Session done. Two laps. Best lap one thirty-nine point zero."]


def test_quit_summary_needs_a_lap_and_never_follows_the_flag():
    rule = RaceSummaryRule()
    rule.on_session(kind("solo_timed", field=False))
    assert rule.on_end(make_state(current_lap=1), make_state(current_lap=0)) == []
    rule.announced = True  # the flag summary was spoken
    assert rule.on_end(make_state(current_lap=4), make_state(current_lap=0)) == []


# real recordings (2026-10-15)


async def test_real_fuji_time_trial_has_no_fuel_or_position_and_a_summary_on_leaving():
    engine_ = engine()
    out = await replay(
        read_recording(FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl", strict=True),
        engine_,
        ConsolePlayer(),
    )
    rules = {c.rule for c in out}
    assert "fuel" not in rules and "position" not in rules
    assert out[-1].text == "Session done. Two laps. Best lap two oh zero point three."


async def test_real_tokyo_east_race_is_briefed_without_position_or_fuel():
    out = await replay(
        read_recording(FIXTURES / "real-nuc-tokyo-east-race-2026-10-15.jsonl", strict=True),
        engine(),
        ConsolePlayer(),
    )
    brief = next(c.text for c in out if c.rule == "start_brief")
    assert brief == "Tokyo Expressway. East Clockwise. Three laps."
    assert not any(c.rule in ("fuel", "position") for c in out)
