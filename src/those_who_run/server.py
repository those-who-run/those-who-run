"""The engineer's HTTP server: aiohttp on the event loop.

``GT7_METRICS_PORT`` (9850) serves what anyone on the LAN may read:
``/metrics``, ``/healthz``, and under ``/api/v1`` (:attr:`Server.api`) the
read-only API: ``GET /api/v1/status`` (#292), and the dash WebSocket,
``GET /api/v1/dash`` (#239). The
control port, ``GT7_CONTROL_PORT`` (9851 in ADR 0001), is a second listener with
its own application and middleware (:attr:`Server.control`, routes under
``/api/v1`` in :attr:`Server.control_api`), where the control routes and the
admin-token check go (#136, #140; ADR 0001 point 3). Add routes and middleware
before :meth:`Server.start`; aiohttp freezes them then.

Handlers run on the event loop, so they read the engine's state between frames,
never halfway through one. No CORS headers and no static files: a browser
reaches the engineer only through the pit wall's ``/api/engine/*`` proxy, on
the pit wall's own origin, and serving the web app is the pit wall's job (ADR
0003 point 6).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from those_who_run.metrics import Metrics

log = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

SHUTDOWN_SECS = 1.0  # open connections are cut after this on stop (docker stop: 10 s)


@web.middleware
async def errors(request: web.Request, handler: Handler) -> web.StreamResponse:
    """A handler that raises gets a logged traceback and a 500, not a dropped
    connection. 404 and the other HTTP errors pass through."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("error serving %s %s", request.method, request.path)
        return web.Response(status=500, text="internal server error")


def json_route(body: Callable[[], Any]) -> Handler:
    """A GET handler serving ``body()`` as JSON, never cached: it changes with
    every frame."""

    async def serve(request: web.Request) -> web.Response:
        return web.json_response(body(), headers={"Cache-Control": "no-store"})

    return serve


class DebugAccessLog(AbstractAccessLogger):
    """One debug line per request: Prometheus and the probes would flood INFO."""

    def log(self, request: web.BaseRequest, response: web.StreamResponse, time: float) -> None:
        log.debug(
            "http %s %s %s %d (%.1f ms)",
            request.remote,
            request.method,
            request.path_qs,
            response.status,
            time * 1000,
        )


class Server:
    """``/metrics`` and ``/healthz`` from ``metrics`` and ``health``, room for
    ``/api/v1``, and an optional control port. ``port`` 0 picks a free one
    (:attr:`bound_port`)."""

    def __init__(
        self,
        metrics: Metrics,
        health: Callable[[], dict[str, Any]],
        *,
        host: str = "0.0.0.0",
        port: int = 9850,
        control_port: int | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.control_port = control_port
        self._metrics = metrics
        self._health = health
        self.app = web.Application(middlewares=[errors])
        self.app.router.add_get("/metrics", self._serve_metrics)
        self.app.router.add_get("/healthz", self._serve_health)
        self.api = web.Application()  # mounted at /api/v1 on ``port``: read-only routes
        self.control = web.Application(middlewares=[errors])  # the control port's app
        self.control_api = web.Application()  # mounted at /api/v1 on ``control_port``
        self._runners: list[web.AppRunner] = []
        self._bound: list[int] = []  # the ports listened on, kept after stop()

    async def start(self) -> None:
        self.app.add_subapp("/api/v1", self.api)
        await self._listen(self.app, self.port)
        log.info("metrics on :%d/metrics, health on :%d/healthz", self.bound_port, self.bound_port)
        if self.control_port is not None:
            self.control.add_subapp("/api/v1", self.control_api)
            await self._listen(self.control, self.control_port)
            log.info("control API on :%d/api/v1", self.bound_control_port)

    async def stop(self) -> None:
        while self._runners:
            await self._runners.pop().cleanup()

    @property
    def bound_port(self) -> int:
        return self._bound[0]

    @property
    def bound_control_port(self) -> int:
        return self._bound[1]

    async def _listen(self, app: web.Application, port: int) -> None:
        runner = web.AppRunner(app, access_log_class=DebugAccessLog, shutdown_timeout=SHUTDOWN_SECS)
        await runner.setup()
        self._runners.append(runner)  # cleaned up by stop() even if the bind fails
        await web.TCPSite(runner, self.host, port).start()
        self._bound.append(int(runner.addresses[0][1]))

    async def _serve_metrics(self, request: web.Request) -> web.Response:
        return web.Response(
            body=self._metrics.render(), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    async def _serve_health(self, request: web.Request) -> web.Response:
        status = self._health()
        return web.Response(
            text=json.dumps(status),
            status=200 if status.get("ok", True) else 503,
            content_type="application/json",
        )
