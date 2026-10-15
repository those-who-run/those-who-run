from tests.conftest import make_state
from those_who_run.rules import build_rules
from those_who_run.rules.final_lap import FinalLapRule
from those_who_run.rules.fuel import FuelRule
from those_who_run.rules.lap_time import LapTimeRule
from those_who_run.rules.position import PositionRule
from those_who_run.rules.race_summary import RaceSummaryRule
from those_who_run.rules.start_brief import StartBriefRule
from those_who_run.rules.temps import TempsRule
from those_who_run.state import Phase, racing_frame
from those_who_run.trackdetect import TrackMatch


def run_rule(rule, frames):
    return [c.text for c in run_rule_callouts(rule, frames)]


def run_rule_callouts(rule, frames):
    """Feed frames through one rule with the engine's gating."""
    out = []
    prev = None
    for s in frames:
        if s.phase is Phase.IN_RACE or racing_frame(prev, s):
            out.extend(rule.evaluate(prev, s))
        prev = s
    return out


def _match(track_id, name, confidence):
    return TrackMatch(track_id, name, confidence, (), "test")


def test_lap_time_deltas(sim):
    frames = sim(total_laps=3).menu().at_track().race([100000, 99500, 101000]).frames
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. one forty point zero.",
        "Lap two. one thirty-nine point five. New best by zero point five.",
        "Lap three. one forty-one point zero. one point five over best.",
    ]


def test_lap_time_new_best_has_its_own_template_and_priority(sim):
    frames = sim(total_laps=3).race([100000, 99000, 99000]).frames
    out = run_rule_callouts(LapTimeRule(), frames)
    assert [c.text for c in out] == [
        "Lap one. one forty point zero.",  # the first lap is not a "new best"
        "Lap two. one thirty-nine point zero. New best by one point zero.",
        "Lap three. one thirty-nine point zero. equal to best.",
    ]
    assert [c.priority for c in out] == [20, 11, 20]
    rule = LapTimeRule({"template_new_best": "Best. {time}. {delta}", "new_best_priority": 3})
    out = run_rule_callouts(rule, frames)
    assert out[1].text == "Best. one thirty-nine point zero. one point zero under best."
    assert out[1].priority == 3


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
    assert names == [
        "lap_time",
        "final_lap",
        "position",
        "start_brief",
        "race_summary",
        "temps",
    ]
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


# start brief


def test_start_brief_lap_race(sim):
    frames = sim(total_laps=3, position=10, cars=20).menu().at_track().race([100000] * 3).frames
    assert run_rule(StartBriefRule(), frames) == ["Three laps. P ten of twenty."]


def test_start_brief_timed_race(sim):
    frames = sim(total_laps=0, position=1, cars=20, is_race=True).race([100000] * 2).frames
    assert run_rule(StartBriefRule(), frames) == ["Timed race. P one of twenty."]


def test_start_brief_silent_in_practice(sim):
    # No lap total and no other cars: time trial, practice or a licence test.
    assert run_rule(StartBriefRule(), sim(total_laps=0).race([100000] * 2).frames) == []
    lone = sim(total_laps=0, cars=1, position=1, is_race=True).race([100000] * 2).frames
    assert run_rule(StartBriefRule(), lone) == []


def test_start_brief_single_car_race_has_no_position(sim):
    frames = sim(total_laps=1, cars=1, position=1).race([100000]).frames
    assert run_rule(StartBriefRule(), frames) == ["One lap."]


def test_start_brief_joined_mid_race():
    # The engineer was restarted on lap 5 of 10: say what is left, not the total.
    frames = [
        make_state(t=float(t), current_lap=5, total_laps=10, race_start_pos=3, total_cars=12)
        for t in range(4)
    ]
    assert run_rule(StartBriefRule(), frames) == ["Six laps to go. P three of twelve."]


def test_start_brief_waits_for_the_grid_to_settle():
    rule = StartBriefRule({"settle_secs": 2.0})
    frames = [
        make_state(t=0.0, current_lap=1, race_start_pos=20),
        make_state(t=0.5, current_lap=1, race_start_pos=1),
        make_state(t=1.9, current_lap=1, race_start_pos=1),
    ]
    assert run_rule(rule, frames) == []
    assert run_rule(rule, [make_state(t=2.0, current_lap=1, race_start_pos=1)]) == [
        "Five laps. P one of sixteen."
    ]


def test_start_brief_includes_a_track_known_at_the_start(sim):
    rule = StartBriefRule()
    rule.on_track(_match(348, "Nurburgring 24h", "probable"))
    frames = sim(total_laps=3).race([100000] * 3).frames
    assert run_rule(rule, frames) == [
        "Nurburgring twenty-four hour. Three laps. P five of sixteen."
    ]


def test_start_brief_speaks_a_track_learned_later_once_per_track(sim):
    rule = StartBriefRule()
    s = sim(total_laps=5)
    s.race([100000], finish=False)
    assert run_rule(rule, s.frames) == ["Five laps. P five of sixteen."]

    rule.on_track(_match(16, "Fuji International Speedway", "ambiguous"))
    assert run_rule(rule, s.drive(2).frames[-2:]) == [], "a guess is not worth announcing"
    rule.on_track(_match(348, "Nurburgring 24h", "probable"))
    assert run_rule(rule, s.drive(2).frames[-2:]) == ["Nurburgring twenty-four hour."]
    rule.on_track(_match(348, "Nurburgring 24h", "confirmed"))
    assert run_rule(rule, s.drive(2).frames[-2:]) == [], "same track, only more certain"
    rule.on_track(_match(349, "Nurburgring GP", "confirmed"))
    assert run_rule(rule, s.drive(2).frames[-2:]) == ["Nurburgring G P."], "changed verdict"

    quiet = StartBriefRule({"announce_track": False})
    quiet.on_track(_match(348, "Nurburgring 24h", "confirmed"))
    assert run_rule(quiet, s.frames) == [
        "Nurburgring twenty-four hour. Five laps. P five of sixteen."
    ]
    quiet.on_track(_match(349, "Nurburgring GP", "confirmed"))
    assert run_rule(quiet, s.drive(2).frames[-2:]) == []


def test_start_brief_once_per_race_and_again_after_reset(sim):
    rule = StartBriefRule()
    frames = sim(total_laps=2).race([100000] * 2).frames
    assert run_rule(rule, frames) == ["Two laps. P five of sixteen."]
    assert run_rule(rule, frames) == []
    rule.reset()
    assert run_rule(rule, frames) == ["Two laps. P five of sixteen."]


# race summary


def test_race_summary_at_the_flag(sim):
    frames = sim(total_laps=3, fuel=100, burn=5, position=6).race([100000, 99000, 99500]).frames
    assert run_rule(RaceSummaryRule(), frames) == [
        "Chequered flag. Finished sixth. Best lap one thirty-nine point zero. "
        "Fuel used fifteen percent."
    ]


def test_race_summary_counts_fuel_from_both_stints(sim):
    frames = (
        sim(total_laps=4, fuel=50, burn=10)
        .race([100000] * 4, refuel_after_lap=2, refuel_to=50)
        .frames
    )
    (text,) = run_rule(RaceSummaryRule(), frames)
    # 50 -> 30 before the stop, 50 -> 30 after; the sim refuels on the lap-2 crossing
    # frame, which hides that frame's 5 units, so 35 of the 40 burnt are visible.
    assert text.endswith("Fuel used thirty-five percent.")


def test_race_summary_without_position_or_fuel(sim):
    # time trial: no cars on track, fuel consumption off
    frames = sim(total_laps=2, burn=0, is_race=False).race([100000, 101000]).frames
    assert run_rule(RaceSummaryRule(), frames) == ["Chequered flag. Best lap one forty point zero."]
    # a one-car race is not a finishing position either
    frames = sim(total_laps=1, cars=1, position=1, burn=0).race([100000]).frames
    assert run_rule(RaceSummaryRule(), frames) == ["Chequered flag. Best lap one forty point zero."]


def test_race_summary_uses_its_own_best_not_gt7s(sim):
    from dataclasses import replace

    s = sim(total_laps=2)
    s.race([51000, 53100])
    # GT7's best ignores lap 1, so at the flag it says 53.1; ours says 51.0.
    frames = [
        replace(f, best_lap_ms=53100 if f.current_lap > 2 else -1) if f.phase.value != "menu" else f
        for f in s.frames
    ]
    (text,) = run_rule(RaceSummaryRule(), frames)
    assert "Best lap fifty-one point zero." in text


def test_race_summary_silent_on_quit(sim):
    s = sim(total_laps=5)
    s.race([100000], finish=False)
    s.paused().loading().at_track().menu()
    assert run_rule(RaceSummaryRule(), s.frames) == []


def test_race_summary_templates_are_configurable(sim):
    rule = RaceSummaryRule({"template": "{position} {fuel}", "template_position": "P {p}."})
    frames = sim(total_laps=2, fuel=100, burn=10, position=3).race([100000] * 2).frames
    assert run_rule(rule, frames) == ["P 3. Fuel used twenty percent."]


# temperatures

HOT_FL = (125.0, 90.0, 90.0, 90.0)
WARM = (90.0, 90.0, 90.0, 90.0)


def _stint(sim, laps=1):
    s = sim(total_laps=10, tyres=WARM)
    s.race([100000] * laps, finish=False)
    return s


def test_temps_hot_corner_after_sustain(sim):
    s = _stint(sim)
    assert run_rule(TempsRule(), s.drive(5, tire_temp=HOT_FL).frames) == []
    assert run_rule(TempsRule(), s.drive(1, tire_temp=HOT_FL).frames) == ["Front left tyre hot."]


def test_temps_spike_is_ignored(sim):
    s = _stint(sim)
    s.drive(3, tire_temp=HOT_FL).drive(3, tire_temp=WARM).drive(3, tire_temp=HOT_FL)
    assert run_rule(TempsRule(), s.frames) == []


def test_temps_corners_are_joined_into_one_phrase(sim):
    s = _stint(sim).drive(6, tire_temp=(125.0, 90.0, 125.0, 90.0))
    assert run_rule(TempsRule(), s.frames) == ["Front left and rear left tyres hot."]
    s = _stint(sim).drive(6, tire_temp=(125.0, 125.0, 125.0, 125.0))
    assert run_rule(TempsRule(), s.frames) == ["All tyres hot."]
    s = _stint(sim).drive(6, tire_temp=(125.0, 125.0, 125.0, 90.0))
    assert run_rule(TempsRule(), s.frames) == ["Front left, front right and rear left tyres hot."]


def test_temps_once_while_hot_then_again_after_cooling_and_cooldown(sim):
    rule = TempsRule()
    s = _stint(sim).drive(130, tire_temp=HOT_FL)
    assert run_rule(rule, s.frames) == ["Front left tyre hot."], "no nagging while it stays hot"
    # back under threshold but not under threshold - hysteresis: still armed off
    assert run_rule(rule, s.drive(3, tire_temp=(115.0, 90.0, 90.0, 90.0)).frames[-3:]) == []
    assert run_rule(rule, s.drive(6, tire_temp=HOT_FL).frames[-6:]) == []
    # cooled properly: re-armed, and the cooldown has long passed
    s.drive(2, tire_temp=WARM)
    assert run_rule(rule, s.drive(6, tire_temp=HOT_FL).frames[-8:]) == ["Front left tyre hot."]


def test_temps_cooldown_blocks_a_quick_second_warning(sim):
    rule = TempsRule({"cooldown_secs": 60})
    s = _stint(sim).drive(6, tire_temp=HOT_FL)
    assert run_rule(rule, s.frames) == ["Front left tyre hot."]
    s.drive(2, tire_temp=WARM)
    assert run_rule(rule, s.drive(6, tire_temp=HOT_FL).frames[-8:]) == [], "re-armed, in cooldown"


def test_temps_pause_restarts_the_sustain_window(sim):
    rule = TempsRule()
    s = _stint(sim).drive(3, tire_temp=HOT_FL)
    for _ in range(6):
        s.paused()
    assert run_rule(rule, s.drive(5, tire_temp=HOT_FL).frames) == []
    assert run_rule(rule, s.drive(1, tire_temp=HOT_FL).frames[-1:]) == ["Front left tyre hot."]


def test_temps_cold_tyres_once_at_the_start(sim):
    frames = sim(total_laps=3, tyres=(21.0, 21.0, 21.0, 21.0)).race([100000] * 2).frames
    assert run_rule(TempsRule(), frames) == ["Tyres cold."]
    frames = sim(total_laps=3, tyres=(60.0, 60.0, 60.0, 60.0)).race([100000] * 2).frames
    assert run_rule(TempsRule(), frames) == [], "a fresh load reads a flat 60 to 70"


def test_temps_water_and_oil(sim):
    s = _stint(sim).drive(6, water_temp=115.0, oil_temp=135.0)
    assert run_rule(TempsRule(), s.frames) == [
        "Water temperature high.",
        "Oil temperature high.",
    ]


def test_temps_thresholds_can_be_disabled(sim):
    rule = TempsRule({"tyre_hot_c": None, "water_hot_c": 0, "tyre_cold_c": None})
    s = sim(total_laps=10, tyres=(21.0, 21.0, 21.0, 21.0))
    s.race([100000], finish=False).drive(6, tire_temp=HOT_FL, water_temp=150.0)
    assert run_rule(rule, s.frames) == []
