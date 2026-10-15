from tests.conftest import make_state
from those_who_run.rules import build_rules
from those_who_run.rules.final_lap import FinalLapRule
from those_who_run.rules.fuel import FuelRule
from those_who_run.rules.lap_time import LapTimeRule
from those_who_run.rules.position import PositionRule
from those_who_run.state import Phase, racing_frame


def run_rule(rule, frames):
    out = []
    prev = None
    for s in frames:
        if s.phase is Phase.IN_RACE or racing_frame(prev, s):
            out.extend(rule.evaluate(prev, s))
        prev = s
    return [c.text for c in out]


def test_lap_time_deltas(sim):
    frames = sim(total_laps=3).menu().at_track().race([100000, 99500, 101000]).frames
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. one forty point zero.",
        "Lap two. one thirty-nine point five. zero point five under best.",
        "Lap three. one forty-one point zero. one point five over best.",
    ]


def test_lap_time_templates_are_configurable(sim):
    frames = sim(total_laps=2).race([100000, 100000]).frames
    rule = LapTimeRule({"template": "{time}, {delta}", "delta_equal": "same as best"})
    assert run_rule(rule, frames) == [
        "one forty point zero.",
        "one forty point zero, same as best.",
    ]


def test_fuel_thresholds(sim):
    # 100 units, 10 per lap, 20 laps: estimate is 9 after lap 1, then 8, 7 ...
    frames = sim(total_laps=20, fuel=100, burn=10).race([100000] * 10, finish=False).frames
    assert run_rule(FuelRule(), frames) == [
        "Fuel. nine laps remaining.",  # crosses 10
        "Fuel. five laps remaining.",
        "Fuel. three laps remaining.",
        "Fuel. two laps remaining.",
        "Fuel. one lap remaining.",
        "Fuel critical. Less than one lap.",
    ]


def test_fuel_silent_when_enough_for_the_race(sim):
    frames = sim(total_laps=5, fuel=100, burn=10).race([100000] * 5).frames
    assert run_rule(FuelRule(), frames) == []


def test_fuel_silent_with_fuel_off(sim):
    frames = sim(total_laps=20, fuel=100, burn=0).race([100000] * 5).frames
    assert run_rule(FuelRule(), frames) == []


def test_fuel_refuel_resets_announcements(sim):
    frames = (
        sim(total_laps=30, fuel=40, burn=10)
        .race([100000] * 8, refuel_after_lap=3, refuel_to=40, finish=False)
        .frames
    )
    texts = run_rule(FuelRule(), frames)
    # lap1 -> 3 left (10,5,3 crossed, says three); lap2 -> 2; lap3 refuel -> 4 (nothing new);
    # lap4 -> 3 again because the announced set was cleared on refuel
    assert texts[:2] == ["Fuel. three laps remaining.", "Fuel. two laps remaining."]
    assert "Fuel. three laps remaining." in texts[2:]


def test_fuel_critical_priority_is_configurable(sim):
    frames = sim(total_laps=20, fuel=10, burn=10).race([100000] * 2, finish=False).frames
    rule = FuelRule({"critical_priority": 1})
    out = [
        c
        for s_prev, s in zip([None] + frames, frames, strict=False)
        for c in rule.evaluate(s_prev, s)
    ]
    assert out and out[-1].priority == 1


def test_final_lap_once(sim):
    frames = sim(total_laps=3).race([100000] * 3).frames
    assert run_rule(FinalLapRule(), frames) == ["Final lap."]


def test_final_lap_not_for_timed_races(sim):
    frames = sim(total_laps=0).race([100000] * 3).frames
    assert run_rule(FinalLapRule(), frames) == []


def test_build_rules_respects_enabled():
    rules = build_rules({"fuel": {"enabled": False}, "lap_time": {"priority": 7}})
    names = [r.name for r in rules]
    assert names == ["lap_time", "final_lap", "position"]
    assert rules[0].priority == 7


def test_lap_time_uses_own_best_when_gt7_has_none(sim):
    # GT7 leaves best_lap_ms at -1 after lap 1 of a race. Lap 2 should still get a delta.
    s = sim(total_laps=2)
    s.race([51000, 53100])
    frames = [f for f in s.frames]
    # emulate GT7: best stays -1 until lap 2 completes
    from dataclasses import replace

    frames = [
        replace(f, best_lap_ms=-1) if f.current_lap <= 2 and f.phase.value != "menu" else f
        for f in frames
    ]
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. fifty-one point zero.",
        "Lap two. fifty-three point one. two point one over best.",
    ]


def test_position_ignores_the_grid_settling_then_announces():
    rule = PositionRule({"settle_secs": 2.0, "min_interval_secs": 5.0})
    rule.reset()

    def frame(t, pos):
        return make_state(t=t, current_lap=1, race_start_pos=pos, cars_on_track=True)

    frames = [frame(0.0, 20), frame(0.1, 1), frame(1.0, 1), frame(3.0, 1), frame(4.0, 1)]
    assert run_rule(rule, frames) == [], "P20 -> P1 inside the first two seconds is the grid"
    frames += [frame(5.0, 2), frame(6.0, 2), frame(7.5, 2)]
    assert run_rule(rule, frames[5:]) == ["Down to second."]
