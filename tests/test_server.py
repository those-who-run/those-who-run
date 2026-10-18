"""The engineer's aiohttp server (#173): /metrics, /healthz, errors, the /api/v1
room with a WebSocket, the control port, and no CORS."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families

from tests.test_app import FakePlayer, FakeSpeech, FakeTelemetry, wait_for
from those_who_run.app import App
from those_who_run.metrics import Metrics
from those_who_run.server import Server


@pytest.fixture
async def http() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


def server(health: Any = None, **kw: Any) -> Server:
    metrics = Metrics()
    metrics.in_race.set(1)
    return Server(
        metrics,
        health or (lambda: {"ok": True, "telemetry_connected": False}),
        host="127.0.0.1",
        port=0,
        **kw,
    )


def url(srv: Server, path: str, control: bool = False) -> str:
    port = srv.bound_control_port if control else srv.bound_port
    return f"http://127.0.0.1:{port}{path}"


async def test_metrics_scrape_as_prometheus_reads_it(http):
    srv = server()
    await srv.start()
    try:
        async with http.get(url(srv, "/metrics")) as r:
            assert r.status == 200 and r.headers["Content-Type"] == CONTENT_TYPE_LATEST
            families = {f.name: f for f in text_string_to_metric_families(await r.text())}
        assert families["gt7_in_race"].samples[0].value == 1.0
        assert "gt7_callouts_dropped" in families  # a counter, named without _total
    finally:
        await srv.stop()


async def test_healthz_is_the_health_body_and_503_when_not_ok(http):
    state = {"ok": True, "telemetry_connected": False}
    srv = server(lambda: state)
    await srv.start()
    try:
        async with http.get(url(srv, "/healthz")) as r:
            assert r.status == 200 and await r.json() == state
            assert r.content_type == "application/json"
        state["ok"] = False
        async with http.get(url(srv, "/healthz")) as r:
            assert r.status == 503 and (await r.json())["ok"] is False
    finally:
        await srv.stop()


async def test_unknown_paths_are_404(http):
    srv = server()
    await srv.start()
    try:
        for path in ("/nope", "/metricsfoo", "/healthzz", "/api/v1/nothing", "/index.html"):
            async with http.get(url(srv, path)) as r:
                assert r.status == 404, path
    finally:
        await srv.stop()


async def test_a_handler_error_is_500_and_logged(http, caplog):
    def broken() -> dict[str, Any]:
        raise KeyError("track")

    srv = server(broken)

    async def api_broken(request: web.Request) -> web.Response:
        raise RuntimeError("bug")

    srv.api.router.add_get("/status", api_broken)
    await srv.start()
    try:
        with caplog.at_level(logging.ERROR, logger="those_who_run.server"):
            for path in ("/healthz", "/api/v1/status"):
                async with http.get(url(srv, path)) as r:
                    assert r.status == 500, path
        logged = [r for r in caplog.records if r.exc_info]
        assert [r.getMessage() for r in logged] == [
            "error serving GET /healthz",
            "error serving GET /api/v1/status",
        ]
    finally:
        await srv.stop()


async def test_no_response_carries_cors_headers(http):
    srv = server()

    async def status(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    srv.api.router.add_get("/status", status)
    await srv.start()
    try:
        origin = {"Origin": "http://pitwall.example"}
        for method, path in [
            ("GET", "/metrics"),
            ("GET", "/healthz"),
            ("GET", "/api/v1/status"),
            ("GET", "/nope"),
            ("OPTIONS", "/api/v1/status"),
        ]:
            async with http.request(method, url(srv, path), headers=origin) as r:
                assert not any(h.lower().startswith("access-control-") for h in r.headers), path
    finally:
        await srv.stop()


async def test_the_bind_address_is_used():
    srv = server()
    await srv.start()
    try:
        assert srv._runners[0].addresses[0][0] == "127.0.0.1"
    finally:
        await srv.stop()


async def test_the_control_port_has_its_own_routes_and_middleware(http):
    srv = server(control_port=0)

    @web.middleware
    async def token(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.headers.get("Authorization") != "Bearer secret":
            raise web.HTTPUnauthorized()
        return await handler(request)

    async def mute(request: web.Request) -> web.Response:
        return web.json_response({"muted": True})

    srv.control.middlewares.append(token)  # what #140 adds
    srv.control_api.router.add_post("/mute", mute)  # what #136 adds
    await srv.start()
    try:
        assert srv.bound_control_port != srv.bound_port
        async with http.post(url(srv, "/api/v1/mute", control=True)) as r:
            assert r.status == 401
        auth = {"Authorization": "Bearer secret"}
        async with http.post(url(srv, "/api/v1/mute", control=True), headers=auth) as r:
            assert r.status == 200 and await r.json() == {"muted": True}
        async with http.post(url(srv, "/api/v1/mute"), headers=auth) as r:
            assert r.status == 404  # never on the read-only port
        async with http.get(url(srv, "/healthz", control=True), headers=auth) as r:
            assert r.status == 404  # and the read-only routes are not on the control port
        async with http.get(url(srv, "/healthz")) as r:
            assert r.status == 200  # the token check is the control port's alone
    finally:
        await srv.stop()


async def test_no_control_port_unless_configured():
    srv = server()
    await srv.start()
    try:
        assert len(srv._runners) == 1
    finally:
        await srv.stop()


async def test_a_port_in_use_raises_and_leaves_nothing_listening():
    first = server()
    await first.start()
    try:
        second = Server(Metrics(), dict, host="127.0.0.1", port=first.bound_port)
        with pytest.raises(OSError):
            await second.start()
        await second.stop()
        assert second._runners == []
    finally:
        await first.stop()


# the WebSocket hook #239 uses


class PacedTelemetry(FakeTelemetry):
    """Puts one frame on the queue every ``every`` seconds, as the PS5 does at 60 Hz."""

    every = 0.005

    async def _feed(self) -> None:
        shift = time.monotonic() - self.frames[0].t
        for f in self.frames:
            await self.app.states.put(dataclasses.replace(f, t=f.t + shift))
            self.packets += 1
            await asyncio.sleep(self.every)


async def test_a_websocket_route_streams_while_frames_are_processed(settings, sim, http):
    race = sim(total_laps=3).menu().at_track().race([90000, 89000, 88500])
    frames = race.drive(150).frames  # ~1 s of frames at the paced rate
    processed: list[float] = []
    made: list[PacedTelemetry] = []

    def telemetry(app: App) -> PacedTelemetry:
        made.append(PacedTelemetry(app, frames))
        return made[-1]

    app = App(
        settings,
        speech=lambda app: FakeSpeech(),
        player=lambda app: FakePlayer(),
        telemetry=telemetry,
    )

    async def dash(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async def push() -> None:
            while True:
                await ws.send_json({"packets": app.status()["packets"]})
                await asyncio.sleep(0.01)

        pusher = asyncio.create_task(push())
        try:
            async for _ in ws:  # until the client closes
                pass
        finally:
            pusher.cancel()
        return ws

    app.server.api.router.add_get("/dash", dash)
    running = asyncio.create_task(app.run())
    await wait_for(lambda: made and made[0].packets > 0)
    process = app.engine.process

    def counted(state: Any) -> None:
        processed.append(time.monotonic())
        process(state)

    app.engine.process = counted  # type: ignore[method-assign]
    seen: list[int] = []
    async with http.ws_connect(url(app.server, "/api/v1/dash")) as ws:
        async for msg in ws:
            seen.append(msg.json()["packets"])
            if seen[-1] == len(frames):
                break
    app.stop()
    assert await asyncio.wait_for(running, 5) == 0
    assert len(seen) > 10 and seen == sorted(seen)  # it streamed as the frames came in
    assert app.status()["packets"] == len(frames)
    # Every frame was handled as it arrived: the stream did not hold up ingest.
    assert app.states.qsize() == 0
    gaps = [b - a for a, b in zip(processed, processed[1:], strict=False)]
    assert max(gaps) < 0.1


@pytest.fixture
def settings(tmp_path):
    from those_who_run.config import Settings

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
