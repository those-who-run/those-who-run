"""The outing archive and full-rate cuts (#197)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from tests.archive import archived_outing
from those_who_run import archive
from those_who_run.__main__ import main
from those_who_run.replay import Window, read_recording, thin, write_recording


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("GT7_RECORD_DIR", "GT7_RULES_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GT7_ARCHIVE_DIR", str(tmp_path / "archive"))
    return tmp_path


def outing(directory: Path, oid: str, sim, plain: bool = False) -> Path:
    """A two-lap race recorded as the engineer names outings."""
    frames = sim(total_laps=2).menu().at_track().race([90000, 89000]).frames
    path = directory / f"{oid}.jsonl{'' if plain else '.gz'}"
    directory.mkdir(parents=True, exist_ok=True)
    write_recording(path, frames)
    return path


# archiving


def test_archive_an_outing_then_list_it(env, sim, capsys):
    src = outing(env / "rec", "20261018-101500", sim)
    assert main(["recordings", "archive", str(src), "--note", "two laps", "--issue", "15"]) == 0
    assert "archived 20261018-101500" in capsys.readouterr().out
    copied = env / "archive" / "20261018-101500.jsonl.gz"
    assert copied.read_bytes() == src.read_bytes()
    side = json.loads((env / "archive" / "20261018-101500.json").read_text())
    assert side["note"] == "two laps" and side["issues"] == [15]
    assert side["kinds"][0].startswith("lap_race (") and side["date"] == "2026-10-18"
    assert side["frames"] == len(list(read_recording(src)))
    assert len(side["sessions"]) == 1 and "2-lap race" in side["sessions"][0]

    assert main(["recordings", "archive"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("20261018-101500  ") and out[0].endswith("#15")
    assert out[1].strip() == "two laps"


def test_archive_by_id_from_the_record_dir_and_again(env, sim, monkeypatch, capsys):
    outing(env / "rec", "20261018-101500", sim)
    monkeypatch.setenv("GT7_RECORD_DIR", str(env / "rec"))
    assert (
        main(["recordings", "archive", "20261018-101500", "--note", "first", "--issue", "15"]) == 0
    )
    # Again: the issues add up, the note stays unless a new one is given.
    assert main(["recordings", "archive", "20261018-101500", "--issue", "16"]) == 0
    (entry,) = archive.list_archive(env / "archive")
    assert entry.note == "first" and entry.issues == [15, 16]


def test_a_plain_recording_is_archived_gzipped(env, sim):
    src = outing(env / "rec", "20261018-101500", sim, plain=True)
    entry = archive.archive_outing(src, env / "archive", note="plain")
    assert entry.file == "20261018-101500.jsonl.gz"
    assert list(read_recording(env / "archive" / entry.file)) == list(read_recording(src))


def test_archive_refuses_what_is_not_an_outing(env, sim, tmp_path):
    assert main(["recordings", "archive", "20990101-000000"]) == 2  # nowhere to be found
    other = outing(tmp_path, "my-drive", sim)
    assert main(["recordings", "archive", str(other)]) == 2  # not a recorder name


def test_an_empty_archive(env, capsys):
    assert main(["recordings", "archive"]) == 0
    assert "nothing archived" in capsys.readouterr().out


def test_the_default_archive_dir():
    assert archive.archive_dir({"GT7_ARCHIVE_DIR": "/x"}) == Path("/x")
    assert archive.archive_dir({}).parts[-2:] == ("those-who-run", "outings")


# fetching


def test_fetch_a_local_outing_and_check_its_sha(env, sim):
    entry = archive.archive_outing(outing(env / "rec", "20261018-101500", sim), env / "archive")
    path, why = archive.fetch(entry.id, env / "archive")
    assert path == env / "archive" / entry.file and why == ""
    assert archived_outing(entry.id) == path
    path.write_bytes(b"not the outing")
    assert archive.fetch(entry.id, env / "archive") == (
        None,
        f"{path} does not match the sha256 in its sidecar",
    )


def test_fetch_downloads_from_the_release(env, sim, monkeypatch):
    src = outing(env / "rec", "20261018-101500", sim)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        dest = Path(cmd[cmd.index("-D") + 1])
        (dest / src.name).write_bytes(src.read_bytes())
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(archive.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(archive.subprocess, "run", fake_run)
    path, _ = archive.fetch("20261018-101500", env / "fetched", repo="o/r")
    assert path is not None and path.read_bytes() == src.read_bytes()
    assert calls[0][:4] == ["/usr/bin/gh", "release", "download", "outings"]
    assert calls[0][-2:] == ["-R", "o/r"]
    archive.fetch("20261018-101501", env / "fetched")
    assert calls[1][-2:] == ["-R", "those-who-run/outings"]


def test_fetch_says_why_an_outing_is_not_there(env, monkeypatch):
    assert archive.fetch("nope", env / "archive")[1] == "'nope' is not an outing id"
    monkeypatch.setattr(archive.shutil, "which", lambda name: None)
    assert "no gh" in archive.fetch("20261018-101500", env / "archive")[1]
    with pytest.raises(pytest.skip.Exception, match="archived outing 20261018-101500: .*no gh"):
        archived_outing("20261018-101500")

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "release not found")

    monkeypatch.setattr(archive.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(archive.subprocess, "run", failing)
    assert archive.fetch("20261018-101500", env / "archive") == (
        None,
        "gh release download failed: release not found",
    )

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 600)

    monkeypatch.setattr(archive.subprocess, "run", timeout)
    assert "timed out" in archive.fetch("20261018-101500", env / "archive")[1]


# full-rate cuts


def sixty_hz(sim, seconds: float = 60.0):
    """A 60 Hz stretch of one lap: nothing tracked changes, so plain thinning
    keeps about two frames a second."""
    base = sim(total_laps=3).menu().at_track().race([], finish=False).frames[-1]
    return [
        dataclasses.replace(base, t=i / 60, packet_id=i, current_lap=1 + int(i / 60 // 20))
        for i in range(int(seconds * 60))
    ]


def test_thin_window_keeps_every_frame_inside_it(sim):
    frames = sixty_hz(sim)
    plain = list(thin(frames))
    assert len(plain) < 200
    cut = list(thin(frames, windows=[Window.parse("10:20")]))
    inside = [f for f in frames if 10 <= f.t <= 20]
    assert [f for f in cut if 10 <= f.t <= 20] == inside and len(inside) == 601
    outside = [f for f in cut if not 10 <= f.t <= 20]
    assert len(outside) < len(plain)


def test_thin_window_in_laps(sim):
    frames = sixty_hz(sim)  # lap 1 for 20 s, lap 2 for 20 s, lap 3 for 20 s
    cut = list(thin(frames, windows=[Window.parse("lap2:lap2")]))
    assert [f for f in cut if f.current_lap == 2] == [f for f in frames if f.current_lap == 2]
    assert len([f for f in cut if f.current_lap == 3]) < 60


def test_thin_stride(sim):
    frames = sixty_hz(sim, seconds=10)
    kept = list(thin(frames, stride=6))
    assert [f.packet_id for f in kept] == list(range(0, 600, 6))


def test_window_parse():
    assert Window.parse("120:180.5") == Window(120, 180.5)
    assert Window.parse("lap3:lap5") == Window(3, 5, laps=True)
    for bad in ("120", "a:b", "180:120", "lap3:5x"):
        with pytest.raises(ValueError, match="window"):
            Window.parse(bad)


def test_thin_cli_window_and_stride(env, sim, capsys):
    src = env / "60hz.jsonl.gz"
    write_recording(src, sixty_hz(sim))
    out = env / "cut.jsonl.gz"
    assert main(["thin", str(src), str(out), "--window", "10:20", "--window", "lap3:lap3"]) == 0
    kept = list(read_recording(out))
    assert len([f for f in kept if 10 <= f.t <= 20]) == 601
    assert len([f for f in kept if f.current_lap == 3]) == 1200
    assert main(["thin", str(src), str(out), "--stride", "60"]) == 0
    assert len(list(read_recording(out))) == 60 + 2 * 2  # plus each lap change and its neighbours
    assert main(["thin", str(src), str(out), "--window", "20:10"]) == 2
