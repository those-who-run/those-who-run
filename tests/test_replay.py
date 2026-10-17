import gzip

from tests.conftest import make_state
from those_who_run.replay import (
    OutingRecorder,
    RecordingWriter,
    read_recording,
    thin,
    write_recording,
)
from those_who_run.state import Phase


def test_gzip_recording_roundtrip(tmp_path, sim):
    frames = sim(total_laps=2).menu().race([100000, 100000]).frames
    path = tmp_path / "race.jsonl.gz"
    assert write_recording(path, frames) == len(frames)
    with gzip.open(path) as fh:
        assert fh.read(1) == b"{"
    assert list(read_recording(path, strict=True)) == frames
    w = RecordingWriter(path)  # append keeps the file readable
    w.write(frames[0])
    w.close()
    assert list(read_recording(path, strict=True)) == [*frames, frames[0]]


def _trace():
    # 10 s at 10 Hz, lap 1 -> 2 at t=5.0, a position change at t=8.0
    out = []
    for i in range(100):
        t = i / 10
        out.append(
            make_state(
                t=t,
                packet_id=i,
                current_lap=1 if t < 5.0 else 2,
                race_start_pos=5 if t < 8.0 else 4,
                speed_kph=100.0 + i,
            )
        )
    return out


def test_thin_keeps_transitions_their_neighbours_and_a_regular_sample():
    kept = [round(s.t, 1) for s in thin(_trace(), every=1.0)]
    assert kept == [0.0, 1.0, 2.0, 3.0, 4.0, 4.9, 5.0, 5.1, 6.1, 7.1, 7.9, 8.0, 8.1, 9.1]


def test_thin_ignores_fields_that_are_not_tracked():
    # speed changes every frame; only the sample rate keeps frames
    kept = list(thin(_trace()[:40], every=2.0))
    assert [round(s.t, 1) for s in kept] == [0.0, 2.0]


def test_thin_window():
    kept = [round(s.t, 1) for s in thin(_trace(), every=1.0, start=4.5, end=6.0)]
    assert kept == [4.5, 4.9, 5.0, 5.1]  # the next sample would be 6.1, past the end


def test_outing_recorder_one_file_per_outing_with_pruning(tmp_path):
    clock = [1_000_000.0]
    rec = OutingRecorder(tmp_path / "rec", keep=2, clock=lambda: clock[0])
    menu = make_state(t=0.0, current_lap=-1, phase=Phase.MENU)
    rec.write(menu)
    assert not (tmp_path / "rec").exists(), "menus are not recorded"

    def outing(t0):
        rec.write(make_state(t=t0, current_lap=0, phase=Phase.AT_TRACK))
        rec.write(make_state(t=t0 + 1, current_lap=1))
        rec.write(make_state(t=t0 + 2, current_lap=-1, phase=Phase.MENU))
        clock[0] += 3600

    outing(10.0)
    (first,) = sorted((tmp_path / "rec").glob("*.jsonl.gz"))
    frames = list(read_recording(first, strict=True))
    assert [f.phase for f in frames] == [Phase.MENU, Phase.AT_TRACK, Phase.IN_RACE, Phase.MENU]
    assert frames[0] == menu, "the last menu frame opens the file"
    outing(20.0)
    outing(30.0)
    names = sorted(p.name for p in (tmp_path / "rec").glob("*.jsonl.gz"))
    assert len(names) == 2 and first.name not in names, "oldest pruned beyond keep"
    assert rec.outings == 3 and rec.count == 12
    rec.close()  # idempotent when nothing is open
