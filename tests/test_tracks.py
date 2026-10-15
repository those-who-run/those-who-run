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
)
from those_who_run.tracks import Track, load_tracks, track_by_id, track_name
from those_who_run.tracktools import backfill, detect_recording, detect_session

FIXTURE = Path(__file__).parent / "fixtures" / "real-n24h-race-lap1-positions-2026-10-14.jsonl"
N24H, GP, NORDSCHLEIFE, TOURIST = 348, 349, 95, 347


# the table


def test_table_loads_with_names_and_geometry():
    tracks = load_tracks()
    assert len(tracks) == 106
    assert sum(t.has_geometry for t in tracks) == 103
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


# synthetic layouts: a family sharing a finish line, its reverse twin, and a huge
# unrelated box like Special Stage Route X


def _tracks() -> tuple[Track, ...]:
    line = ((100.0, 0.0), (100.0, 60.0))  # crossed moving +x
    return (
        Track(1, "Full", "PX", line, (0, 0, 2000, 1000)),
        Track(2, "Short", "PX", line, (0, 0, 1000, 1000)),
        Track(3, "Full Reverse", "NX", line, (0, 0, 2000, 1000)),
        Track(
            4, "Far Away", "PX", ((4000.0, 4000.0), (4000.0, 4060.0)), (-5000, -5000, 5000, 5000)
        ),
    )


def _drive(det: TrackDetector, points: list[tuple[float, float]]) -> list:
    changes = []
    for x, z in points:
        m = det.observe_point(x, z)
        if m is not None:
            changes.append(m)
    return changes


def _straight(x0: float, x1: float, z: float, step: float = 10.0) -> list[tuple[float, float]]:
    n = int(abs(x1 - x0) / step)
    sign = 1 if x1 >= x0 else -1
    return [(x0 + sign * i * step, z) for i in range(n + 1)]


def test_family_narrows_by_bounds_then_line_direction():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)
    # On the grid, 40 m past the line: three layouts share it; Far Away's line is 5 km off.
    first = det.observe_point(140, 30)
    assert first is not None and first.confidence == "ambiguous"
    assert first.candidate_ids == (2, 1, 3) or set(first.candidate_ids) == {1, 2, 3}
    # Drive 1.5 km east along z=30: Short's box ends at x=1000.
    _drive(det, _straight(150, 1500, 30))
    m = det.match
    assert m.confidence == "ambiguous" and set(m.candidate_ids) == {1, 3}
    assert m.track_id in (1, 3)
    # Loop back west at z=500 (no line there), then south and east across the line at x=100.
    _drive(det, _straight(1500, 50, 500))
    _drive(det, [(50, 400), (50, 300), (50, 200), (50, 100), (50, 30)])
    changes = _drive(det, _straight(50, 200, 30))
    assert det.match.confidence == "confirmed"
    assert det.match.track_id == 1 and det.match.name == "Full"
    assert changes and changes[-1].evidence.startswith("finish line crossed")
    # The reverse twin was never crossed in its direction, so it is not even a candidate.
    assert [c.track.id for c in det.match.candidates if c.line_crossed] == [1]


def test_only_layout_near_the_start_becomes_probable_after_some_driving():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)
    # Start just inside Full's box but 1.2 km east of the line: only Full and Reverse fit by
    # box; both are too far for the start filter, so the pool falls back to every survivor.
    _drive(det, _straight(1300, 1600, 30))
    m = det.match
    assert m.confidence == "ambiguous" and set(m.candidate_ids) == {1, 3, 4}

    det = TrackDetector(
        (_tracks()[0], _tracks()[3]), box_tolerance_m=20, start_radius_m=500, min_distance_m=300
    )
    _drive(det, _straight(140, 300, 30))
    assert det.match.confidence == "ambiguous"  # unique, but has barely moved
    _drive(det, _straight(300, 600, 30))
    assert det.match.confidence == "probable" and det.match.track_id == 1
    assert "only layout" in det.match.evidence


def test_teleport_is_not_a_line_crossing_and_leaving_every_box_gives_none():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, teleport_m=100)
    det.observe_point(140, 30)
    det.observe_point(150, 30)
    # Return to pits: jump from one side of the line to the other.
    det.observe_point(50, 30)
    assert det.match.confidence == "ambiguous"
    assert not any(c.line_crossed for c in det.match.candidates)
    assert det.distance_m == pytest.approx(10)
    # Drive off every table box.
    _drive(det, _straight(50, 7000, 30, step=50))
    assert det.match.confidence == "none" and det.match.track_id is None


def test_dominant_fit_breaks_a_shared_line():
    # Two layouts share the line and the car stays inside both; the box that fits the lap
    # clearly better wins once the line is crossed.
    tracks = (
        Track(1, "Tight", "PX", ((100.0, 0.0), (100.0, 60.0)), (0, 0, 600, 600)),
        Track(2, "Loose", "PX", ((100.0, 0.0), (100.0, 60.0)), (0, 0, 2000, 2000)),
    )
    det = TrackDetector(tracks, box_tolerance_m=20, start_radius_m=500)
    _drive(det, _straight(140, 550, 30))
    _drive(det, [(550, 300), (550, 550), (50, 550), (50, 30)])
    _drive(det, _straight(50, 200, 30))
    m = det.match
    assert m.confidence == "confirmed" and m.track_id == 1
    assert "next best Loose" in m.evidence


def test_menu_or_loading_frame_starts_over_but_a_pause_does_not():
    det = TrackDetector(_tracks(), box_tolerance_m=20, start_radius_m=500, min_distance_m=300)

    def frame(phase: Phase, x: float, z: float):
        return make_state(phase=phase, current_lap=1, track_id=None, pos_x=x, pos_z=z)

    for x in range(140, 700, 10):
        det.observe(frame(Phase.IN_RACE, x, 30))
    assert det.distance_m > 500
    det.observe(frame(Phase.PAUSED, 700, 30))
    det.observe(frame(Phase.IN_RACE, 700, 30))
    assert det.distance_m > 500  # pause kept everything
    det.observe(frame(Phase.LOADING, 0, 0))
    det.observe(frame(Phase.AT_TRACK, 140, 30))
    assert det.distance_m == 0  # new venue: start over


# the real thing: Nürburgring 24h race, 2026-10-14, from the pre-race screen to lap 2


def test_real_n24h_race_is_confirmed_before_the_lights():
    final, steps = detect_recording(FIXTURE)
    assert final.track_id == N24H and final.confidence == "confirmed"
    assert "finish line crossed" in final.evidence
    race_start = next(s.t for s in read_recording(FIXTURE) if s.phase is Phase.IN_RACE)
    confirmed = next(s for s in steps if s.match.confidence == "confirmed")
    assert confirmed.lap == 0 and confirmed.t < race_start  # the rolling start crosses the line
    assert confirmed.match.candidate_ids == (N24H,)
    # On the way there the GP layout and both Nordschleife layouts were live candidates.
    seen = {tid for s in steps for tid in s.match.candidate_ids}
    assert {GP, NORDSCHLEIFE, TOURIST} <= seen
    assert final.candidates[0].fit > 0.2  # still only lap 1 + 20 s of lap 2


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
