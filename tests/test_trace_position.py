"""The lap trace carries the car's position (#349), for the track map (#350).

The Circuit Gilles Villeneuve race of 2026-10-17 (outing ``20261017-162118``):
#117 measured its lap at 4,310 m from 60 Hz frames, and its pit stop on lap 6
jumps the car 120.8 m in one frame as the cut-scene starts.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import pytest

from tests.archive import archived_outing
from tests.test_pitwall import drive
from those_who_run.pitwall import data
from those_who_run.pitwall.api_models import Trace
from those_who_run.pitwall.server import encode
from those_who_run.replay import read_recording

FIXTURES = Path(__file__).parent / "fixtures"
LAP_METRES = 4310.0  # #117's evidence
JUMP = 120.8  # lap 6's cut-scene, in the pit lane


def steps(tr: Trace) -> list[float]:
    xz = list(zip(tr.x, tr.z, strict=True))
    return [math.dist(a, b) for a, b in zip(xz, xz[1:], strict=False)]


def jumps(tr: Trace) -> list[float]:
    """Steps over 20 m that the trace's own time and speed can't explain: two
    frames side by side, a cut-scene apart. A thinned trace's other steps are
    long too (a stretch can be a second of a straight), but take their time."""
    out = []
    for i, step in enumerate(steps(tr)):
        reach = 2 / 3.6 * max(tr.speed_kph[i], tr.speed_kph[i + 1]) * (tr.t[i + 1] - tr.t[i])
        if step > max(data.JUMP_METRES, reach):
            out.append(round(step, 1))
    return out


@pytest.fixture(scope="module")
def race(tmp_path_factory) -> tuple[Path, str]:
    """The whole race at 60 Hz, stored as the engineer stores it."""
    store = tmp_path_factory.mktemp("gilles")
    drive(store, list(read_recording(archived_outing("20261017-162118"), strict=True)))
    (session,) = data.list_sessions(store)
    return store, session.session_id


@pytest.fixture(scope="module")
def pit_fixture(tmp_path_factory) -> tuple[Path, str]:
    """Laps 5 to 8 of the same race, thinned to 2 Hz."""
    store = tmp_path_factory.mktemp("gilles-pit")
    drive(
        store,
        list(read_recording(FIXTURES / "real-nuc-gilles-villeneuve-pit-stop-2026-10-17.jsonl.gz")),
    )
    (session,) = data.list_sessions(store)
    return store, session.session_id


def test_a_clean_lap_traces_the_whole_track(race):
    """AC1: x and z beside every t, and a clean lap's steps add up to the lap."""
    store, sid = race
    clean = [
        r for r in data.lap_summaries(store, sid) if not r.invalid and not r.pit and not r.out_lap
    ]
    assert len(clean) >= 9
    for row in clean:
        tr = data.lap_trace(store, sid, row.lap)
        assert tr is not None
        assert len(tr.x) == len(tr.z) == len(tr.t)
        assert 1400 <= len(tr) <= 1500
        assert sum(steps(tr)) == pytest.approx(LAP_METRES, rel=0.02), row.lap
        assert jumps(tr) == []


def test_the_position_adds_under_a_third_to_the_body(race):
    """R4: two more columns at a tenth of a metre grow a 1,500-point lap's JSON
    by about 29% (gzipped, about 34%)."""
    store, sid = race
    tr = data.lap_trace(store, sid, 2)
    assert tr is not None
    without = {k: v for k, v in dataclasses.asdict(tr).items() if k not in ("x", "z")}
    assert len(encode(tr)) / len(encode(without)) < 1.30


def test_the_pit_lap_keeps_both_frames_around_its_jump(race):
    """AC2: lap 6's cut-scene survives thinning as one 120.8 m step between the
    frames either side of it, at the default and at a phone's point count."""
    store, sid = race
    for points in (1500, 400, 100):
        tr = data.lap_trace(store, sid, 6, max_points=points)
        assert tr is not None
        assert jumps(tr) == [pytest.approx(JUMP, abs=0.15)], points
        # The jump's two frames are the only ones over the count.
        assert len(tr) <= points + 2


def test_a_sparse_recording_jumps_only_at_the_cut_scene(pit_fixture):
    """At 2 Hz a fast car covers 20 to 47 m between frames, which its speed
    explains: thinning keeps the cut-scene's frames and no others."""
    store, sid = pit_fixture
    full = data.lap_trace(store, sid, 6)
    assert full is not None
    assert max(steps(full)) == pytest.approx(JUMP, abs=0.15)
    thin = data.lap_trace(store, sid, 6, max_points=40)
    assert thin is not None and len(thin) <= 42
    # Its 0.5 s gaps count as 0.1 s on the time axis, so here the jump is the
    # one long step between frames a few hundredths of a second apart.
    quick = [round(s, 1) for i, s in enumerate(steps(thin)) if thin.t[i + 1] - thin.t[i] < 0.05]
    assert [s for s in quick if s > data.JUMP_METRES] == [pytest.approx(JUMP, abs=0.15)]
    clean = data.lap_trace(store, sid, 8)
    assert clean is not None and len(data.lap_trace(store, sid, 8, max_points=40) or ()) <= 40
    assert sum(steps(clean)) == pytest.approx(LAP_METRES, rel=0.02)
