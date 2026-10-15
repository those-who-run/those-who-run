"""Regression test against a slice of a real GT7 session recorded on 2026-10-14.

The fixture keeps every frame where a tracked field changed, its neighbours,
and one frame per second otherwise. It covers: practice laps (time trial mode,
no cars on track), a two-lap race from P10 to P6, the chequered flag at
"lap 3 of 2", the results screen, and the replay blip GT7 emits afterwards.
"""

import sqlite3
from pathlib import Path

from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.rules import build_rules
from those_who_run.state import Phase
from those_who_run.store import SessionStore

FIXTURE = Path(__file__).parent / "fixtures" / "real-race-2laps-2026-10-14.jsonl"
QUALI = Path(__file__).parent / "fixtures" / "real-quali-restart-quit-2026-10-14.jsonl"


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
        # practice session: the engineer started mid-session on lap 7
        "Lap seven. forty-nine point seven.",
        # the race: P10 on the grid
        "Up to ninth.",
        "Final lap.",
        "Lap one. fifty-one point zero.",
        "Up to eighth.",
        "Up to seventh.",
        "Lap two. fifty-three point one. two point one over best.",
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
        "Fuel. three laps remaining.",
        "Lap one. eight twenty-six point four.",
        "Lap one. eight twenty point four.",
        "Lap two. eight twenty point two. zero point two under best.",
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
