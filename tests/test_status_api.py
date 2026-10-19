"""``GET /api/v1/status`` on 9850 (#292): what the engineer is doing right now,
from real recordings fed through the live app."""

from __future__ import annotations

import asyncio
import builtins
import dataclasses
import json
import subprocess
import sys
import time
import types
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.test_app import FakePlayer, make_app, wait_for
from tests.test_pitwall_api import openapi_script
from those_who_run import __version__
from those_who_run import app as app_module
from those_who_run import status as models
from those_who_run.app import App
from those_who_run.config import Settings
from those_who_run.openapi import doc
from those_who_run.pitwall import server as pitwall
from those_who_run.replay import read_recording
from those_who_run.state import Phase, RaceState

FIXTURES = Path(__file__).parent / "fixtures"
GILLES = FIXTURES / "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz"
LAGUNA_DEMO = FIXTURES / "real-nuc-laguna-seca-demo-2026-10-18.jsonl.gz"
SUGO_REPLAY = FIXTURES / "real-nuc-sugo-replay-2026-10-18.jsonl.gz"
FEED_TIMEOUT = 0.5  # telemetry_timeout_secs where a test waits for idle


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
        bind_address="127.0.0.1",
    )


@pytest.fixture
async def http() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[App]:
    """The live app with no telemetry of its own: a test hands it frames."""
    app, _ = make_app(settings, [], FakePlayer())
    running = asyncio.create_task(app.run())
    await wait_for(lambda: app.supervisor.alive())
    yield app
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def get(http: aiohttp.ClientSession, app: App, path: str) -> tuple[str, Any]:
    async with http.get(f"http://127.0.0.1:{app.server.bound_port}{path}") as resp:
        assert resp.status == 200
        return await resp.text(), resp.headers


async def status(http: aiohttp.ClientSession, app: App) -> dict[str, Any]:
    text, _ = await get(http, app, "/api/v1/status")
    return json.loads(text)


async def feed(app: App, frames: list[RaceState]) -> None:
    for f in frames:
        await app._handle(f)


def gilles() -> tuple[list[RaceState], int]:
    """The race, and the index of a frame on lap 2 (the track confirmed on lap 1)."""
    frames = list(read_recording(GILLES, strict=True))
    lap2 = [i for i, f in enumerate(frames) if f.in_race and f.current_lap == 2]
    return frames, lap2[len(lap2) // 2]


def to_menu(last: RaceState) -> RaceState:
    return dataclasses.replace(
        last,
        t=last.t + 0.1,
        packet_id=last.packet_id + 1,
        phase=Phase.MENU,
        current_lap=-1,
        race_start_pos=-1,
        total_cars=-1,
    )


async def test_mid_race_it_says_driving_with_the_session_lap_and_position(app, http):
    # AC1
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    body = await status(http, app)
    frame = frames[mid]
    assert app.store.session is not None
    assert body["activity"] == "driving"
    assert body["version"] == __version__
    assert body["started_at"] > 1.7e9  # epoch seconds
    assert body["idle_secs"] == 0
    assert body["voice_connected"] is True
    assert body["telemetry"]["last_packet_age_s"] is not None
    assert body["session"] == {
        "id": app.store.session.session_id,
        "kind": "lap_race",
        "track": {"id": 100002, "name": "Circuit Gilles Villeneuve", "sure": True},
        "car": "Mazda RX-VISION GT3 EVO '26",
        "lap": frame.current_lap,
        "laps_total": 12,
        "position": frame.position,
        "cars": frame.total_cars,
    }
    assert frame.current_lap == 2 and frame.position is not None


async def test_paused_in_the_race(app, http):
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    last = frames[mid]
    await app._handle(
        dataclasses.replace(last, t=last.t + 0.1, packet_id=last.packet_id + 1, phase=Phase.PAUSED)
    )
    body = await status(http, app)
    assert body["activity"] == "paused"
    assert body["session"]["lap"] == last.current_lap  # from the last driving frame


async def test_after_the_race_and_the_timeout_it_is_idle_like_healthz(settings, http):
    # AC2
    settings = dataclasses.replace(settings, telemetry_timeout_secs=FEED_TIMEOUT)
    app, _ = make_app(settings, [], FakePlayer())
    running = asyncio.create_task(app.run())
    await wait_for(lambda: app.supervisor.alive())
    frames, _ = gilles()
    await feed(app, [*frames, to_menu(frames[-1])])
    assert app.store.session is None  # the race ended at the menu
    await wait_for(lambda: app.status()["idle"])
    body = await status(http, app)
    health = json.loads((await get(http, app, "/healthz"))[0])
    assert body["activity"] == "idle" and health["idle"] is True
    assert body["session"] is None
    assert body["idle_secs"] > 0 and health["idle_secs"] > 0
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def test_activity_is_idle_exactly_when_healthz_says_idle(settings):
    # R5, frame by frame through a race, its end and the wait after it
    settings = dataclasses.replace(settings, telemetry_timeout_secs=FEED_TIMEOUT)
    app, _ = make_app(settings, [], FakePlayer())
    running = asyncio.create_task(app.run())
    await wait_for(lambda: app.supervisor.alive())
    assert app.live_status().activity == "idle"  # nothing yet
    frames, _ = gilles()
    seen = set()
    for f in [*frames, to_menu(frames[-1])]:
        await app._handle(f)
        live = app.live_status().activity
        seen.add(live)
        assert (live == "idle") is app.status()["idle"]
    assert seen == {"idle", "driving"}  # idle at the track before the start
    await wait_for(lambda: app.status()["idle"])
    assert app.live_status().activity == "idle"
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def test_a_demo_race_says_demo(app, http):
    # AC3: GT7's attract-mode demo, joined part way, the flag off and the fuel flat
    await feed(app, list(read_recording(LAGUNA_DEMO, strict=True)))
    assert app.engine.replay
    body = await status(http, app)
    assert body["activity"] == "demo"
    assert body["session"] is None


async def test_a_gt7_replay_says_replay(app, http):
    await feed(app, list(read_recording(SUGO_REPLAY, strict=True)))
    assert app.engine.replay
    body = await status(http, app)
    assert body["activity"] == "replay"
    assert body["session"] is None


async def test_no_token_secret_or_id_in_the_body(tmp_path, monkeypatch, http):
    # AC4, R3
    secrets = {
        "DISCORD_BOT_TOKEN": "discord-bot-token-c0ffee",
        "GT7_DISCORD_TOKEN": "gt7-discord-token-c0ffee",
        "GT7_ADMIN_TOKEN": "admin-token-c0ffee",
        "GT7_PS5_IP": "192.0.2.123",
        "DISCORD_VOICE_CHANNEL_ID": "987654321098765432",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"")
    settings = dataclasses.replace(
        Settings.from_env(check=()),
        data_dir=tmp_path / "data",
        voice_model=model,
        metrics_port=0,
        bind_address="127.0.0.1",
    )
    assert settings.discord_token == secrets["DISCORD_BOT_TOKEN"]
    app, _ = make_app(settings, [], FakePlayer())
    running = asyncio.create_task(app.run())
    await wait_for(lambda: app.supervisor.alive())
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    text, _ = await get(http, app, "/api/v1/status")
    assert json.loads(text)["session"] is not None
    for value in secrets.values():
        assert value not in text
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0


async def test_it_is_never_cached(app, http):
    # R6
    _, headers = await get(http, app, "/api/v1/status")
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"].startswith("application/json")


async def test_it_reads_held_state_and_touches_no_file_or_database(app, monkeypatch):
    # R4: the store's index and every file are out of reach while it is built
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    app.store.wait()

    class NoIO:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"status touched the index ({name})")

    def no_open(*args: Any, **kw: Any) -> Any:
        raise AssertionError(f"status opened {args[0] if args else '?'}")

    db = app.store._db
    monkeypatch.setattr(app.store, "_db", NoIO())
    monkeypatch.setattr(builtins, "open", no_open)
    monkeypatch.setattr(Path, "open", no_open)
    try:
        assert app.live_status().session is not None
    finally:
        monkeypatch.setattr(app.store, "_db", db)  # the teardown closes it
        monkeypatch.undo()


async def test_a_position_or_field_of_0_or_minus_1_is_null(app, http):
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    last = frames[mid]
    for n, (pos, cars) in enumerate([(0, 0), (-1, -1)], start=1):
        frame = dataclasses.replace(
            last,
            t=last.t + 0.02 * n,
            packet_id=last.packet_id + n,
            race_start_pos=pos,
            total_cars=cars,
        )
        await app._handle(frame)
        session = (await status(http, app))["session"]
        assert session["position"] is None and session["cars"] is None
    assert session["lap"] == last.current_lap  # the rest of the session as it was


# R2, AC5: the schema


def test_the_schema_has_the_route_and_goes_stale_with_the_model(monkeypatch):
    committed = json.loads(openapi_script.OUT.read_text())
    op = committed["paths"]["/api/engine/status"]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EngineStatus"
    }
    assert set(committed["components"]["schemas"]["EngineStatus"]["properties"]) == {
        f.name for f in dataclasses.fields(models.EngineStatus)
    }
    assert openapi_script.main(["--check"]) == 0

    @dataclasses.dataclass(frozen=True, slots=True)
    class EngineStatus(models.EngineStatus):
        fuel: float = doc("A field added without running make openapi")

    route = dataclasses.replace(models.ROUTES[0], response=EngineStatus)
    monkeypatch.setattr(models, "ROUTES", (route,))
    assert openapi_script.main(["--check"]) == 1


def test_the_pit_wall_reads_the_models_without_the_engineer():
    """The schema imports ``status``: none of the engineer's runtime comes with it."""
    code = (
        "import sys; from those_who_run import openapi; openapi.spec();"
        "print(' '.join(sorted(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    loaded = set(out.stdout.split())
    assert "those_who_run.status" in loaded
    for heavy in ("those_who_run.engine", "those_who_run.app", "those_who_run.metrics", "discord"):
        assert heavy not in loaded


# AC6: behind the pit wall


async def test_the_pit_wall_forwards_the_same_body(app, http, tmp_path, monkeypatch):
    frames, mid = gilles()
    await feed(app, frames[: mid + 1])
    # Hold the engineer's clock, so both reads give the same ages
    now = time.monotonic()
    monkeypatch.setattr(
        app_module, "time", types.SimpleNamespace(monotonic=lambda: now, time=time.time)
    )
    direct, headers = await get(http, app, "/api/v1/status")
    wall = TestClient(
        TestServer(
            pitwall.make_app(tmp_path, engineer_url=f"http://127.0.0.1:{app.server.bound_port}")
        )
    )
    await wall.start_server()
    try:
        resp = await wall.get("/api/engine/status")
        assert resp.status == 200
        assert json.loads(await resp.text()) == json.loads(direct)
        assert json.loads(direct)["session"]["track"]["name"] == "Circuit Gilles Villeneuve"
        assert resp.headers["Cache-Control"] == headers["Cache-Control"] == "no-store"
    finally:
        await wall.close()
