"""The live engineer as one object (#172): run with fakes, status and stop, and
an orderly teardown when a component fails to start."""

from __future__ import annotations

import asyncio
import dataclasses
import signal
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from those_who_run.app import App
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.config import DEFAULT_RULES, Settings
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.rules import build_rules
from those_who_run.state import RaceState
from those_who_run.store import SessionStore


class FakeTelemetry:
    """Feeds ``frames``, restamped to end now, into the app's queue on start."""

    def __init__(self, app: App, frames: list[RaceState]) -> None:
        self.app, self.frames = app, frames
        self.packets = 0
        self.listening = True
        self.restarts = 0
        self.healthy = True
        self.fail_stop = False
        self.events: list[str] = []
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.events.append("start")
        self._task = asyncio.get_running_loop().create_task(self._feed())

    async def _feed(self) -> None:
        if not self.frames:
            return
        shift = time.monotonic() - self.frames[-1].t
        for f in self.frames:
            await self.app.states.put(dataclasses.replace(f, t=f.t + shift))
            self.packets += 1

    def connected(self, timeout: float) -> bool:
        return self.packets > 0

    async def stop(self) -> None:
        self.events.append("stop")
        if self._task is not None:
            self._task.cancel()
        if self.fail_stop:
            raise RuntimeError("telemetry would not stop")


class FakePlayer:
    def __init__(self, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.played: list[str] = []  # the rule of each callout spoken
        self.connected = False
        self.client: Any = None
        self.closed = False

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("discord is down")

    async def play(self, callout: Callout) -> None:
        self.played.append(callout.rule)

    async def on_phase(self, phase: Any, now: float) -> None:
        self.connected = True

    async def check_idle(self, now: float) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class FakeSpeech:
    def synthesize(self, text: str) -> Path | None:
        return None

    def release(self, clip: Path | None) -> None:
        pass


@pytest.fixture
def settings(tmp_path) -> Settings:
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"")
    return Settings(
        ps5_ip="192.0.2.1",
        discord_token="x",
        discord_channel_id=1,
        rules_file=None,
        data_dir=tmp_path / "data",
        voice_model=model,
        metrics_port=0,
        idle_disconnect_secs=600,
        telemetry_timeout_secs=3,
        log_level="INFO",
    )


def make_app(
    settings: Settings, frames: list[RaceState], player: FakePlayer, **kw: Any
) -> tuple[App, list[FakeTelemetry]]:
    made: list[FakeTelemetry] = []

    def telemetry(app: App) -> FakeTelemetry:
        made.append(FakeTelemetry(app, frames))
        return made[-1]

    app = App(
        settings,
        speech=lambda app: FakeSpeech(),
        player=lambda app: player,
        telemetry=telemetry,
        **kw,
    )
    return app, made


async def wait_for(cond, timeout: float = 5.0) -> None:
    async def poll() -> None:
        while not cond():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


async def replayed(frames: list[RaceState], tmp_path: Path) -> list[str]:
    """The rule of each callout ``replay`` says for the same frames: the live app
    must say the same (the wording varies, see phrasing)."""
    store = SessionStore(tmp_path / "replay")
    try:
        engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
        return [c.rule for c in await replay(frames, engine, ConsolePlayer())]
    finally:
        store.close()


async def test_the_app_with_fakes_says_the_expected_callouts_and_stops(settings, sim, tmp_path):
    frames = sim(total_laps=3).menu().at_track().race([90000, 89000, 88500]).frames
    expected = await replayed(frames, tmp_path)
    assert expected  # the race says something
    player = FakePlayer()
    app, made = make_app(settings, frames, player)
    running = asyncio.create_task(app.run())
    await wait_for(lambda: len(player.played) >= len(expected))
    status = app.status()
    assert status["ok"] and status["packets"] == len(frames)
    assert set(status["tasks"]) == {"ingest", "speak", "watchdog"}
    assert status["races_started"] == 1 and status["voice_connected"]
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0
    assert sorted(player.played) == sorted(expected)
    assert made[0].events == ["start", "stop"] and player.closed
    summaries = list((settings.data_dir / "sessions").glob("*/summary.json"))
    assert len(summaries) == 1  # the race was stored and closed
    assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, signal.default_int_handler)


async def test_the_app_serves_its_status_as_healthz(settings, sim):
    import json
    import urllib.request

    player = FakePlayer()
    app, _ = make_app(settings, sim().menu().frames, player)
    running = asyncio.create_task(app.run())
    await wait_for(lambda: hasattr(app, "http") and app.supervisor.ok() and app.supervisor.alive())
    url = f"http://127.0.0.1:{app.http.bound_port}/healthz"
    body = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=2).read())
    assert json.loads(body).keys() == app.status().keys()
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def test_a_start_that_raises_closes_everything_opened_so_far(settings, tmp_path):
    record = tmp_path / "frames.jsonl"
    player = FakePlayer(fail_start=True)
    app, made = make_app(settings, [], player, record=record)
    with pytest.raises(RuntimeError, match="discord is down"):
        await asyncio.wait_for(app.run(), 5)
    # the HTTP server is closed: its port no longer answers
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", app.http.bound_port), 1):
        pass
    SessionStore(settings.data_dir).close()  # the writer lock was released
    assert record.exists() and list(read_recording(record)) == []  # the recording was closed
    assert player.closed and made[0].events == ["stop"]
    assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, signal.default_int_handler)


async def test_a_component_that_cannot_be_built_leaves_the_store_closed(settings):
    def broken(app: App) -> Any:
        raise RuntimeError("no Piper")

    app = App(settings, speech=broken)
    with pytest.raises(RuntimeError, match="no Piper"):
        await app.run()
    SessionStore(settings.data_dir).close()


async def test_a_failing_closer_does_not_skip_the_rest(settings, sim):
    player = FakePlayer()
    app, made = make_app(settings, sim().menu().frames, player)
    running = asyncio.create_task(app.run())
    await wait_for(lambda: made and made[0].events == ["start"])
    made[0].fail_stop = True
    app.stop()
    with pytest.raises(RuntimeError, match="would not stop"):
        await asyncio.wait_for(running, 5)
    assert player.closed
    SessionStore(settings.data_dir).close()


async def test_a_task_that_cannot_be_kept_running_exits_non_zero(settings, sim):
    player = FakePlayer()
    app, _ = make_app(settings, sim().menu().frames, player)
    app.supervisor._max_restarts = 0

    async def broken_watchdog() -> None:
        raise RuntimeError("bug")

    app._watchdog = broken_watchdog  # type: ignore[method-assign]
    assert await asyncio.wait_for(app.run(), 5) == 1


# the awaitable queue (R4)


def held(text: str, created_at: float, hold: float, priority: int = 10) -> Callout:
    return Callout(text=text, priority=priority, rule="test", created_at=created_at, hold=hold)


async def test_get_wakes_on_a_push():
    queue = CalloutQueue(max_age=None)
    waiting = asyncio.create_task(queue.get())
    await asyncio.sleep(0.02)
    assert not waiting.done()
    queue.push(held("Box this lap.", time.monotonic(), 0.0))
    assert (await asyncio.wait_for(waiting, 1)).text == "Box this lap."


async def test_get_returns_a_held_callout_when_it_falls_due_with_no_push():
    queue = CalloutQueue(max_age=None)
    start = time.monotonic()
    queue.push(held("P3.", start, 0.2))
    c = await asyncio.wait_for(queue.get(), 2)
    assert c.text == "P3." and time.monotonic() - start >= 0.2


async def test_get_speaks_a_due_callout_before_a_held_one():
    queue = CalloutQueue(max_age=None)
    now = time.monotonic()
    queue.push(held("P3.", now, 0.2, priority=1))
    queue.push(held("Last lap.", now, 0.0, priority=5))
    assert (await asyncio.wait_for(queue.get(), 1)).text == "Last lap."
    assert (await asyncio.wait_for(queue.get(), 1)).text == "P3."


async def test_get_skips_a_held_callout_taken_back():
    queue = CalloutQueue(max_age=None)
    now = time.monotonic()
    queue.push(held("P3.", now, 0.1))
    waiting = asyncio.create_task(queue.get())
    await asyncio.sleep(0.02)
    queue.remove(lambda c: c.text == "P3.")
    await asyncio.sleep(0.15)
    assert not waiting.done()
    queue.push(held("Fuel is fine.", time.monotonic(), 0.0))
    assert (await asyncio.wait_for(waiting, 1)).text == "Fuel is fine."
