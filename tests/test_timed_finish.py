"""The end of a timed race, which GT7 never flags (2026-10-16)."""

from pathlib import Path

from tests.conftest import make_state
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import Phase, race_started
from those_who_run.store import SessionStore

FIXTURE = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-timed-race-2026-10-16.jsonl.gz"


async def test_real_timed_race_finishes_at_the_line(tmp_path):
    """Five minutes at Suzuka East with nineteen AI cars: five laps, P1. After the
    first crossing past the clock GT7 drove the car (hands off, coasting), showed
    the results, then replayed the race's last frames from the track screen."""
    summaries: list[dict] = []
    store = SessionStore(tmp_path, on_end=summaries.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    spoken = [
        c.text for c in await replay(read_recording(FIXTURE, strict=True), engine, ConsolePlayer())
    ]
    store.close()
    laps = [t for t in spoken if t.startswith("Lap ")]
    assert laps == [
        "Lap one. one oh two point zero.",
        # GT7 left lap 1 (from a grid ahead of the line) out of its best: no delta
        "Lap two. one oh seven point six.",
        "Lap three. one oh seven point six. equal to best.",
        "Lap four. one oh seven point seven. zero point one over best.",
        "Lap five. one oh eight point two. zero point six over best.",
    ]
    assert spoken[-1] == "Chequered flag. Finished first. Best lap one oh seven point six."
    assert engine.races_started == 1, "the replayed frames after the results are not a race"
    (summary,) = summaries
    assert summary["finished"] is True and summary["total_time_ms"] == 333162
    card = build_card(summary)
    assert card is not None
    assert card.title == "Suzuka Circuit East Course · timed race"
    assert card.description == "🚩 Finished P1 of 20 in 5:33.162"
    assert dict(card.fields)["Best lap"] == "1:07.585 (lap 2)"


def _timed(tmp_path, cars, after):
    """A timed race (``cars`` > 1) or time trial: two laps, then ``after`` frames
    of (throttle, brake) past the line."""
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    common = dict(total_laps=0, total_cars=cars, cars_on_track=True,
                  race_start_pos=1 if cars == 1 else 5)  # fmt: skip
    t = 0.0
    frames = []
    for lap, (last, best) in enumerate([(-1, -1), (60000, -1), (61000, 61000)], start=1):
        for _ in range(30 if lap < 3 else 1):
            t += 1
            frames.append(make_state(t=t, current_lap=lap, last_lap_ms=last,
                                     best_lap_ms=best, throttle=200, **common))  # fmt: skip
    for throttle, brake in after:
        t += 1
        frames.append(make_state(t=t, current_lap=3, last_lap_ms=61000, best_lap_ms=61000,
                                 throttle=throttle, brake=brake, **common))  # fmt: skip
    said = [c.text for f in frames for c in engine.process(f)]
    return engine, said


def test_hands_off_after_the_line_ends_a_timed_race(tmp_path):
    engine, said = _timed(tmp_path, 20, [(0, 0)] * 5)
    assert engine.finished and any(t.startswith("Chequered flag") for t in said)


def test_driving_on_or_a_short_lift_is_not_the_end(tmp_path):
    engine, _ = _timed(tmp_path, 20, [(0, 0), (0, 0), (200, 0)] + [(0, 0)] * 5)
    assert not engine.finished, "the driver kept going: just another lap"
    engine, _ = _timed(tmp_path, 20, [(0, 0)] * 2)
    assert not engine.finished


def test_a_time_trial_never_finishes_this_way(tmp_path):
    engine, said = _timed(tmp_path, 1, [(0, 0)] * 10)
    assert not engine.finished and not any(t.startswith("Chequered flag") for t in said)


def test_replayed_frames_after_the_results_are_not_a_start():
    track = make_state(phase=Phase.AT_TRACK, current_lap=0, total_laps=0)
    assert not race_started(track, make_state(current_lap=6, total_laps=0))
    assert race_started(track, make_state(current_lap=1, total_laps=0))
