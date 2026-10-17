from pathlib import Path

import pytest

from tests.conftest import make_state
from those_who_run.pitstop import PitStatus, PitStop
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
    frames = sim(total_laps=4).menu().at_track().race([104000, 100000, 99500, 101000]).frames
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. one forty-four point zero.",
        "Lap two. one forty point zero.",  # only lap 1, the start, to compare with
        "Lap three. one thirty-nine point five. New best by zero point five.",
        "Lap four. one forty-one point zero. one point five over best.",
    ]


def test_lap_time_lap_2_of_a_race_is_not_measured_against_the_start(sim):
    """SUGO, 2026-10-15: a rolling start at 80 km/h made lap 1 a 1:53 and lap 2
    "new best by eleven point nine". In a timed session lap 1 is a real lap."""
    race = sim(total_laps=5).race([113117, 101201, 106407], finish=False).frames
    assert run_rule(LapTimeRule(), race)[:3] == [
        "Lap one. one fifty-three point one.",
        "Lap two. one forty-one point two.",
        "Lap three. one forty-six point four. five point two over best.",
    ]
    timed = sim(total_laps=0).race([113117, 101201], finish=False).frames
    assert run_rule(LapTimeRule(), timed)[1] == (
        "Lap two. one forty-one point two. New best by eleven point nine."
    )


def test_lap_time_new_best_has_its_own_template_and_priority(sim):
    frames = sim(total_laps=4).race([100000, 100000, 99000, 99000]).frames
    out = run_rule_callouts(LapTimeRule(), frames)
    assert [c.text for c in out] == [
        "Lap one. one forty point zero.",  # the first lap is not a "new best"
        "Lap two. one forty point zero.",
        "Lap three. one thirty-nine point zero. New best by one point zero.",
        "Lap four. one thirty-nine point zero. equal to best.",
    ]
    assert [c.priority for c in out] == [20, 20, 11, 20]
    rule = LapTimeRule({"template_new_best": "Best. {time}. {delta}", "new_best_priority": 3})
    out = run_rule_callouts(rule, frames)
    assert out[2].text == "Best. one thirty-nine point zero. one point zero under best."
    assert out[2].priority == 3


def test_lap_time_templates_are_configurable(sim):
    frames = sim(total_laps=3).race([100000, 100000, 100000]).frames
    rule = LapTimeRule({"template": "{time}, {delta}", "delta_equal": "same as best"})
    assert run_rule(rule, frames) == [
        "one forty point zero.",
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
        "Pit this lap.",  # the instruction comes first, then the number
        "Fuel. one lap remaining.",
        "Fuel critical. Less than one lap.",
    ]


def test_fuel_pit_call_once_per_stint_and_again_after_a_stop(sim):
    frames = (
        sim(total_laps=30, fuel=30, burn=10)
        .race([100000] * 5, refuel_after_lap=3, refuel_to=30, finish=False)
        .frames
    )
    texts = run_rule(FuelRule(), frames)
    # lap 1: 2.0 laps left is not under 2; lap 2: 1.0 -> pit; the stop on lap 3
    # re-arms it; lap 4: 2.0; lap 5: 1.0 -> pit again
    assert texts.count("Pit this lap.") == 2
    assert texts.index("Pit this lap.") < texts.index("Fuel. one lap remaining.")


def test_fuel_pit_call_in_a_timed_race(sim):
    frames = sim(total_laps=0, fuel=20, burn=10).race([100000] * 2, finish=False).frames
    assert run_rule(FuelRule(), frames)[0] == "Pit this lap."


def test_fuel_pit_call_can_be_disabled_or_moved(sim):
    frames = sim(total_laps=20, fuel=100, burn=10).race([100000] * 10, finish=False).frames
    assert "Pit this lap." not in run_rule(FuelRule({"pit_window": False}), frames)
    out = run_rule_callouts(FuelRule({"pit_laps": 3, "pit_priority": 2}), frames)
    pit = next(c for c in out if c.text == "Pit this lap.")
    assert pit.priority == 2
    assert out.index(pit) == out.index(next(c for c in out if "two laps" in c.text)) - 1


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


def _gt7_best(frames, counts_lap_one):
    """Emulate GT7's best_lap_ms: -1 until a counted lap is done; lap 1 of a
    lap-count race never counts (the grid is ahead of the line)."""
    from dataclasses import replace

    out, best = [], -1
    for f in frames:
        if f.phase.value != "menu" and f.last_lap_ms > 0:
            completed = f.current_lap - 1
            if (counts_lap_one or completed > 1) and (best <= 0 or f.last_lap_ms < best):
                best = f.last_lap_ms
        out.append(replace(f, best_lap_ms=best) if f.phase.value != "menu" else f)
    return out


def test_lap_time_ignores_the_short_first_lap_of_a_lap_race(sim):
    # Suzuka East 2026-10-15: lap 1 57.1 s from the grid, then 60 s laps.
    frames = _gt7_best(sim(total_laps=4).race([57100, 60500, 60900, 59500]).frames, False)
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. fifty-seven point one.",
        "Lap two. one oh zero point five.",
        "Lap three. one oh zero point nine. zero point four over best.",
        "Lap four. fifty-nine point five. New best by one point zero.",
    ]


def test_lap_time_counts_lap_one_without_a_lap_total(sim):
    # A timed race or time trial: GT7 counts lap 1 (SUGO 2026-10-15), and so do we
    # while GT7's best is still empty.
    frames = _gt7_best(sim(total_laps=0).race([100300, 101300]).frames, True)
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. one forty point three.",
        "Lap two. one forty-one point three. one point zero over best.",
    ]
    from dataclasses import replace

    # GT7 posting lap 1 and keeping its best blank leaves it out (a start from a grid
    # ahead of the line, Suzuka East timed race 2026-10-16): no reference for lap 2.
    no_gt7 = [replace(f, best_lap_ms=-1) for f in frames]
    assert run_rule(LapTimeRule(), no_gt7)[1] == "Lap two. one forty-one point three."


def test_lap_time_within_a_twentieth_is_equal_not_a_new_best(sim):
    frames = sim(total_laps=0).race([93892, 93896, 93885]).frames
    assert run_rule(LapTimeRule(), frames) == [
        "Lap one. one thirty-three point nine.",
        "Lap two. one thirty-three point nine. equal to best.",
        "Lap three. one thirty-three point nine. equal to best.",
    ]
    strict = LapTimeRule({"equal_ms": 0})
    assert run_rule(strict, frames)[2].endswith("New best by zero point zero.")


def test_position_ignores_the_grid_settling_then_announces():
    rule = PositionRule({"settle_secs": 2.0, "min_interval_secs": 5.0, "start_grace_secs": 0})
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
    s.race([], finish=False).drive(2)
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


def test_start_brief_names_the_circuit_when_only_its_layouts_are_left(sim):
    """Fuji and Fuji Short share a line and a box in the table: say Fuji."""
    rule = StartBriefRule()
    rule.on_track(
        TrackMatch(
            837,
            "Fuji International Speedway (Short)",
            "ambiguous",
            (),
            "test",
            "Fuji International Speedway",
        )
    )
    frames = sim(total_laps=3).race([100000] * 3).frames
    assert run_rule(rule, frames) == ["Fuji International Speedway. Three laps. P five of sixteen."]


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


def test_race_summary_best_lap_is_gt7s(sim):
    # The short grid lap (51.0) is not a best lap; GT7 says 53.1 at the flag.
    frames = _gt7_best(sim(total_laps=2).race([51000, 53100]).frames, False)
    (text,) = run_rule(RaceSummaryRule(), frames)
    assert "Best lap fifty-three point one." in text


def test_race_summary_best_lap_without_gt7s(sim):
    from dataclasses import replace

    frames = sim(total_laps=3).race([51000, 53100, 52800]).frames
    no_gt7 = [replace(f, best_lap_ms=-1) for f in frames]
    (text,) = run_rule(RaceSummaryRule(), no_gt7)
    assert "Best lap fifty-two point eight." in text, "lap 1 of a lap race does not count"


def test_race_summary_silent_on_quit(sim):
    s = sim(total_laps=5)
    s.race([100000], finish=False)
    s.paused().loading().at_track().menu()
    assert run_rule(RaceSummaryRule(), s.frames) == []


def test_race_summary_templates_are_configurable(sim):
    rule = RaceSummaryRule({"template": "{position} {fuel}", "template_position": "P {p}."})
    frames = sim(total_laps=2, fuel=100, burn=10, position=3).race([100000] * 2).frames
    assert run_rule(rule, frames) == ["P three. Fuel used twenty percent."]


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


def test_temps_a_corner_already_hot_joins_the_one_that_fires(sim):
    """While drifting the rears crossed the threshold a few frames apart and were
    reported 0.3 s apart (2026-10-15). Both rears are one phrase."""
    s = _stint(sim).drive(1, tire_temp=(90.0, 90.0, 125.0, 90.0))
    s.drive(6, tire_temp=(90.0, 90.0, 125.0, 125.0))
    assert run_rule(TempsRule(), s.frames) == ["Rear tyres hot."]
    s = _stint(sim).drive(6, tire_temp=(125.0, 125.0, 90.0, 90.0))
    assert run_rule(TempsRule(), s.frames) == ["Front tyres hot."]


def test_real_drift_rears_are_one_warning_each_time():
    """BRZ Drift Car at Tsukuba (2026-10-15): rears at 177-188 °C while drifting."""
    from those_who_run.replay import read_recording

    frames = read_recording(
        Path(__file__).parent / "fixtures" / "real-nuc-tsukuba-brz-drift-2026-10-15.jsonl"
    )
    assert run_rule(TempsRule(), frames) == ["Rear tyres hot."] * 3


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


def test_start_brief_does_not_name_the_track_after_the_first_lap(sim):
    # Suzuka East is only certain at the line; a lap in, the driver knows.
    rule = StartBriefRule()
    s = sim(total_laps=5)
    s.race([60000], finish=False)
    assert run_rule(rule, s.frames) == ["Five laps. P five of sixteen."]
    rule.on_track(_match(442, "Suzuka Circuit East Course", "confirmed"))
    assert run_rule(rule, s.drive(2).frames[-2:]) == []

    anytime = StartBriefRule({"late_track_first_lap_only": False})
    run_rule(anytime, s.frames[:-2])
    anytime.on_track(_match(442, "Suzuka Circuit East Course", "confirmed"))
    assert run_rule(anytime, s.drive(2).frames[-2:]) == ["Suzuka Circuit East Course."]


def test_position_quiet_through_the_start_then_compares_with_the_grid():
    rule = PositionRule({"settle_secs": 2.0, "min_interval_secs": 5.0, "start_grace_secs": 15})

    def frame(t, pos):
        return make_state(t=t, current_lap=1, race_start_pos=pos, cars_on_track=True)

    shuffle = [frame(0.0, 10), frame(3.0, 11), frame(6.0, 12), frame(9.0, 13), frame(12.0, 12)]
    assert run_rule(rule, shuffle) == [], "the field sorts itself out after the lights"
    after = [frame(15.0, 12), frame(16.0, 12), frame(17.5, 12)]
    assert run_rule(rule, after) == ["Down to twelfth."], "ten on the grid, twelfth now"


def test_position_defaults_are_calmer_than_a_call_per_swap():
    rule = PositionRule()
    assert (rule.settle_secs, rule.min_interval, rule.grace) == (3.0, 10.0, 15.0)


def test_fuel_says_nothing_on_the_crossing_into_the_pits():
    # GT7 crosses the line inside the pit cut-scene (a loading screen), before
    # the refuel. The engine bridges it and tells the rule what it bridged.
    rule = FuelRule()

    def frame(t, lap, fuel):
        return make_state(t=t, current_lap=lap, total_laps=6, fuel_level=fuel)

    frames = [frame(0, 1, 96.7), frame(1, 2, 65.6), frame(2, 3, 37.9)]
    run_rule(rule, frames)
    rule.on_bridge(Phase.LOADING)
    assert rule.evaluate(frames[-1], frame(3, 4, 22.9)) == []

    ignored = FuelRule()  # the same crossing on track (race 1: the call was ignored)
    run_rule(ignored, frames)
    ignored.on_bridge(Phase.PAUSED)
    assert [c.text for c in ignored.evaluate(frames[-1], frame(3, 4, 22.9))] == [
        "Fuel critical. Less than one lap."
    ]


def _stop(in_lap, out_lap, fuel_after=50.0):
    return PitStop(1, in_lap, out_lap, 0.0, None, 0.0, 10.0, fuel_after, False, 60.0, 1, 1, "test")


def test_fuel_in_lap_and_out_lap_are_not_measured():
    rule = FuelRule({"rolling_laps": 5})

    def frame(t, lap, fuel):
        return make_state(t=t, current_lap=lap, total_laps=20, fuel_level=fuel)

    # lap 3 is the in-lap and lap 4 the out-lap, without a refuel (tyres only)
    frames = [frame(i, lap, 100.0 - 10 * (lap - 1)) for i, lap in enumerate(range(1, 7))]
    rule.evaluate(None, frames[0])
    for prev, s in zip(frames, frames[1:], strict=False):
        if s.current_lap == 3:
            rule.on_pit(PitStatus(True, (_stop(3, None),)))
        if s.current_lap == 5:
            rule.on_pit(PitStatus(False, (_stop(3, 4),)))
        rule.evaluate(prev, s)
    assert list(rule.consumption) == [10.0, 10.0, 10.0]  # laps 1, 2 and 5


def test_fuel_a_stop_starts_a_new_stint_even_without_fuel():
    """A tyres-only stop: the level does not rise, but the pit call and the thresholds
    are armed again for the new stint, and the estimate is redone at once."""
    rule = FuelRule()

    def frame(t, lap, fuel):
        return make_state(t=t, current_lap=lap, total_laps=20, fuel_level=fuel)

    frames = [frame(0, 1, 30.0), frame(1, 2, 20.0), frame(2, 3, 10.0)]
    assert "Pit this lap." in run_rule(rule, frames)
    rule.on_pit(PitStatus(True, (_stop(3, None, fuel_after=10.0),)))
    rule.on_pit(PitStatus(False, (_stop(3, 4, fuel_after=10.0),)))
    assert rule.stint == 2 and not rule.pit_announced and not rule.announced
    assert rule.laps_remaining == pytest.approx(1.0)
    texts = [c.text for c in rule.evaluate(frame(3, 4, 8.0), frame(4, 5, 0.5))]
    assert texts == ["Pit this lap.", "Fuel critical. Less than one lap."]


def test_fuel_says_nothing_on_a_crossing_in_the_pit_lane():
    """Circuit Gilles Villeneuve crosses the line in the pit lane, at the limiter,
    with no loading screen around it."""
    rule = FuelRule()

    def frame(t, lap, fuel):
        return make_state(t=t, current_lap=lap, total_laps=12, fuel_level=fuel)

    frames = [frame(0, 1, 50.0), frame(1, 2, 35.0), frame(2, 3, 20.0)]
    run_rule(rule, frames)
    rule.on_pit(PitStatus(True, (_stop(3, None),)))
    assert rule.evaluate(frames[-1], frame(3, 4, 5.0)) == []


# situational pools from the script


def test_lap_time_pools_for_small_and_large_deltas_and_a_small_new_best(sim):
    rule = LapTimeRule(
        {
            "delta_slower_small": ["{delta} off, close."],
            "delta_slower_large": ["{delta} off, regroup."],
            "template_new_best_small": ["By a hair. {time}. Up {gap}."],
        }
    )
    frames = sim(total_laps=0).race([60000, 60200, 63000, 60800, 59900]).frames
    assert run_rule(rule, frames) == [
        "Lap one. one oh zero point zero.",
        "Lap two. one oh zero point two. zero point two off, close.",
        "Lap three. one oh three point zero. three point zero off, regroup.",
        "Lap four. one oh zero point eight. zero point eight over best.",
        "By a hair. fifty-nine point nine. Up zero point one.",
    ]


def test_position_pools_for_the_lead_and_the_podium():
    rule = PositionRule(
        {
            "start_grace_secs": 0,
            "settle_secs": 1.0,
            "min_interval_secs": 0,
            "template_gained_lead": ["Into the lead."],
            "template_gained_podium": ["Podium. P {p}."],
            "template_lost_lead": ["Lost the lead. Down to {position}."],
        }
    )

    def frame(t, pos):
        return make_state(t=t, current_lap=1, race_start_pos=pos, cars_on_track=True)

    frames = [frame(0, 5), frame(2, 5)]
    for t, pos in [(3, 4), (5, 3), (7, 1), (9, 2), (11, 4)]:
        frames += [frame(t, pos), frame(t + 1.5, pos)]
    assert run_rule(rule, frames) == [
        "Up to fourth.",
        "Podium. P three.",
        "Into the lead.",
        "Lost the lead. Down to second.",
        "Down to fourth.",
    ]


def test_race_summary_pools_for_a_win_and_a_podium_and_fuel_left(sim):
    cfg = {
        "template_position_win": ["Winner."],
        "template_position_podium": ["Podium, {position}."],
        "template_fuel": ["{fuel_left} left."],
    }
    win = sim(total_laps=2, fuel=100, burn=10, position=1).race([100000] * 2).frames
    assert run_rule(RaceSummaryRule(cfg), win)[0].startswith("Chequered flag. Winner.")
    third = sim(total_laps=2, fuel=100, burn=10, position=3).race([100000] * 2).frames
    assert run_rule(RaceSummaryRule(cfg), third) == [
        "Chequered flag. Podium, third. Best lap one forty point zero. eighty percent left."
    ]


def test_fuel_reassures_on_the_final_lap_only_after_a_warning(sim):
    cfg = {"template_last_lap_enough": ["Fuel is fine to the end."], "pit_window": False}

    def frame(t, lap, fuel):
        return make_state(t=t, current_lap=lap, total_laps=4, fuel_level=fuel)

    # A heavy first lap worries the estimate; lifting and coasting brings it back.
    worried = [frame(0, 1, 100), frame(1, 2, 70), frame(2, 3, 55), frame(3, 4, 45)]
    assert run_rule(FuelRule(cfg), worried) == [
        "Fuel. two laps remaining.",
        "Fuel is fine to the end.",
    ]
    assert run_rule(FuelRule(), worried) == ["Fuel. two laps remaining."], "no built-in phrase"
    relaxed = sim(total_laps=4, fuel=100, burn=10).race([100000] * 3, finish=False).frames
    assert run_rule(FuelRule(cfg), relaxed) == []


def test_start_brief_position_can_be_an_ordinal(sim):
    rule = StartBriefRule({"template_position": "Starting {position} from {total}."})
    frames = sim(total_laps=2, position=10, cars=20).race([100000] * 2).frames
    assert run_rule(rule, frames) == ["Two laps. Starting tenth from twenty."]


def test_variants_rotate_without_repeating(sim):
    import random

    rule = FinalLapRule({"template": ["Final lap.", "Last lap now.", "One lap to go."]})
    rule.phrases.rng = random.Random(3)
    said = []
    for _ in range(12):
        rule.reset()
        said += run_rule(rule, sim(total_laps=2).race([100000] * 2).frames)
    assert set(said) == {"Final lap.", "Last lap now.", "One lap to go."}
    assert all(a != b for a, b in zip(said, said[1:], strict=False))


def test_fuel_is_not_measured_across_a_telemetry_gap():
    """A lap crossed while the PS5 was offline reads heavy, and the lap after it
    light (gap simulation on the Suzuka race, 2026-10-16): neither is measured."""
    rule = FuelRule()

    def lap(t, lap_no, fuel):
        return make_state(t=t, current_lap=lap_no, total_laps=10, fuel_level=fuel)

    frames = [
        lap(0, 1, 100.0),
        lap(99.9, 1, 90.1),
        lap(100.0, 2, 90.0),  # 10 a lap
        lap(190.0, 2, 81.0),
        lap(200.0, 3, 79.0),  # crossed inside a 10 s hole: reads 11
        lap(299.9, 3, 70.1),
        lap(300.0, 4, 70.0),  # started inside the hole: reads 9
        lap(399.9, 4, 60.1),
        lap(400.0, 5, 60.0),
    ]
    prev = None
    for f in frames:
        rule.evaluate(prev, f)
        prev = f
    assert list(rule.consumption) == pytest.approx([10.0, 10.0])


def test_fuel_is_measured_across_a_pause():
    rule = FuelRule()
    a = make_state(t=0, current_lap=1, total_laps=10, fuel_level=100.0)
    rule.evaluate(None, a)
    b = make_state(t=50, current_lap=1, total_laps=10, fuel_level=95.0)
    rule.evaluate(a, b)
    rule.on_bridge(Phase.PAUSED)  # the engine compares across the pause
    c = make_state(t=200, current_lap=2, total_laps=10, fuel_level=90.0)
    rule.evaluate(b, c)
    assert list(rule.consumption) == pytest.approx([10.0])
