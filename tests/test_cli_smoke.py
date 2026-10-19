"""Every command run end to end through ``main([...])`` (#168).

Each test points ``GT7_DATA_DIR`` (and ``GT7_RECORD_DIR`` where it matters) at a
temp directory, so nothing touches a real store. What needs a PS5, Discord or a
Piper voice (``run``, ``record``, ``say``, ``post``, ``replay --wav-out``) gets a
fake of the one class that talks to it; everything else is the real code.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import signal
import socket
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

import those_who_run.cli.cars as cars_command
from those_who_run.__main__ import main
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, write_recording
from those_who_run.rules import build_rules
from those_who_run.state import RaceState
from those_who_run.store import SessionStore

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(stem: str) -> Path:
    """A fixture by name, stored plain or gzipped."""
    found = sorted(FIXTURES.glob(stem + ".jsonl*"))
    assert found, f"no fixture {stem}"
    return found[0]


SUZUKA = "real-nuc-suzuka-east-2026-10-15"  # 60 KB, a confirmed track and full laps


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("GT7_DATA_DIR", str(d))
    voice = tmp_path / "voice.onnx"  # checked for at startup; the fakes never load it
    voice.write_bytes(b"")
    monkeypatch.setenv("GT7_VOICE_MODEL", str(voice))
    for name in (
        "GT7_RECORD_DIR",
        "GT7_RULES_FILE",
        "GT7_PS5_IP",
        "DISCORD_BOT_TOKEN",
        "DISCORD_VOICE_CHANNEL_ID",
        "DISCORD_RESULTS_CHANNEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    return d


def store_session(data_dir: Path, frames: list[RaceState], at: float | None = None) -> str:
    """Drive frames into a store at ``data_dir``, the drive starting at wall-clock
    time ``at`` (now by default), and return the newest session id."""
    start = time.time() if at is None else at
    clock = [start]
    store = SessionStore(data_dir, clock=lambda: clock[0])
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    for f in frames:
        clock[0] = start + f.t - frames[0].t
        engine.process(f)
    if store.session is not None and engine.prev is not None:
        store.end_session(engine.prev)
    store.close()
    return sorted(p.name for p in (data_dir / "sessions").iterdir())[-1]


# offline commands


def test_replay(data_dir, capsys):
    assert main(["replay", str(fixture(SUZUKA))]) == 0
    assert "(race_summary) " in capsys.readouterr().out


def test_replay_wav_out_and_realtime(data_dir, tmp_path, monkeypatch):
    class FakeSpeech:
        def __init__(self, model: Path, cache: Path, cfg: dict[str, Any], **_: Any) -> None:
            self.wav = tmp_path / "one.wav"
            self.wav.write_bytes(b"RIFF")

        def synthesize(self, text: str) -> Path:
            return self.wav

        def release(self, path: Path) -> None:
            pass

    monkeypatch.setattr("those_who_run.speech.PiperSpeech", FakeSpeech)
    frames = list(read_recording(fixture(SUZUKA)))
    # Realtime sleeps out the gaps: squeeze the recording into a fraction of a second.
    t0 = frames[0].t
    quick = [dataclasses.replace(f, t=t0 + i * 0.0005) for i, f in enumerate(frames)]
    short = tmp_path / "short.jsonl"
    write_recording(short, quick)
    out = tmp_path / "wavs"
    assert main(["replay", str(short), "--wav-out", str(out), "--realtime"]) == 0
    wavs = sorted(out.glob("*.wav"))
    assert wavs and wavs[0].name.startswith("001-")


def test_thin(data_dir, tmp_path, capsys):
    out = tmp_path / "thin.jsonl.gz"
    assert main(["thin", str(fixture(SUZUKA)), str(out), "--every", "5", "--end", "60"]) == 0
    kept = list(read_recording(out))
    assert len(kept) > 0 and kept[-1].t - kept[0].t <= 60
    assert f"{len(kept)} of " in capsys.readouterr().out


def test_tracks_list(data_dir, capsys):
    assert main(["tracks", "list"]) == 0
    assert "Suzuka Circuit East Course" in capsys.readouterr().out


def test_tracks_detect_a_recording_and_a_session(data_dir, capsys):
    assert main(["tracks", "detect", str(fixture(SUZUKA))]) == 0
    assert "result: confirmed Suzuka Circuit East Course (442)" in capsys.readouterr().out
    sid = store_session(data_dir, list(read_recording(fixture(SUZUKA))))
    assert main(["tracks", "detect", str(data_dir / "sessions" / sid)]) == 0
    assert "Suzuka Circuit East Course" in capsys.readouterr().out


def test_tracks_detect_refuses_other_files(data_dir, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hi")
    assert main(["tracks", "detect", str(other)]) == 2


def test_tracks_learn(data_dir, capsys):
    assert main(["tracks", "learn", str(fixture(SUZUKA)), "--id", "442", "--name", "X"]) == 0
    out = capsys.readouterr().out
    assert "completed lap" in out and "\n442,X," in out


def test_tracks_backfill(data_dir, capsys):
    store_session(data_dir, list(read_recording(fixture(SUZUKA))))
    assert main(["tracks", "backfill", "--force"]) == 0
    assert "of 1 sessions updated" in capsys.readouterr().out


def test_cars(data_dir, capsys):
    assert main(["cars", "list"]) == 0
    assert len(capsys.readouterr().out.splitlines()) > 100
    assert main(["cars", "find", "nismo", "400r"]) == 0
    assert "NISMO 400R" in capsys.readouterr().out
    assert main(["cars", "find", "no-such-car-at-all"]) == 1
    assert main(["cars", "name", "0"]) == 0
    assert capsys.readouterr().out.strip() == "none"


def test_recordings(data_dir, tmp_path, monkeypatch, capsys, sim):
    rec_dir = tmp_path / "rec"
    rec_dir.mkdir()
    for stamp in ("20261015-180000", "20261015-190000"):
        (rec_dir / f"{stamp}.jsonl.gz").write_bytes(fixture(SUZUKA).read_bytes())
    monkeypatch.setenv("GT7_RECORD_DIR", str(rec_dir))
    assert main(["recordings", "--last", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "20261015-190000.jsonl.gz" and "Suzuka Circuit East Course" in out[1]
    # Explicit paths, one of them a menu-only file with no session in it.
    empty = tmp_path / "menu.jsonl"
    write_recording(empty, sim().menu().frames)
    assert main(["recordings", str(empty)]) == 0
    assert capsys.readouterr().out.splitlines()[-1].strip() == "no session"


def test_recordings_needs_a_path_or_a_record_dir(data_dir):
    assert main(["recordings"]) == 2


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, embed: Any) -> None:
        self.sent.append(embed)


class FakeClient:
    """discord.Client: logs in, hands out one text channel, closes."""

    instances: list[FakeClient] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        self.channel = FakeChannel()
        self.closed = False
        FakeClient.instances.append(self)

    async def login(self, token: str) -> None:
        self.token = token

    def get_channel(self, channel_id: int) -> FakeChannel:
        return self.channel

    async def close(self) -> None:
        self.closed = True


def test_post_dry_run_then_post(data_dir, monkeypatch, capsys):
    sid = store_session(data_dir, list(read_recording(fixture(SUZUKA))))
    assert main(["post", sid, "--dry-run"]) == 0
    assert "Suzuka Circuit East Course" in capsys.readouterr().out
    # Without the dry run it needs a token and a channel ...
    assert main(["post", sid]) == 2
    # ... and then posts the card and marks the session posted.
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_RESULTS_CHANNEL_ID", "42")
    monkeypatch.setattr("discord.Client", FakeClient)
    FakeClient.instances.clear()
    assert main(["post", sid]) == 0
    client = FakeClient.instances[-1]
    assert client.closed and len(client.channel.sent) == 1


def test_post_unknown_session_or_no_full_lap(data_dir, sim):
    assert main(["post", "20990101-000000", "--dry-run"]) == 2
    sid = store_session(data_dir, sim(total_laps=3).menu().at_track().race([], finish=True).frames)
    assert main(["post", sid, "--dry-run"]) == 1


def test_ctrl_c_is_exit_130(data_dir, monkeypatch):
    def interrupted(args: Any, settings: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cars_command, "run", interrupted)
    assert main(["cars", "list"]) == 130


# commands that talk to the PS5, Discord or Piper


class FakeTelemetry:
    """LiveTelemetry: feeds ``frames`` (restamped to now) into the queue on start."""

    frames: list[RaceState] = []
    events: list[str] = []
    then: Any = None  # called once every frame has been taken off the queue

    def __init__(self, ip: str | None, queue: asyncio.Queue, loop: Any, **_: Any) -> None:
        self.queue, self.loop = queue, loop
        self.packets = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        FakeTelemetry.events.append("telemetry start")
        self._task = self.loop.create_task(self._feed())

    async def _feed(self) -> None:
        now = time.monotonic()
        last = self.frames[-1].t
        for f in self.frames:
            await self.queue.put(dataclasses.replace(f, t=now - last + f.t))
            self.packets += 1
        while not self.queue.empty():
            await asyncio.sleep(0.01)
        if FakeTelemetry.then is not None:
            await FakeTelemetry.then()

    def connected(self, timeout: float) -> bool:
        return self.packets > 0

    async def stop(self) -> None:
        FakeTelemetry.events.append("telemetry stop")
        if self._task is not None:
            self._task.cancel()


class FakePlayer:
    """DiscordPlayer: joins on the first frame at the track, records what it plays."""

    instance: FakePlayer | None = None

    def __init__(self, token: str, channel_id: int, speech: Any, **_: Any) -> None:
        self.client = FakeClient()
        self.connected = False
        self.played: list[str] = []
        FakePlayer.instance = self

    async def start(self) -> None:
        FakeTelemetry.events.append("player start")

    async def on_phase(self, phase: Any, now: float) -> None:
        self.connected = self.connected or self.join

    async def connect(self, now: float | None = None) -> bool:
        self.connected = self.join
        return self.connected

    async def check_idle(self, now: float) -> None:
        pass

    join = True

    async def play(self, callout: Any) -> None:
        self.played.append(callout.text)

    async def close(self) -> None:
        FakeTelemetry.events.append("player close")


class FakeSpeech:
    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def synthesize(self, text: str) -> Path:
        return Path("/dev/null")

    def release(self, path: Path) -> None:
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def live(data_dir, monkeypatch):
    monkeypatch.setattr("those_who_run.telemetry.LiveTelemetry", FakeTelemetry)
    monkeypatch.setattr("those_who_run.audio.discord_player.DiscordPlayer", FakePlayer)
    monkeypatch.setattr("those_who_run.speech.PiperSpeech", FakeSpeech)
    monkeypatch.setenv("GT7_PS5_IP", "192.0.2.1")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_VOICE_CHANNEL_ID", "1")
    monkeypatch.setenv("GT7_METRICS_PORT", str(free_port()))
    FakeTelemetry.events = []
    FakeTelemetry.then = None
    FakePlayer.join = True
    return data_dir


def stop_when(done) -> Any:
    """A ``then`` for FakeTelemetry: wait for ``done()``, then SIGTERM ourselves as
    the container runtime would."""

    async def then() -> None:
        for _ in range(500):
            if done():
                break
            await asyncio.sleep(0.01)
        os.kill(os.getpid(), signal.SIGTERM)

    return then


def test_run_live_finished_race_posts_the_card_then_stops_cleanly(live, tmp_path, monkeypatch, sim):
    rec_dir = tmp_path / "rec"
    monkeypatch.setenv("GT7_RECORD_DIR", str(rec_dir))
    monkeypatch.setenv("DISCORD_RESULTS_CHANNEL_ID", "42")
    race = sim(total_laps=2).menu().at_track().race([90000, 89000])
    FakeTelemetry.frames = race.frames
    FakeTelemetry.then = stop_when(
        lambda: FakePlayer.instance is not None and FakePlayer.instance.client.channel.sent
    )
    assert main(["run"]) == 0
    player = FakePlayer.instance
    assert player is not None and len(player.client.channel.sent) == 1
    assert player.played, FakeTelemetry.events
    # Telemetry stops first, so no frame arrives once the session is being closed;
    # the player goes last, after the card and the recording are written.
    assert FakeTelemetry.events == [
        "player start",
        "telemetry start",
        "telemetry stop",
        "player close",
    ]
    assert len(list(rec_dir.glob("*.jsonl.gz"))) == 1
    summaries = list((live / "sessions").glob("*/summary.json"))
    assert len(summaries) == 1
    with closing(sqlite3.connect(live / "index.sqlite")) as db:
        posted = db.execute("SELECT count(*) FROM sessions WHERE posted_at IS NOT NULL")
        assert posted.fetchone() == (1,)


def test_run_live_closes_a_session_cut_short(live, tmp_path, sim):
    """Stopped mid-race with ``--record``: the session is closed and the file written."""
    out = tmp_path / "frames.jsonl"
    race = sim(total_laps=5).menu().at_track().race([90000], finish=False)
    FakeTelemetry.frames = race.frames
    FakeTelemetry.then = stop_when(lambda: True)
    assert main(["run", "--record", str(out)]) == 0
    assert len(list(read_recording(out))) == len(race.frames)
    summaries = list((live / "sessions").glob("*/summary.json"))
    assert len(summaries) == 1 and not json.loads(summaries[0].read_text())["finished"]


def test_run_needs_the_ps5_and_discord(data_dir):
    assert main(["run"]) == 2


def test_record(live, tmp_path, sim):
    out = tmp_path / "rec.jsonl.gz"
    FakeTelemetry.frames = sim(total_laps=2).menu().at_track().race([90000, 89000]).frames
    assert main(["record", str(out), "--seconds", "0.2"]) == 0
    assert len(list(read_recording(out))) == len(FakeTelemetry.frames)
    assert FakeTelemetry.events == ["telemetry start", "telemetry stop"]


def test_say(live, capsys):
    assert main(["say", "radio check"]) == 0
    assert FakePlayer.instance is not None and FakePlayer.instance.played == ["radio check"]
    FakePlayer.join = False
    assert main(["say"]) == 1
    assert FakeTelemetry.events[-1] == "player close"


def test_say_needs_discord(data_dir):
    assert main(["say"]) == 2
