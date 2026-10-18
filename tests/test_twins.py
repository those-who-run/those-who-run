"""Twin layouts the table cannot tell apart, and a pit cut-scene inside a session
(#275): Spa and Spa 24h are named as the circuit, and a loading screen that keeps
the lap counter never costs the session its track."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.pitwall.data import list_sessions
from those_who_run.replay import read_recording
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import Phase
from those_who_run.store import SessionStore
from those_who_run.trackdetect import TrackDetector, TrackMatch, box_iou
from those_who_run.tracks import TWINS, Track, track_by_id
from those_who_run.tracktools import detect_recording

from .conftest import make_state

FIXTURES = Path(__file__).parent / "fixtures"
PIT_CUT = FIXTURES / "real-nuc-spa-pit-cut-quit-2026-10-18.jsonl.gz"
TIME_TRIAL = FIXTURES / "real-nuc-spa-time-trial-2026-10-18.jsonl.gz"
SPA, SPA_24H = 462, 1269
CIRCUIT = "Circuit de Spa-Francorchamps"


def _engine(tmp_path, cards):
    store = SessionStore(tmp_path, on_end=cards.append)
    return Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store), store


def test_each_twin_shares_a_line_and_a_box_with_the_layout_named_after_its_circuit():
    by_name = {t.name: t for t in track_by_id().values()}
    for twin_id, family in TWINS.items():
        twin, base = track_by_id()[twin_id], by_name[family]
        assert twin.family == base.family == family
        assert twin.direction == base.direction
        assert twin.line is not None and base.line is not None
        assert max(math.dist(a, b) for a, b in zip(twin.line, base.line, strict=True)) < 0.5
        assert twin.box is not None and base.box is not None
        assert box_iou(twin.box, base.box) >= 0.98, twin.name
    assert track_by_id()[SPA_24H].family == CIRCUIT
    assert track_by_id()[837].family == "Fuji International Speedway"  # from its name


def test_real_spa_is_the_circuit_and_holds_still():
    """Spa and Spa 24h share a line and a box: the detector named one, then the
    other, ambiguous, as their fit swapped by a thousandth. The circuit is known."""
    final, steps = detect_recording(TIME_TRIAL)
    named = {(s.match.track_id, s.match.name, s.match.confidence) for s in steps if s.match.name}
    assert named == {(SPA, CIRCUIT, "probable")}
    assert final.family == CIRCUIT
    assert {c.track.id for c in final.candidates if c.line_crossed} == {SPA, SPA_24H}


def test_real_spa_keeps_its_track_through_the_pit_cut_and_the_quit(tmp_path):
    """Spa, 2026-10-18 14:16 (outing 20261018-141557): five laps in the Porsche 962
    C, then into the pits, which GT7 shows as a loading cut-scene with the lap
    counter kept, and a quit 13 s later. The cut-scene reset the detector like a
    restart, and the session was saved with no track (#275 AC1)."""
    cards: list[dict] = []
    engine, store = _engine(tmp_path, cards)
    seen, after_cut = [], []
    cut = False
    for s in read_recording(PIT_CUT, strict=True):
        engine.process(s)
        cut = cut or (s.phase is Phase.LOADING and s.current_lap == 5)
        if engine.track is not None:
            seen.append(engine.track.name)
        if cut and s.phase is Phase.IN_RACE:
            after_cut.append(engine.tracks.match.name)
    store.close()
    assert cut and after_cut and set(after_cut) == {CIRCUIT}, "the cut-scene kept it"
    first = seen.index(CIRCUIT)
    assert set(seen[first:]) == {CIRCUIT}, "never dropped once named"
    (summary,) = cards
    assert summary["laps_completed"] == 4
    assert summary["track"]["name"] == CIRCUIT and summary["track"]["id"] == SPA
    assert summary["track"]["confidence"] == "probable"
    card = build_card(summary)
    assert card is not None and card.title.startswith(f"{CIRCUIT} ·")
    (row,) = list_sessions(tmp_path)
    assert row.track == CIRCUIT and row.track_id == SPA  # the pit wall, and lap compare
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT track_id, track_confidence FROM sessions").fetchall() == [
        (SPA, "probable")
    ]
    db.close()


def test_real_spa_time_trial_is_briefed_and_shown_as_the_circuit(tmp_path):
    """Spa, 2026-10-18 14:26 (outing 20261018-142627): a flying start in the Tomahawk
    VGT crosses the line at once. The brief names the circuit, and the pit wall
    shows it while the session is still open."""
    cards: list[dict] = []
    engine, store = _engine(tmp_path, cards)
    said: list[str] = []
    open_rows = []
    for s in read_recording(TIME_TRIAL, strict=True):
        said += [c.text for c in engine.process(s)]
        if s.current_lap == 2 and not open_rows:
            store.wait()
            open_rows = list_sessions(tmp_path)
    store.close()
    assert "Circuit de Spa Francorchamps" in said[0]  # the brief, worded at random
    assert [r.track for r in open_rows] == [CIRCUIT] and not open_rows[0].closed
    (summary,) = cards
    card = build_card(summary)
    assert card is not None and card.title == f"{CIRCUIT} · time trial"


def _line_tracks() -> tuple[Track, ...]:
    # Two circuits whose layouts share a line and a box: a pair the lap cannot split.
    line = ((100.0, 0.0), (100.0, 20.0))
    return (
        Track(1, "Alpha", "PX", line, (0, 0, 1000, 400)),
        Track(2, "Alpha - Long", "PX", line, (0, 0, 1000, 401)),
        Track(3, "Beta", "PX", line, (0, 0, 1000, 402)),
    )


def test_a_pair_of_one_circuit_is_the_circuit_and_a_mixed_pair_is_not():
    def drive(det: TrackDetector) -> TrackMatch:
        for lap in (1, 2):
            for x in range(50, 1000, 10):
                det.observe_point(float(x), 10.0, lap=lap)
            for x in range(1000, 50, -10):
                det.observe_point(float(x), 390.0, lap=lap)
        det.observe_point(50.0, 10.0, lap=2)
        return det.match

    twins = drive(TrackDetector(_line_tracks()[:2], box_tolerance_m=20, start_radius_m=500))
    assert (twins.track_id, twins.name, twins.confidence) == (1, "Alpha", "probable")
    assert twins.family == "Alpha" and "all Alpha" in twins.evidence
    mixed = drive(TrackDetector(_line_tracks(), box_tolerance_m=20, start_radius_m=500))
    assert mixed.confidence == "ambiguous" and mixed.family is None


def test_a_named_track_is_not_replaced_by_no_track_at_the_same_confidence():
    """At Spa an ambiguous pair gave way to an ambiguous nothing, and the session
    was saved without a track (#275 R4). A layout still alive stays."""
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None))
    engine.process(make_state(t=0.0, current_lap=1))
    spa = TrackMatch(SPA, CIRCUIT, "ambiguous", (), "pair")
    engine._apply_track(spa)
    engine._apply_track(TrackMatch(None, None, "ambiguous", (), "28 layouts"))
    assert engine.track is spa
    other = TrackMatch(SPA_24H, "Spa 24h Layout", "ambiguous", (), "pair")
    engine._apply_track(other)
    assert engine.track is other  # a named one at the same confidence still moves
