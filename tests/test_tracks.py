"""Track detection: the table, the geometry, synthetic layouts and a real lap."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import make_state
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.metrics import Metrics
from those_who_run.replay import read_recording, replay
from those_who_run.rules import build_rules
from those_who_run.state import Phase
from those_who_run.store import SessionStore
from those_who_run.trackdetect import (
    TrackDetector,
    box_contains,
    box_iou,
    distance_to_segment,
    segment_crosses,
    travel_direction,
    widen_segment,
)
from those_who_run.tracks import Track, load_tracks, track_by_id, track_name
from those_who_run.tracktools import backfill, detect_recording, detect_session, learn_track

FIXTURE = Path(__file__).parent / "fixtures" / "real-n24h-race-lap1-positions-2026-10-14.jsonl"
UNKNOWN_FIXTURE = Path(__file__).parent / "fixtures" / "real-nuc-unknown-track-2026-10-15.jsonl"
SUZUKA_FIXTURE = Path(__file__).parent / "fixtures" / "real-nuc-suzuka-east-2026-10-15.jsonl"
N24H, GP, NORDSCHLEIFE, TOURIST = 348, 349, 95, 347
FUJI, FUJI_SHORT = 16, 837
SUZUKA, SUZUKA_EAST = 10, 442


# the table


def test_table_loads_with_names_and_geometry():
    tracks = load_tracks()
    assert len(tracks) == 106
    assert sum(t.has_geometry for t in tracks) == 103
    assert all(t.length_m is None for t in tracks)  # none known yet; `tracks learn` fills them
    assert track_name(N24H) == "Nurburgring 24h"
    assert track_name(471) == "Tsukuba Circuit"
    assert track_name(None) is None
    assert track_name(999999) == "track 999999"
    n24h = track_by_id()[N24H]
    assert n24h.direction == "NX" and n24h.line is not None and n24h.box is not None
    assert n24h.box[0] < n24h.box[2] and n24h.box[1] < n24h.box[3]
    assert all(t.direction in {"PX", "NX", "PZ", "NZ"} for t in tracks if t.has_geometry)


# geometry


def test_segment_crossing_and_direction_convention():
    line = ((100.0, 0.0), (100.0, 50.0))
    assert segment_crosses((90, 25), (110, 25), *line)
    assert segment_crosses((90, 50), (110, 50), *line)  # touching the end counts
    assert not segment_crosses((90, 60), (110, 60), *line)  # past the end
    assert not segment_crosses((0, 25), (50, 25), *line)  # short of it
    assert not segment_crosses((90, 25), (90, 30), *line)  # parallel
    # The table keys direction on the sign of x first, then z: not the dominant axis.
    assert travel_direction((0, 0), (-1, 100)) == "NX"
    assert travel_direction((0, 0), (1, -100)) == "PX"
    assert travel_direction((0, 0), (0, 5)) == "PZ"
    assert travel_direction((0, 0), (0, -5)) == "NZ"
    assert travel_direction((0, 0), (0, 0)) is None


def test_boxes_and_distances():
    assert box_contains((0, 0, 100, 100), (10, 10, 90, 90), 0)
    assert not box_contains((0, 0, 100, 100), (10, 10, 120, 90), 0)
    assert box_contains((0, 0, 100, 100), (10, 10, 120, 90), 25)
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert box_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert distance_to_segment((5, 5), (0, 0), (10, 0)) == 5
    assert distance_to_segment((20, 0), (0, 0), (10, 0)) == 10
    assert distance_to_segment((3, 4), (0, 0), (0, 0)) == 5


# synthetic layouts. A rectangle circuit 1000 x 400 m with its finish line on the
# bottom straight, crossed moving +x; a short variant sharing the line; its reverse
# twin; and a huge unrelated box like Special Stage Route X.


def _tracks() -> tuple[Track, ...]:
    line = ((100.0, 0.0), (100.0, 20.0))
    return (
        Track(1, "Full", "PX", line, (0, 0, 1000, 400)),
        Track(2, "Short", "PX", line, (0, 0, 500, 400)),
        Track(3, "Full Reverse", "NX", line, (0, 0, 1000, 400)),
        Track(
            4, "Far Away", "PX", ((4000.0, 4000.0), (4000.0, 4020.0)), (-5000, -5000, 5000, 5000)
        ),
    )


def _rect_lap(
    x0: float, x1: float, z0: float, z1: float, step: float = 10.0
) -> list[tuple[float, float]]:
    """Points around a rectangle, anticlockwise, starting at (x0, z0) heading +x."""
    pts: list[tuple[float, float]] = []
    x, z = x0, z0
    while x < x1:
        pts.append((x, z))
        x += step
    while z < z1:
        pts.append((x1, z))
        z += step
    while x > x0:
        pts.append((x, z1))
        x -= step
    while z > z0:
        pts.append((x0, z))
        z -= step
    return pts[3:] + pts[:3]  # lap boundary mid-straight, heading +x, not on a corner


def _drive(det: TrackDetector, points, lap: int | None = None) -> list:
    changes = []
    for x, z in points:
        m = det.observe_point(x, z, lap=lap)
        if m is not None:
            changes.append(m)
    return changes


def _drive_laps(det: TrackDetector, lap_points, laps: int, first_lap: int = 1) -> None:
    """Drive the same loop ``laps`` times, incrementing the lap counter at the start of each."""
    for n in range(laps):
        _drive(det, lap_points, lap=first_lap + n)


FULL_LAP = _rect_lap(50, 980, 10, 390)  # fills Full's box, leaves Short's
SHORT_LAP = _rect_lap(50, 480, 10, 390)


def test_family_narrows_by_bounds_then_line_then_a_full_lap():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)
    first = det.observe_point(80, 10, lap=1)
    assert first is not None and first.confidence == "ambiguous"
    assert set(first.candidate_ids) == {1, 2, 3} and first.track_id is None
    # First straight crosses the line at x=100 moving +x: Full and Short, not Reverse.
    _drive(det, FULL_LAP[:30], lap=1)
    m = det.match
    assert m.confidence == "ambiguous"
    assert {c.track.id for c in m.candidates if c.line_crossed} == {1, 2}
    assert 3 in m.candidate_ids  # the reverse twin still contains the path; not crossed
    assert m.track_id in (1, 2)  # shared line: best fit named, still ambiguous
    # Past x=500 Short's box is left behind: Full alone, line crossed, no full lap yet.
    _drive(det, FULL_LAP[30:], lap=1)
    assert det.match.confidence == "probable" and det.match.track_id == 1
    assert "no full lap yet" in det.match.evidence
    # The lap counter ticks over: the lap fills Full's box.
    changes = _drive(det, FULL_LAP[:3], lap=2)
    assert det.match.confidence == "confirmed" and det.match.track_id == 1
    assert changes and "a full lap fits" in changes[-1].evidence
    assert [c.track.id for c in det.match.candidates if c.line_crossed] == [1]


def test_short_layout_wins_when_the_lap_stays_inside_it():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500)
    _drive_laps(det, SHORT_LAP, laps=2)
    m = det.match
    assert m.confidence == "confirmed" and m.track_id == 2
    # Full also contained the lap and shares the line, but a completed Short lap fills
    # well under half of Full's box, so Full is ruled out rather than merely outranked.
    assert m.candidate_ids == (2,)


def test_only_layout_near_the_start_becomes_probable_after_some_driving():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)
    # Start 1 km from every line, inside Full/Reverse/Far boxes: nothing to anchor on.
    _drive(det, [(x, 390.0) for x in range(900, 600, -10)])
    m = det.match
    assert m.confidence == "ambiguous" and m.track_id is None
    assert set(m.candidate_ids) == {1, 3, 4} and "no finish line within" in m.evidence

    det = TrackDetector(
        (_tracks()[0], _tracks()[3]), box_tolerance_m=20, start_radius_m=500, min_distance_m=300
    )
    _drive(det, [(x, 10.0) for x in range(140, 300, 10)])
    assert det.match.confidence == "ambiguous"  # unique, but has barely moved
    _drive(det, [(x, 10.0) for x in range(300, 600, 10)])
    assert det.match.confidence == "probable" and det.match.track_id == 1
    assert "only layout" in det.match.evidence


def test_teleport_is_not_a_line_crossing_and_leaving_every_box_gives_none():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, teleport_m=100)
    det.observe_point(140, 10)
    det.observe_point(150, 10)
    # Return to pits: jump from one side of the line to the other.
    det.observe_point(50, 10)
    assert det.match.confidence == "ambiguous"
    assert not any(c.line_crossed for c in det.match.candidates)
    assert det.distance_m == pytest.approx(10)
    # Drive off every table box.
    _drive(det, [(x, 10.0) for x in range(50, 7000, 50)])
    assert det.match.confidence == "none" and det.match.track_id is None


def test_menu_or_loading_frame_starts_over_but_a_pause_does_not():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)

    def frame(phase: Phase, x: float, z: float, lap: int = 1):
        return make_state(phase=phase, current_lap=lap, track_id=None, pos_x=x, pos_z=z)

    for x in range(140, 700, 10):
        det.observe(frame(Phase.IN_RACE, x, 10))
    assert det.distance_m > 500
    det.observe(frame(Phase.PAUSED, 700, 10))
    det.observe(frame(Phase.IN_RACE, 700, 10))
    assert det.distance_m > 500  # pause kept everything
    det.observe(frame(Phase.LOADING, 0, 0))
    det.observe(frame(Phase.AT_TRACK, 140, 10, lap=0))
    assert det.distance_m == 0  # new venue: start over


def test_widen_segment_keeps_midpoint_and_direction():
    a, b = widen_segment((0.0, 0.0), (0.0, 20.0), 50.0)
    assert a == pytest.approx((0.0, -40.0)) and b == pytest.approx((0.0, 60.0))
    assert widen_segment((1.0, 1.0), (1.0, 1.0), 50.0) == ((1.0, 1.0), (1.0, 1.0))


def test_lap_counter_confirms_despite_a_misplaced_table_segment():
    # The table's segment sits 30 m beside the straight the car uses, as at Fuji.
    tracks = (
        Track(1, "Here", "PX", ((100.0, 60.0), (100.0, 80.0)), (0, 0, 1000, 400)),
        Track(2, "Elsewhere", "PX", ((900.0, 60.0), (900.0, 80.0)), (0, 0, 1000, 400)),
    )
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500, line_half_width_m=5)
    _drive(det, FULL_LAP, lap=1)
    assert not any(c.line_crossed for c in det.match.candidates)
    _drive(det, FULL_LAP[:3], lap=2)  # GT7 says: new lap, so x=100 is the line
    m = det.match
    assert m.confidence == "confirmed" and m.track_id == 1
    assert m.candidate_ids == (1,)  # Elsewhere's line is 800 m from the boundary: dropped


def test_lap_counter_drops_layouts_whose_line_is_far_or_faces_the_other_way():
    tracks = (
        Track(1, "Forward", "PX", ((100.0, 0.0), (100.0, 20.0)), (0, 0, 1000, 400)),
        Track(3, "Reverse", "NX", ((100.0, 0.0), (100.0, 20.0)), (0, 0, 1000, 400)),
        Track(4, "Far", "PX", ((700.0, 0.0), (700.0, 20.0)), (0, 0, 1000, 400)),
    )
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500)
    _drive(det, FULL_LAP, lap=1)
    assert 1 in det.match.candidate_ids and 3 in det.match.candidate_ids
    _drive(det, FULL_LAP[:3], lap=2)
    assert det.match.confidence == "confirmed" and det.match.track_id == 1
    assert det.match.candidate_ids == (1,)


def test_a_completed_lap_that_does_not_fill_the_box_rules_the_layout_out():
    # A new, unknown circuit whose line happens to sit near a known layout's line.
    tracks = (Track(1, "Known", "PX", ((100.0, 0.0), (100.0, 20.0)), (0, 0, 1000, 1000)),)
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500)
    _drive(det, FULL_LAP, lap=1)
    assert det.match.confidence == "probable" and det.match.track_id == 1
    _drive(det, FULL_LAP[:3], lap=2)  # the lap only fills 40% of Known's box
    assert det.match.confidence == "none" and det.match.track_id is None
    assert det.lap_length_m == pytest.approx(2 * (930 + 380), abs=40)


def test_known_lap_length_separates_layouts_with_one_box():
    line = ((100.0, 0.0), (100.0, 20.0))
    tracks = (
        Track(1, "Chicane", "PX", line, (0, 0, 1000, 400), length_m=2620),
        Track(2, "No Chicane", "PX", line, (0, 0, 1000, 400), length_m=2300),
    )
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500)
    _drive_laps(det, FULL_LAP, laps=2)
    assert det.match.confidence == "confirmed" and det.match.track_id == 1
    assert det.match.candidate_ids == (1,)


def test_first_racing_frame_anchors_when_the_first_frame_was_a_menu_screen():
    tracks = (
        Track(1, "Here", "PX", ((100.0, 0.0), (100.0, 20.0)), (0, 0, 1000, 400)),
        Track(4, "Huge", "PX", ((4000.0, 4000.0), (4000.0, 4020.0)), (-5000, -5000, 5000, 5000)),
    )
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500, min_distance_m=100)
    det.observe_point(950, 390)  # pre-session camera, nowhere near the line
    assert det.match.track_id is None and "no finish line within" in det.match.evidence
    _drive(det, [(x, 10.0) for x in range(140, 400, 10)], lap=1)  # racing from the grid
    assert det.match.confidence == "probable" and det.match.track_id == 1


def test_widened_segment_catches_a_crossing_beside_the_recorded_one():
    tracks = (Track(1, "Here", "PX", ((100.0, 60.0), (100.0, 80.0)), (0, 0, 1000, 400)),)
    narrow = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500, line_half_width_m=5)
    wide = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500, line_half_width_m=50)
    for det in (narrow, wide):
        det.observe_point(90, 30)
        det.observe_point(110, 30)  # 30 m beside the 20 m recorded segment
    assert not narrow.match.candidates[0].line_crossed
    assert wide.match.candidates[0].line_crossed and wide.match.confidence == "probable"


# the real thing: Nürburgring 24h race, 2026-10-14, from the pre-race screen to lap 2


def test_real_n24h_race_is_probable_before_the_lights_and_confirmed_after_lap_1():
    final, steps = detect_recording(FIXTURE)
    assert final.track_id == N24H and final.confidence == "confirmed"
    assert "a full lap fits" in final.evidence and final.candidates[0].fit > 0.85
    race_start = next(s.t for s in read_recording(FIXTURE) if s.phase is Phase.IN_RACE)
    probable = next(
        s for s in steps if s.match.confidence == "probable" and s.match.track_id == N24H
    )
    assert probable.t < race_start  # the rolling start crosses the line before lap 1
    confirmed = next(s for s in steps if s.match.confidence == "confirmed")
    assert confirmed.lap == 2  # the lap counter closed a lap that fills the 24h box
    assert confirmed.match.candidate_ids == (N24H,)
    # On the way there the GP layout and both Nordschleife layouts were live candidates.
    seen = {tid for s in steps for tid in s.match.candidate_ids}
    assert {GP, NORDSCHLEIFE, TOURIST} <= seen


# the real thing, from the NUC (2026-10-15): a lap of a track GT7 added that day, which
# the table does not have, and a one-lap race at Suzuka East.


def test_real_unknown_track_is_reported_as_none_not_as_fuji():
    final, steps = detect_recording(UNKNOWN_FIXTURE)
    # Fuji's recorded line sits 99 m from where the lap counter ticked, so on the lap
    # counter alone the Fuji pair looked crossed; the completed lap fills only 35% of
    # their box, which rules them out.
    before = [s for s in steps if s.lap == 1]
    assert before and all(s.match.track_id is None for s in before)
    assert final.confidence == "none" and final.track_id is None
    assert final.candidates == ()


def test_real_suzuka_east_is_confirmed_on_the_lap_counter():
    final, steps = detect_recording(SUZUKA_FIXTURE)
    assert final.track_id == SUZUKA_EAST and final.confidence == "confirmed"
    assert final.candidates[0].fit > 0.9
    # The full Suzuka shares the line and contained the lap, but the lap fills a quarter of it.
    decided = next(s for s in steps if s.match.confidence == "confirmed")
    assert decided.lap == 2 and SUZUKA not in decided.match.candidate_ids
    on_lap_1 = [s for s in steps if s.lap == 1]
    assert on_lap_1 and all(s.match.confidence in ("ambiguous", "probable") for s in on_lap_1)


def test_learn_track_derives_a_row_from_the_unknown_lap():
    learned = learn_track(UNKNOWN_FIXTURE)
    assert learned.laps_used == 1
    assert 3400 < learned.lap_length_m < 3700
    assert learned.direction == "PX"
    (p1x, p1z), (p2x, p2z) = learned.line
    assert abs(p1x - 96) < 5 and abs(p2x - 96) < 5  # perpendicular to +x travel
    assert abs((p1z + p2z) / 2 + 213) < 5
    minx, minz, maxx, maxz = learned.box
    assert 1000 < maxx - minx < 1150 and 480 < maxz - minz < 580
    assert learned.nearest[0][1] in (FUJI, FUJI_SHORT) and learned.nearest[0][0] < 120
    row = learned.csv_row(100001, "New Track")
    assert row.startswith("100001,New Track,PX,") and row.endswith(f"{learned.lap_length_m:.0f}")


def test_learn_track_needs_a_completed_lap(tmp_path):
    from those_who_run.replay import write_recording

    partial = tmp_path / "partial.jsonl"
    write_recording(
        partial,
        [make_state(t=float(i), current_lap=1, track_id=None, pos_x=10.0 * i) for i in range(50)],
    )
    with pytest.raises(ValueError, match="no completed lap"):
        learn_track(partial)


def test_engine_records_the_track_in_the_session(tmp_path):
    store = SessionStore(tmp_path)
    metrics = Metrics()
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store, metrics)
    import asyncio

    asyncio.run(replay(read_recording(FIXTURE), engine, ConsolePlayer()))
    assert engine.track is not None and engine.track.track_id == N24H
    assert engine.track.confidence == "confirmed"
    sess = store.session
    assert sess is not None and sess.track_id == N24H
    assert sess.track["confidence"] == "confirmed" and sess.track["name"] == "Nurburgring 24h"
    db = sqlite3.connect(tmp_path / "index.sqlite")
    assert db.execute("SELECT track_id, track_confidence FROM sessions").fetchall() == [
        (N24H, "confirmed")
    ]
    assert metrics.track_id._value.get() == N24H
    assert b'gt7_track_info{confidence="confirmed",name="Nurburgring 24h",track_id="348"} 1.0' in (
        metrics.render()
    )
    # Finish the session: summary carries the verdict.
    last = list(read_recording(FIXTURE))[-1]
    store.end_session(last)
    summary = json.loads((tmp_path / "sessions").glob("*/summary.json").__next__().read_text())
    assert summary["track_id"] == N24H
    assert summary["track"]["confidence"] == "confirmed"
    assert summary["track"]["candidates"][0]["name"] == "Nurburgring 24h"


def test_backfill_restores_a_session_detected_from_parquet(tmp_path):
    import asyncio

    store = SessionStore(tmp_path)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    frames = list(read_recording(FIXTURE))
    asyncio.run(replay(frames, engine, ConsolePlayer()))
    store.end_session(frames[-1])
    store.close()
    session_dir = next((tmp_path / "sessions").glob("*"))
    assert (session_dir / "lap-01.parquet").exists()

    # Pretend the session predates detection.
    db = sqlite3.connect(tmp_path / "index.sqlite")
    db.execute("UPDATE sessions SET track_id = NULL, track_confidence = NULL")
    db.commit()
    summary_path = session_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["track_id"] = None
    summary.pop("track")
    summary_path.write_text(json.dumps(summary))

    match, steps = detect_session(session_dir)
    assert match.track_id == N24H and match.confidence in ("confirmed", "probable")

    results = backfill(tmp_path)
    assert len(results) == 1 and results[0].updated
    assert results[0].after.track_id == N24H
    assert db.execute("SELECT track_id, track_confidence FROM sessions").fetchall() == [
        (N24H, match.confidence)
    ]
    assert json.loads(summary_path.read_text())["track"]["id"] == N24H
    # Second run: nothing to do unless forced.
    again = backfill(tmp_path)
    assert not again[0].updated and again[0].note in (
        "already confirmed",
        "stored answer is better",
        "updated",
    )
    forced = backfill(tmp_path, force=True)
    assert forced[0].updated


def test_backfill_clears_a_stale_guess_when_nothing_fits(tmp_path):
    import asyncio

    store = SessionStore(tmp_path)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    frames = list(read_recording(UNKNOWN_FIXTURE))
    asyncio.run(replay(frames, engine, ConsolePlayer()))
    store.end_session(frames[-1])
    store.close()
    db = sqlite3.connect(tmp_path / "index.sqlite")
    # An older detector had guessed Blue Moon Bay for this lap.
    db.execute("UPDATE sessions SET track_id = 356, track_confidence = 'ambiguous'")
    db.commit()
    results = backfill(tmp_path)
    assert len(results) == 1 and results[0].updated and results[0].note == "cleared stale guess"
    assert db.execute("SELECT track_id, track_confidence FROM sessions").fetchall() == [
        (None, "none")
    ]
    summary = json.loads(next((tmp_path / "sessions").glob("*/summary.json")).read_text())
    assert summary["track_id"] is None and summary["track"]["confidence"] == "none"
    # Nothing to do on a second run.
    assert not backfill(tmp_path)[0].updated
    # A confirmation is never replaced by "nothing fits" unless forced.
    db.execute("UPDATE sessions SET track_id = 356, track_confidence = 'confirmed'")
    db.commit()
    again = backfill(tmp_path)
    assert not again[0].updated and again[0].note == "already confirmed"
    assert backfill(tmp_path, force=True)[0].updated


def test_index_without_the_confidence_column_is_migrated(tmp_path):
    db = sqlite3.connect(tmp_path / "index.sqlite")
    db.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL, ended_at REAL,"
        " type TEXT NOT NULL, track_id INTEGER, car_code INTEGER, total_laps INTEGER NOT NULL,"
        " laps_completed INTEGER NOT NULL DEFAULT 0, best_lap_ms INTEGER, fuel_used REAL,"
        " final_position INTEGER);"
        "CREATE TABLE laps (session_id TEXT, lap INTEGER, lap_time_ms INTEGER, complete INTEGER,"
        " fuel_start REAL, fuel_end REAL, fuel_used REAL, position INTEGER, frames INTEGER,"
        " file TEXT, recorded_at REAL, PRIMARY KEY (session_id, lap));"
    )
    db.commit()
    db.close()
    SessionStore(tmp_path).close()
    cols = {
        r[1]
        for r in sqlite3.connect(tmp_path / "index.sqlite").execute("PRAGMA table_info(sessions)")
    }
    assert "track_confidence" in cols


def test_tracks_cli_parses():
    from those_who_run.__main__ import build_parser

    p = build_parser()
    assert p.parse_args(["tracks", "list"]).tracks_command == "list"
    d = p.parse_args(["tracks", "detect", "x.jsonl"])
    assert d.tracks_command == "detect" and d.source == Path("x.jsonl")
    b = p.parse_args(["tracks", "backfill", "--force"])
    assert b.tracks_command == "backfill" and b.force
    le = p.parse_args(["tracks", "learn", "s", "--id", "837", "--name", "Fuji Short"])
    assert le.tracks_command == "learn" and le.id == 837 and le.name == "Fuji Short"
