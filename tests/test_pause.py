"""A paused race (#229): pause time is not driving time, a pause never splits the
session, a feed lost in a pause ends it paused, the recorder thins the pause, and
nothing is said while paused."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES, Settings
from those_who_run.engine import Engine
from those_who_run.pause import FREEZE_SECS, PauseClock
from those_who_run.pitwall.data import list_sessions
from those_who_run.recordtools import summarise_recording
from those_who_run.replay import OutingRecorder, read_recording, write_recording
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import Phase, RaceState
from those_who_run.store import SessionStore

from .archive import archived_outing
from .conftest import make_state

FIXTURES = Path(__file__).parent / "fixtures"
RESTARTS = FIXTURES / "real-nuc-sugo-restarts-2026-10-18.jsonl.gz"
NO_STOP = FIXTURES / "real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz"

# Outing 20261017-205541: a timed race, paused on lap 1 at +142.6 s for most of an
# hour, then the PS5 was switched off (#229).
PAUSE_START, PAUSE_END = 142.6, 3575.6


def _run(frames, tmp_path, **engine_kw):
    """Replay ``frames`` with a store; the callouts with their frame offsets, the
    summaries in order, and the engine. The replay ends the way ``replay`` does."""
    summaries: list[dict] = []
    store = SessionStore(tmp_path, on_end=summaries.append)
    engine = Engine(
        build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store, **engine_kw
    )
    said: list[tuple[float, str]] = []
    t0 = None
    for s in frames:
        t0 = s.t if t0 is None else t0
        said += [(s.t - t0, c.text) for c in engine.process(s)]
    engine.close_session()
    store.close()
    return said, summaries, engine


def _comparable(summary: dict) -> dict:
    """A summary without what differs between two replays of the same frames."""
    out = {k: v for k, v in summary.items() if k not in ("session_id", "started_at", "ended_at")}
    out["laps"] = [{k: v for k, v in x.items() if k != "recorded_at"} for x in summary["laps"]]
    return out


@pytest.fixture(scope="module")
def paused_hour():
    return list(read_recording(archived_outing("20261017-205541"), strict=True))


def test_real_paused_hour_is_not_driving_time_and_ends_paused(paused_hour, tmp_path):
    """#229 AC1: 110 s of driving, 3 433 s paused, then the feed went: one session,
    ended paused at the start of the pause, on lap 1 in P2."""
    said, (summary,), engine = _run(paused_hour, tmp_path)
    assert round(summary["driving_ms"], -3) == 110000
    assert round(summary["paused_ms"], -3) == 3433000
    assert summary["ended_paused"] is True
    assert (summary["laps_completed"], summary["finished"], summary["final_position"]) == (
        0,
        False,
        2,
    )
    assert engine.races_started == 1
    db = sqlite3.connect(tmp_path / "index.sqlite")
    row = db.execute("SELECT driving_ms, paused_ms, ended_paused FROM sessions").fetchone()
    db.close()
    assert row == (summary["driving_ms"], summary["paused_ms"], 1)
    # no full lap, so no card; the pit wall says how it ended, with the time driven
    assert build_card(summary) is None
    (row,) = list_sessions(tmp_path)
    assert row.result == "Paused on lap 1, P2, no full lap"
    assert round(row.minutes or 0, 1) == 1.8


def test_real_paused_hour_says_nothing_while_paused(paused_hour, tmp_path):
    """#229 AC4: nothing is queued in the pause (replay never speaks the feed-lost
    call, which the live watchdog raises)."""
    said, _, _ = _run(paused_hour, tmp_path)
    assert [(round(t, 1), text) for t, text in said] == [
        (34.9, "Timed race. P three of sixteen."),
        (112.1, "Up to second."),
    ]
    assert not [text for t, text in said if PAUSE_START <= t <= PAUSE_END]


def test_real_paused_hour_rerecorded_is_thinned_and_replays_the_same(paused_hour, tmp_path):
    """#229 AC3: the recorder keeps the pause at 1 Hz, first and last frame
    included, and the re-recorded outing gives the same summary.

    The pause was 96% of the frames but not of the bytes: identical frames compress
    to almost nothing. Its 205 776 frames go to 3 420; the 110 s of driving and the
    loading screens before it (8 540 frames at 60 Hz) are 2.3 MB of the 2.4 MB
    left, so the 0.5 MB in the issue cannot be met by thinning the pause alone."""
    outings = tmp_path / "outings"
    recorder = OutingRecorder(outings, keep=0, clock=lambda: 0.0)
    for s in paused_hour:
        recorder.write(s)
    recorder.close()
    (path,) = outings.iterdir()
    frames = list(read_recording(path, strict=True))
    paused = [s for s in frames if s.phase is Phase.PAUSED]
    assert len(paused) == 3420  # GT7's clock: 3 433 s at a little under 1 Hz
    assert paused[0] == next(s for s in paused_hour if s.phase is Phase.PAUSED)
    assert paused[-1] == paused_hour[-1]
    assert len(frames) - len(paused) == sum(1 for s in paused_hour if s.phase is not Phase.PAUSED)
    assert path.stat().st_size < 2.5e6
    _, (before,), _ = _run(paused_hour, tmp_path / "a")
    _, (after,), _ = _run(frames, tmp_path / "b")
    assert _comparable(after) == _comparable(before)


def _with_pause(frames: list[RaceState], lap: int, secs: float) -> list[RaceState]:
    """``frames`` with a pause of ``secs`` (2 Hz) in the middle of ``lap``."""
    on_lap = [i for i, s in enumerate(frames) if s.in_race and s.current_lap == lap]
    i = on_lap[len(on_lap) // 2]
    at = frames[i]
    n = int(secs * 2)
    pause = [
        replace(at, t=at.t + k / 2, packet_id=at.packet_id + k, phase=Phase.PAUSED)
        for k in range(1, n + 1)
    ]
    rest = [replace(s, t=s.t + secs, packet_id=s.packet_id + n) for s in frames[i + 1 :]]
    return [*frames[: i + 1], *pause, *rest]


def test_a_long_pause_mid_lap_changes_nothing_but_the_pause(tmp_path):
    """#229 AC2: ten minutes paused in the middle of lap 2 of a real six-lap race:
    one session, the same laps, lap times and calls, and the pause counted apart."""
    frames = list(read_recording(NO_STOP, strict=True))
    said, (plain,), _ = _run(frames, tmp_path / "plain")
    paused_said, (paused,), engine = _run(_with_pause(frames, 2, 600), tmp_path / "paused")
    assert engine.races_started == 1
    assert [text for _, text in paused_said] == [text for _, text in said]
    assert paused["laps"] == [
        {**x, "recorded_at": y["recorded_at"]}
        for x, y in zip(plain["laps"], paused["laps"], strict=True)
    ]
    # from the first paused frame to the first driving one: the pause and one gap
    assert plain["paused_ms"] == 0 and 600000 <= paused["paused_ms"] < 600500
    assert abs(paused["driving_ms"] - plain["driving_ms"]) < 500
    assert paused["ended_paused"] is False and paused["finished"] is True
    assert build_card(_comparable(paused)) == build_card(_comparable(plain))


def test_real_frozen_pause_says_nothing_and_counts_as_paused(tmp_path):
    """The other shape of a pause (#229, 2026-10-18 comment): at +235.9 s GT7 sent
    1.2 s of paused frames, then 45 s of identical in_race frames until Restart.
    It is a pause: no "Rear tyres hot." at +240 s, and 48.5 s paused in that
    session (with the 2 s pause on lap 1). The restart is not a pause end."""
    said, summaries, _ = _run(read_recording(RESTARTS, strict=True), tmp_path)
    assert not [text for t, text in said if 235.9 <= t <= 282.3]
    assert [(round(s["paused_ms"], -2), s["ended_paused"]) for s in summaries] == [
        (48500, False),
        (1000, False),
        (0, False),
    ]


def test_frozen_frames_are_a_pause_only_while_moving():
    clock = PauseClock()
    moving = make_state(t=0.0, speed_kph=26.9)
    seen = [clock.observe(replace(moving, t=k / 2)).phase for k in range(5)]
    assert seen == [Phase.IN_RACE] * 2 + [Phase.PAUSED] * 3  # from FREEZE_SECS on
    assert clock.since == 0.0, "dated from the first frozen frame"
    clock.observe(replace(moving, t=3.0, pos_x=1.0))
    assert (clock.since, clock.paused_secs) == (None, 3.0)
    standing = make_state(t=10.0, speed_kph=0.0, pos_x=5.0)
    still = [clock.observe(replace(standing, t=10 + k)).phase for k in range(4)]
    assert still == [Phase.IN_RACE] * 4, "a car standing still is not frozen"
    assert FREEZE_SECS == 1.0


def _race_then_pause(sim, pause_secs: int):
    s = sim(total_laps=5, position=3).menu().at_track().race([60000], finish=False)
    s.drive(5)
    for _ in range(pause_secs):
        s.paused()
    return s


def test_feed_lost_in_a_pause_ends_the_session_paused(tmp_path, sim):
    """#229 R3: the PS5 switched off in a pause. The session ends as of the start
    of the pause, and if the race carries on later it is not picked up again."""
    s = _race_then_pause(sim, 30)
    ends: list[dict] = []
    store = SessionStore(tmp_path, clock=lambda: 1000.0, on_end=ends.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    for f in s.frames:
        engine.process(f)
    assert store.session is not None
    pause_t = next(f.t for f in s.frames if f.phase is Phase.PAUSED)
    assert engine.feed_lost() is True
    (summary,) = ends
    assert summary["ended_paused"] is True
    assert summary["ended_at"] == summary["started_at"]  # the clock stood still here
    assert summary["paused_ms"] == (s.frames[-1].t - pause_t) * 1000
    card = build_card(summary)
    assert card is not None and card.description == "Paused on lap 2 of 5, P3"
    assert engine.feed_lost() is False, "nothing left to end"
    s.drive(10)  # back from rest mode, unpaused: not watched
    said = [c.text for f in s.frames[-10:] for c in engine.process(f)]
    assert said == [] and store.session is None
    s.menu().at_track().race([60000], finish=False)  # the next race is
    for f in s.frames[-4:]:
        engine.process(f)
    assert store.session is not None and engine.races_started == 2
    store.close()


def test_feed_lost_while_driving_keeps_the_session(tmp_path, sim):
    s = sim(total_laps=5).menu().at_track().race([60000], finish=False)
    store = SessionStore(tmp_path)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    for f in s.frames:
        engine.process(f)
    assert engine.feed_lost() is False and store.session is not None
    store.close()


def test_the_pause_limit_ends_a_long_pause(tmp_path, sim):
    """``GT7_PAUSE_LIMIT_SECS``: off by default; set, a pause that long ends the
    session paused."""
    s = _race_then_pause(sim, 120)
    _, (summary,), _ = _run(s.frames, tmp_path / "limit", pause_limit_secs=60)
    assert summary["ended_paused"] is True and summary["paused_ms"] == 60000
    _, (summary,), _ = _run(s.frames, tmp_path / "none")
    assert summary["ended_paused"] is True and summary["paused_ms"] == 119000  # end of frames
    assert Settings.from_env({}).pause_limit_secs == 0.0
    assert Settings.from_env({"GT7_PAUSE_LIMIT_SECS": "7200"}).pause_limit_secs == 7200.0


def test_a_quit_from_the_pause_menu_is_a_quit_with_its_pause_counted(tmp_path, sim):
    s = _race_then_pause(sim, 20).loading().at_track().menu()
    _, (summary,), _ = _run(s.frames, tmp_path)
    assert summary["ended_paused"] is False and summary["paused_ms"] == 20000
    card = build_card(summary)
    assert card is not None and card.description.startswith("Retired on lap 2 of 5")


def test_cards_for_a_session_that_ended_paused():
    base = {
        "laps_completed": 1,
        "ended_paused": True,
        "final_position": 2,
        "total_cars": 16,
        "laps": [{"lap": 1, "lap_time_ms": 90000, "complete": True}],
    }
    timed = {**base, "session_kind": {"kind": "timed_field", "field": True, "cars_on_track": True}}
    card = build_card(timed)
    assert card is not None and card.description == "Paused on lap 2, P2"
    solo = {**base, "session_kind": {"kind": "solo_timed"}}
    card = build_card(solo)
    assert card is not None and card.description == "Paused on lap 2"


def test_the_recorder_keeps_a_pause_at_one_frame_a_second(tmp_path):
    driving = [make_state(t=k / 60, packet_id=k) for k in range(60)]
    last = driving[-1]
    paused = [
        replace(last, t=last.t + k / 60, packet_id=last.packet_id + k, phase=Phase.PAUSED)
        for k in range(1, 601)
    ]
    resumed = replace(paused[-1], t=paused[-1].t + 1 / 60, phase=Phase.IN_RACE, pos_x=9.0)
    recorder = OutingRecorder(tmp_path, keep=0, clock=lambda: 0.0)
    for s in [*driving, *paused, resumed]:
        recorder.write(s)
    recorder.close()
    (path,) = tmp_path.iterdir()
    frames = list(read_recording(path, strict=True))
    kept = [s for s in frames if s.phase is Phase.PAUSED]
    assert kept[0] == paused[0] and kept[-1] == paused[-1]
    assert len(kept) == 11  # 0 s, 1 s ... 9 s, and the last
    assert frames[-1] == resumed and len(frames) == 60 + 11 + 1
    unthinned = OutingRecorder(tmp_path / "all", keep=0, clock=lambda: 0.0, paused_every=0)
    for s in paused:
        unthinned.write(s)
    unthinned.close()
    assert unthinned.count == 600


def test_recordings_lists_a_session_that_ends_in_a_pause(tmp_path, sim):
    path = tmp_path / "20261017-205541.jsonl"
    s = _race_then_pause(sim, 120)
    write_recording(path, s.frames)
    (session,), complete = summarise_recording(path)
    assert complete and session.ended == "paused"
    assert round(session.minutes * 60) == s.frames[-121].t - s.frames[2].t + 1
    assert json.dumps(session.summary["ended_paused"]) == "true"
