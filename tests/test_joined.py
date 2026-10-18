"""The engineer starting part way through a session (#265): no grid-slot brief, no
cold-tyre call, no track from a mid-lap start, and the session marked as joined."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine, joined_part_way
from those_who_run.replay import read_recording
from those_who_run.results import build_card
from those_who_run.rules import FuelRule, build_rules
from those_who_run.store import SessionStore

from .conftest import make_state

JOINED = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-joined-mid-race-2026-10-18.jsonl.gz"
SUZUKA = 10


def _engine(tmp_path, cards):
    store = SessionStore(tmp_path, on_end=cards.append)
    return Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store), store


def test_real_engineer_restarted_mid_race(tmp_path):
    """Suzuka timed race, 2026-10-18 13:45 (outing 20261018-134517): the pod came
    back 20 s into lap 7, leading, at 124 km/h. Live, 0.5.1 said "Timed race. P one
    of seventeen." (a grid slot), "Tyres cold." (rears at 44 C after six laps) and
    two Lago Maggiore layouts, from the mid-lap start near their line and a path
    across it. Joined part way it says where the race is, and the track is Suzuka,
    probable from the line at the end of lap 7 (#265 AC1)."""
    cards: list[dict] = []
    engine, store = _engine(tmp_path, cards)
    said, tracks = [], set()
    for s in read_recording(JOINED, strict=True):
        said += [c.text for c in engine.process(s)]
        if engine.track is not None and engine.track.track_id is not None:
            tracks.add((engine.track.track_id, engine.track.confidence))
    assert engine.prev is not None
    store.end_session(engine.prev)  # the fixture stops on lap 8
    store.close()
    assert said == [
        "Back with you. Lap seven. P one.",
        "Lap seven. two thirty point five. two point three over best.",
    ]
    assert tracks == {(SUZUKA, "probable")}
    (summary,) = cards
    assert summary["joined_on_lap"] == 7
    assert summary["track"]["id"] == SUZUKA
    assert summary["session_kind"]["kind"] == "timed_field"
    assert summary["session_kind"]["start"] == "unknown", "the start was not seen"
    card = build_card(summary)
    assert card is not None and dict(card.fields)["Joined"] == "on lap 7"
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT joined_on_lap FROM sessions").fetchall() == [(7,)]
    db.close()


def test_joined_only_past_lap_1_with_nothing_before():
    racing = make_state(current_lap=3)
    assert joined_part_way(None, racing)
    assert not joined_part_way(make_state(current_lap=2), racing), "a frame before it"
    # lap 1 at speed with nothing before it is a flying start as much as a join
    assert not joined_part_way(None, make_state(current_lap=1, speed_kph=200.0))


def test_a_joined_lap_race_is_briefed_on_the_lap_and_its_first_lap_not_measured(tmp_path):
    """Joined on lap 3 of 5 on cold rears: the brief has the lap and the place, not
    a grid slot, and no cold-tyre call. The fuel used on lap 3 is part of a lap,
    so the first measured lap is lap 4."""
    common = dict(total_laps=5, race_start_pos=4, tire_temp=(60.0, 60.0, 40.0, 40.0))
    frames = []
    t, fuel = 0.0, 80.0
    for lap, last in ((3, 59000), (4, 60000), (5, 61000)):
        for _ in range(6):
            t += 1
            fuel -= 1.0
            frames.append(
                make_state(
                    t=t,
                    packet_id=int(t),
                    current_lap=lap,
                    last_lap_ms=last,
                    best_lap_ms=59000,
                    fuel_level=fuel,
                    **common,
                )
            )
    cards: list[dict] = []
    engine, store = _engine(tmp_path, cards)
    said = [c.text for f in frames for c in engine.process(f)]
    assert engine.prev is not None
    store.end_session(engine.prev)
    store.close()
    assert said[0] == "Back with you. Lap three of five. P four."
    assert "Tyres cold." not in said
    fuel_rule = next(r for r in engine.rules if isinstance(r, FuelRule))
    assert list(fuel_rule.consumption) == [6.0]  # lap 4; lap 3 was joined part way
    assert cards[0]["joined_on_lap"] == 3


def test_real_willow_springs_cut_mid_race_names_no_wrong_track(tmp_path):
    """The Willow Springs pit-stop fixture starts mid-lap 6, as when the engineer
    starts mid-race. Read as a fresh start it named four other tracks on lap 6
    (Dragon Trail, two Lago Maggiore layouts, Kyoto) from crossings of their
    lines; joined part way it names none (#265)."""
    path = (
        Path(__file__).parent / "fixtures" / "real-nuc-willow-springs-pit-stop-2026-10-17.jsonl.gz"
    )
    cards: list[dict] = []
    engine, store = _engine(tmp_path, cards)
    said = []
    for s in read_recording(path, strict=True):
        engine.process(s)
        while (c := engine.queue.pop(s.t)) is not None:
            said.append(c.text)
    store.close()
    assert [t for t in said if t.startswith(("Back with you", "Dragon", "Autodrome", "Kyoto"))] == [
        "Back with you. Lap six of ten. P one."
    ]
