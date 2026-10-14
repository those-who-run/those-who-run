"""Regression test against a slice of a real GT7 session recorded on 2026-10-14.

The fixture keeps every frame where a tracked field changed, its neighbours,
and one frame per second otherwise. It covers: practice laps (time trial mode,
no cars on track), a two-lap race from P10 to P6, the chequered flag at
"lap 3 of 2", the results screen, and the replay blip GT7 emits afterwards.
"""

from pathlib import Path

from gt7_race_engineer.audio.player import ConsolePlayer
from gt7_race_engineer.callouts import CalloutQueue
from gt7_race_engineer.config import DEFAULT_RULES
from gt7_race_engineer.engine import Engine
from gt7_race_engineer.replay import read_recording, replay
from gt7_race_engineer.rules import build_rules
from gt7_race_engineer.state import Phase
from gt7_race_engineer.store import SessionStore

FIXTURE = Path(__file__).parent / "fixtures" / "real-race-2laps-2026-10-14.jsonl"


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
