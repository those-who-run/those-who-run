import json
import sqlite3

from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.metrics import Metrics
from those_who_run.replay import read_recording, replay, write_recording
from those_who_run.rules import build_rules
from those_who_run.store import SessionStore


def make_engine(tmp_path, max_age=None):
    rules = build_rules(DEFAULT_RULES["rules"])
    queue = CalloutQueue(max_age=max_age)
    return Engine(rules, queue, SessionStore(tmp_path), Metrics()), queue


async def test_full_race_callouts_and_records(tmp_path, sim):
    frames = (
        sim(total_laps=3, fuel=100, burn=5).menu().at_track().race([100000, 99000, 99500]).frames
    )
    engine, queue = make_engine(tmp_path)
    player = ConsolePlayer()
    spoken = await replay(frames, engine, player)
    texts = [c.text for c in spoken]
    assert texts == [
        "Three laps. P five of sixteen.",
        "Lap one. one forty point zero.",
        "Final lap.",  # final lap outranks the lap time posted on the same crossing
        "Lap two. one thirty-nine point zero.",  # lap 1 is the start: no delta
        "Lap three. one thirty-nine point five. zero point five over best.",
        "Chequered flag. Finished fifth. Best lap one thirty-nine point zero.",
    ]
    assert engine.races_started == 1

    sessions = list((tmp_path / "sessions").iterdir())
    assert len(sessions) == 1
    laps = sorted(p.name for p in sessions[0].glob("lap-*.parquet"))
    assert laps == ["lap-01.parquet", "lap-02.parquet", "lap-03.parquet"]
    summary = json.loads((sessions[0] / "summary.json").read_text())
    assert summary["laps_completed"] == 3
    assert summary["best_lap_ms"] == 99000
    assert summary["fuel_used"] == 15.0
    lap2 = summary["laps"][1]
    assert lap2["lap"] == 2 and lap2["lap_time_ms"] == 99000 and lap2["fuel_used"] == 5.0


async def test_pause_does_not_restart_race(tmp_path, sim):
    frames = sim(total_laps=3).race([100000] * 3, pause_in_lap=2).frames
    engine, _ = make_engine(tmp_path)
    await replay(frames, engine, ConsolePlayer())
    assert engine.races_started == 1
    assert len(list((tmp_path / "sessions").iterdir())) == 1


async def test_second_race_resets_rules(tmp_path, sim):
    s = sim(total_laps=2)
    s.race([100000, 100000])
    s.at_track()
    s.race([100000, 100000])
    engine, _ = make_engine(tmp_path)
    spoken = await replay(s.frames, engine, ConsolePlayer())
    assert [c.text for c in spoken].count("Final lap.") == 2
    assert engine.races_started == 2
    assert len(list((tmp_path / "sessions").iterdir())) == 2


async def test_restart_closes_session_and_starts_another(tmp_path, sim):
    s = sim(total_laps=3)
    s.race([100000], finish=False)  # one lap done, restart during lap 2
    s.race([99000, 98000, 97000])
    engine, _ = make_engine(tmp_path)
    spoken = await replay(s.frames, engine, ConsolePlayer())
    assert [c.text for c in spoken] == [
        "Three laps. P five of sixteen.",
        "Lap one. one forty point zero.",
        "Three laps. P five of sixteen.",  # briefed again from the grid
        "Lap one. one thirty-nine point zero.",  # best is reset by the restart
        "Final lap.",
        "Lap two. one thirty-eight point zero.",
        "Lap three. one thirty-seven point zero. New best by one point zero.",
        "Chequered flag. Finished fifth. Best lap one thirty-seven point zero.",
    ]
    assert engine.races_started == 2
    db = sqlite3.connect(tmp_path / "index.sqlite")
    sessions = db.execute(
        "SELECT laps_completed, ended_at IS NOT NULL FROM sessions ORDER BY started_at, id"
    ).fetchall()
    assert sessions == [(1, 1), (3, 1)]
    first_laps = db.execute(
        "SELECT lap, complete FROM laps WHERE session_id = (SELECT min(id) FROM sessions)"
        " ORDER BY lap"
    ).fetchall()
    assert first_laps == [(1, 1), (2, 0)], "the lap in progress at the restart is kept partial"


async def test_quit_from_pause_menu_ends_session(tmp_path, sim):
    s = sim(total_laps=5)
    s.race([100000], finish=False)
    s.paused().loading().at_track().menu()
    engine, _ = make_engine(tmp_path)
    await replay(s.frames, engine, ConsolePlayer())
    assert engine.recorder is not None and engine.recorder.session is None
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT laps_completed, ended_at IS NOT NULL FROM sessions").fetchall() == [
        (1, 1)
    ]
    (session_dir,) = (tmp_path / "sessions").iterdir()
    assert (session_dir / "summary.json").exists()


async def test_stale_callouts_dropped_in_live_queue(tmp_path, sim):
    frames = sim(total_laps=3).race([100000] * 3).frames
    engine, queue = make_engine(tmp_path, max_age=8.0)
    for f in frames:
        engine.process(f)
    # Nothing was popped while time (frame t) moved on, so everything is stale now.
    assert queue.pop(frames[-1].t + 100) is None
    assert queue.dropped == queue.pushed


def test_recording_roundtrip(tmp_path, sim):
    frames = sim(total_laps=2).menu().race([100000, 100000]).frames
    path = tmp_path / "race.jsonl"
    assert write_recording(path, frames) == len(frames)
    assert list(read_recording(path, strict=True)) == frames


async def test_metrics_follow_state(tmp_path, sim):
    frames = sim(total_laps=20, fuel=100, burn=10).race([100000] * 2, finish=False).frames
    engine, _ = make_engine(tmp_path)
    await replay(frames, engine, ConsolePlayer())
    text = engine.metrics.render().decode()
    assert "gt7_in_race 1.0" in text
    assert "gt7_current_lap 3.0" in text
    assert 'gt7_callouts_total{rule="fuel"} 1.0' in text
    assert "gt7_fuel_laps_remaining 8.0" in text


async def test_post_results_blip_is_quiet(tmp_path, sim):
    """After the results screen GT7 replays the last frames of the race: a FINISHED
    frame and then an in-race frame with no lap total, no cars and no position
    (recording 2026-10-14). The in-race frame is evaluated, so every rule must
    treat it as nothing new."""
    s = sim(total_laps=2, position=4, cars=12)
    s.race([100000, 99000], finish=False)  # ends on the flag frame
    s.at_track()
    s._push(current_lap=3)  # FINISHED again
    s._push(current_lap=3, total_laps=0, cars_on_track=False, race_start_pos=-1, total_cars=-1)
    s.loading(0).menu()
    engine, _ = make_engine(tmp_path)
    spoken = await replay(s.frames, engine, ConsolePlayer())
    assert [c.text for c in spoken] == [
        "Two laps. P four of twelve.",
        "Final lap.",
        "Lap one. one forty point zero.",
        "Lap two. one thirty-nine point zero.",  # lap 1 is the start: no delta
        "Chequered flag. Finished fourth. Best lap one thirty-nine point zero.",
    ]
    assert engine.races_started == 1


async def test_track_verdict_reaches_the_brief_through_the_engine(tmp_path, sim):
    from those_who_run.trackdetect import TrackMatch

    s = sim(total_laps=2, position=3, cars=8)
    s.race([100000, 99000])
    engine, _ = make_engine(tmp_path)
    player = ConsolePlayer()
    frames = iter(s.frames)
    engine.process(next(frames))  # race start: session opens, rules reset
    engine._apply_track(TrackMatch(471, "Tsukuba Circuit", "probable", (), "test"))
    spoken = await replay(frames, engine, player)
    assert [c.text for c in spoken][0] == "Tsukuba Circuit. Two laps. P three of eight."


async def test_a_lap_posted_on_a_loading_frame_is_still_called(tmp_path, sim):
    """GT7 crosses the line into the pit cut-scene: the lap time and the counter
    bump arrive on a LOADING frame (Suzuka East, 2026-10-15). The engine compares
    the next driving frame with the last one before the loading screen."""
    from dataclasses import replace

    from those_who_run.state import Phase

    s = sim(total_laps=3)
    s.race([60000], finish=False)
    crossing = replace(s.frames[-1], phase=Phase.LOADING, t=s.frames[-1].t)
    frames = s.frames[:-1] + [crossing, replace(crossing, phase=Phase.IN_RACE, t=crossing.t + 0.1)]
    engine, _ = make_engine(tmp_path)
    spoken = await replay(iter(frames), engine, ConsolePlayer())
    assert "Lap one. one oh zero point zero." in [c.text for c in spoken]
    assert [lap["lap"] for lap in engine.recorder.session.laps] == [1], "lap 1 stored on its own"
    engine.recorder.close()


async def test_a_replay_between_two_races_is_ignored(tmp_path, sim):
    """A race, its GT7 replay (no cars-on-track flag, the fuel draining) and the
    next race: two sessions, two briefs, nothing from the replay (#243)."""
    s = sim(total_laps=2, position=4, cars=12, is_race=True)
    s.menu().at_track().race([100000, 99000]).menu().at_track()
    s.is_race = False
    s.race([100000, 99000]).menu().at_track()
    s.is_race = True
    s.race([101000, 98000])
    cards: list[dict] = []
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]),
        CalloutQueue(max_age=None),
        SessionStore(tmp_path, on_end=cards.append),
    )
    spoken = [c.text for c in await replay(s.frames, engine, ConsolePlayer())]
    assert engine.races_started == 2
    assert spoken.count("Two laps. P four of twelve.") == 2
    assert len([t for t in spoken if t.startswith("Chequered flag")]) == 2
    assert len(cards) == 2
    assert len(list((tmp_path / "sessions").iterdir())) == 2


async def test_an_unflagged_start_is_held_then_driven_as_if_never_held(tmp_path, sim):
    """The flag missing from the first frame only delays the session until it shows:
    every frame then goes through as it would have, so the callouts are the same."""
    from dataclasses import replace

    frames = sim(total_laps=3, is_race=True).menu().at_track().race([100000, 99000, 99500]).frames
    engine, _ = make_engine(tmp_path / "a")
    expected = [c.text for c in await replay(frames, engine, ConsolePlayer())]
    start = next(i for i, f in enumerate(frames) if f.in_race)
    late = list(frames)
    late[start] = replace(late[start], cars_on_track=False)
    engine, _ = make_engine(tmp_path / "b")
    assert engine.process(late[start - 1]) == [] and engine.process(late[start]) == []
    assert engine.races_started == 0, "held"
    rest = [c.text for c in await replay(late[start + 1 :], engine, ConsolePlayer())]
    assert rest == expected
    assert engine.races_started == 1


async def test_an_unflagged_race_with_no_fuel_use_is_driven(tmp_path, sim):
    """The races GT7 never flags (2026-10-15, #63) have never used fuel: they are
    driven, after the replay check's window, not ignored."""
    s = sim(total_laps=3, position=9, burn=0.0, is_race=False)
    frames = s.menu().at_track().race([100000, 99000, 99500]).frames
    engine, _ = make_engine(tmp_path)
    spoken = [c.text for c in await replay(frames, engine, ConsolePlayer())]
    assert spoken[0] == "Three laps."
    assert engine.races_started == 1
    assert len(list((tmp_path / "sessions").iterdir())) == 1
