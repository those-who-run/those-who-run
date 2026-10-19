"""The pit wall's HTTP server (#236): a read-only data API, the engineer's
routes forwarded, and the web app's files, all on one origin.

- **Data**, under ``/api/v1``: the sessions, laps and lap traces in
  ``GT7_DATA_DIR``, as JSON, from :mod:`those_who_run.pitwall.data`. Read-only
  (ADR 0001 point 2): the index is opened ``mode=ro`` for each read and closed
  after it, Parquet is read through DuckDB, and nothing is written. The reads
  run in a thread, so one slow trace never holds up the session list.
- **Caching:** the session list and lap tables are kept per index stamp (which
  moves when the engineer commits), and a trace per lap file and frame count
  (a lap file never changes once it is indexed). Every data response carries an
  ``ETag`` built the same way, so a page polling every 5 s gets 304 until the
  engineer writes. JSON over 1 KB is gzipped when the browser takes it.
- **The engineer**, under ``/api/engine``: ``status`` and ``dash`` (a
  WebSocket) go to the read-only port, ``control/{path}`` to the control port's
  ``/api/v1/{path}``. The ``Authorization`` header goes through unchanged and
  is never logged; only a short list of headers is forwarded either way, so
  cookies and hop-by-hop headers stay behind. An engineer that is down is a 502
  within 2 s and never touches the data routes.
- **The web app:** with ``--static``, every other path is a file from that
  directory, and a path that is not a file is ``index.html`` (a client route).
  Hashed assets are cached for a year; ``index.html`` is never cached.

No engineer imports: the pit wall reads the store's files and talks to the
engineer over HTTP only (#195). It holds no secret and reads no token.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import sqlite3
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

from those_who_run import __version__
from those_who_run.openapi import spec
from those_who_run.pitwall import data
from those_who_run.pitwall.api_models import (
    DEFAULT_POINTS,
    MAX_POINTS,
    FilterOption,
    FilterOptions,
    Health,
    KindOption,
    LapList,
    SameTrack,
    SessionList,
)
from those_who_run.sessionkind import LABELS

log = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

SHUTDOWN_SECS = 1.0
GZIP_OVER = 1024  # bytes of JSON: a trace is about 60 KB, an error a few dozen
# The engineer down is a 502 within 2 s (#236 R5): connecting gives up first,
# a status read soon after. The health check asks with less, so a slow
# engineer never makes the probe time out.
CONNECT_SECS = 1.5
STATUS_SECS = 1.8
HEALTH_ENGINEER_SECS = 0.5
CONTROL_SECS = 10.0  # a setup write may take a moment (#138)

IMMUTABLE = "public, max-age=31536000, immutable"  # Vite's hashed names under assets/
NO_CACHE = "no-cache"

# Forwarded to the engineer, and back: nothing else (no cookies, no hop-by-hop).
REQUEST_HEADERS = ("Accept", "Authorization", "Content-Type", "If-Match", "If-None-Match")
RESPONSE_HEADERS = ("Cache-Control", "Content-Type", "ETag", "Retry-After", "WWW-Authenticate")


class Reader:
    """The store, read through :mod:`data`, cached on what makes each read change."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.sessions = lru_cache(maxsize=2)(lambda stamp: data.list_sessions(data_dir))
        # the list as filtered, per stamp and filter: a page polling one view
        # re-reads nothing until the engineer writes
        self.session_list = lru_cache(maxsize=32)(
            lambda stamp, want, tz: build_session_list(self.sessions(stamp), want, tz)
        )
        self.laps = lru_cache(maxsize=16)(
            lambda session_id, stamp: data.lap_summaries(data_dir, session_id)
        )
        self.trace = lru_cache(maxsize=32)(
            lambda session_id, lap, file, frames, points: data.lap_trace(
                data_dir, session_id, lap, points
            )
        )

    def stamp(self) -> float:
        return data.index_stamp(self.data_dir)

    def session(self, session_id: str, stamp: float) -> data.SessionRow | None:
        return next((r for r in self.sessions(stamp) if r.session_id == session_id), None)


# The engineer's routes as the pit wall forwards them. Their bodies are the
# engineer's; a forwarded route whose body the web app reads goes in the schema
# too (``openapi.spec``).
FORWARDED = ("/api/engine/status", "/api/engine/dash", "/api/engine/control/{path}")

DATA_DIR = web.AppKey("data_dir", Path)
READER = web.AppKey("reader", Reader)
CLIENT = web.AppKey("client", aiohttp.ClientSession)
ENGINEER = web.AppKey("engineer", str)  # the engineer's read-only port, no trailing /
CONTROL = web.AppKey("control", str)  # its control port
SCHEMA = web.AppKey("schema", bytes)
STATIC = web.AppKey("static", Path)
SOCKETS: web.AppKey[weakref.WeakSet[web.WebSocketResponse]] = web.AppKey("sockets")


# responses


def encode(value: Any) -> bytes:
    """A model (or a dict of them) as compact JSON."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def json_response(
    request: web.Request, body: bytes, *, status: int = 200, etag: str | None = None
) -> web.Response:
    resp = web.Response(body=body, status=status, content_type="application/json")
    if etag is not None:
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = NO_CACHE  # revalidate every time: 304 is cheap
    if len(body) > GZIP_OVER:
        resp.headers["Vary"] = "Accept-Encoding"
        if "gzip" in request.headers.get("Accept-Encoding", "").lower():
            resp.enable_compression(web.ContentCoding.gzip)
    return resp


def error(request: web.Request, status: int, message: str) -> web.Response:
    return json_response(request, encode({"error": message}), status=status)


def not_modified(request: web.Request, etag: str) -> bool:
    sent = request.headers.get("If-None-Match", "")
    return sent.strip() == "*" or etag in (t.strip() for t in sent.split(","))


def etag_of(*parts: object) -> str:
    """Weak: the gzipped and plain bodies are the same resource. The version is
    in it, so a new pit wall never answers 304 for an old one's body."""
    return 'W/"' + "-".join(str(p) for p in (__version__, *parts)) + '"'


@web.middleware
async def errors(request: web.Request, handler: Handler) -> web.StreamResponse:
    """JSON errors under /api/ and on /healthz. A busy index is a 503; a handler
    that raises is logged with its traceback and answered 500."""
    api = request.path.startswith("/api/") or request.path == "/healthz"
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if api and exc.status >= 400:
            return error(request, exc.status, exc.reason)
        raise
    except sqlite3.OperationalError as exc:  # locked or busy past data.READ_TIMEOUT_SECS
        log.warning("index busy serving %s: %s", request.path, exc)
        return error(request, 503, "the index is busy, try again")
    except Exception:
        log.exception("error serving %s %s", request.method, request.path)
        return error(request, 500, "internal server error")


class AccessLog(AbstractAccessLogger):
    """One debug line per request, path only: never a header (the token)."""

    def log(self, request: web.BaseRequest, response: web.StreamResponse, time: float) -> None:
        log.debug(
            "http %s %s %s %d (%.1f ms)",
            request.remote,
            request.method,
            request.path,
            response.status,
            time * 1000,
        )


# data routes


async def _cached(
    request: web.Request, etag: str, read: Callable[[], Any], missing: str
) -> web.Response:
    """304 when the browser has ``etag``; else ``read()`` in a thread, 404 with
    ``missing`` when it returns None."""
    if not_modified(request, etag):
        return web.Response(status=304, headers={"ETag": etag, "Cache-Control": NO_CACHE})

    def body() -> bytes | None:
        value = read()
        return None if value is None else encode(value)

    out = await asyncio.to_thread(body)
    if out is None:
        return error(request, 404, missing)
    return json_response(request, out, etag=etag)


def _session_id(request: web.Request) -> str:
    session_id = request.match_info["id"]
    if not data.safe_name(session_id):
        raise web.HTTPNotFound(reason="no such session")
    return session_id


def _day(request: web.Request, name: str) -> date | None:
    """A ``YYYY-MM-DD`` query parameter, or None when it is absent or empty."""
    text = request.query.get(name, "")
    if not text:
        return None
    try:
        if len(text) != 10:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        raise web.HTTPBadRequest(reason=f"{name} is a date, YYYY-MM-DD") from None


def session_filter(request: web.Request) -> data.SessionFilter:
    """The list's filters from the query: empty values match everything."""
    q = request.query
    return data.SessionFilter(
        track=q.get("track") or None,
        car=q.get("car") or None,
        kind=q.get("kind") or None,
        since=_day(request, "from"),
        until=_day(request, "to"),
    )


def _zone(request: web.Request) -> ZoneInfo | None:
    """The ``tz`` query parameter as a zone, or None (the pit wall's own zone)
    when it is absent or empty. The pit wall's container runs in UTC; the
    browser sends its own zone so a day is the viewer's day."""
    name = request.query.get("tz", "")
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        raise web.HTTPBadRequest(reason="tz is a time zone name, Europe/Dublin") from None


def build_session_list(
    rows: list[data.SessionRow], want: data.SessionFilter, tz: ZoneInfo | None = None
) -> SessionList:
    shown = _values(data.filter_sessions(rows, want, tz))
    counts = data.option_counts(rows, want, tz)
    return SessionList(
        sessions=shown,
        options=FilterOptions(
            track=[FilterOption(v, n) for v, n in counts["track"].items()],
            car=[FilterOption(v, n) for v, n in counts["car"].items()],
            kind=[KindOption(k, LABELS.get(k, k), n) for k, n in counts["kind"].items()],
        ),
        total=len(rows),
        matched=len(shown),
    )


async def list_sessions(request: web.Request) -> web.Response:
    reader = request.app[READER]
    want, tz = session_filter(request), _zone(request)
    stamp = reader.stamp()
    # The filters and the zone are in the ETag, as in the URL: one stamp, one
    # body per view.
    view = repr((dataclasses.astuple(want), tz and tz.key))
    key = hashlib.blake2s(view.encode(), digest_size=6).hexdigest()
    return await _cached(
        request, etag_of(stamp, key), lambda: reader.session_list(stamp, want, tz), ""
    )


def _values(rows: list[data.SessionRow]) -> list[Any]:
    return [r.values for r in rows if r.values is not None]


async def get_session(request: web.Request) -> web.Response:
    reader, session_id = request.app[READER], _session_id(request)
    stamp = reader.stamp()

    def read() -> Any:
        row = reader.session(session_id, stamp)
        return None if row is None else row.values

    return await _cached(request, etag_of(stamp), read, "no such session")


async def list_laps(request: web.Request) -> web.Response:
    reader, session_id = request.app[READER], _session_id(request)
    stamp = reader.stamp()

    def read() -> LapList | None:
        if reader.session(session_id, stamp) is None:
            return None
        return LapList(session_id=session_id, laps=reader.laps(session_id, stamp))

    return await _cached(request, etag_of(stamp), read, "no such session")


async def same_track(request: web.Request) -> web.Response:
    reader, session_id = request.app[READER], _session_id(request)
    stamp = reader.stamp()

    def read() -> SameTrack | None:
        row = reader.session(session_id, stamp)
        if row is None:
            return None
        return SameTrack(sessions=_values(data.same_track_sessions(row, reader.sessions(stamp))))

    return await _cached(request, etag_of(stamp), read, "no such session")


async def get_trace(request: web.Request) -> web.Response:
    reader, session_id = request.app[READER], _session_id(request)
    try:
        lap = int(request.match_info["lap"])
        points = int(request.query.get("points", DEFAULT_POINTS))
    except ValueError:
        return error(request, 400, "lap and points are whole numbers")
    if not 1 <= points <= MAX_POINTS:
        return error(request, 400, f"points is from 1 to {MAX_POINTS}")
    # The lap's file and frame count key the trace, and its ETag: an index read,
    # not a Parquet one.
    found = await asyncio.to_thread(data.lap_file, reader.data_dir, session_id, lap)
    if found is None:
        return error(request, 404, "no such lap")
    file, frames = found
    return await _cached(
        request,
        etag_of(file, frames, points),
        lambda: reader.trace(session_id, lap, file, frames, points),
        "no telemetry for this lap",
    )


async def openapi(request: web.Request) -> web.Response:
    return json_response(request, request.app[SCHEMA])


def _readable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK | os.X_OK)


async def healthz(request: web.Request) -> web.Response:
    """200 while the data directory can be read. The index may not exist yet (a
    new volume), and an engineer that is down is reported, never a failure."""
    data_dir = request.app[DATA_DIR]
    ok = await asyncio.to_thread(_readable, data_dir)
    engineer = await _engineer_answers(request.app)
    body = Health(
        ok=ok, version=__version__, index=data.index_path(data_dir).exists(), engineer=engineer
    )
    return json_response(request, encode(body), status=200 if ok else 503)


async def _engineer_answers(app: web.Application) -> bool:
    url = f"{app[ENGINEER]}/api/v1/status"
    timeout = aiohttp.ClientTimeout(total=HEALTH_ENGINEER_SECS)
    try:
        async with app[CLIENT].get(url, timeout=timeout) as resp:
            return resp.status < 500
    except aiohttp.ClientError, TimeoutError:
        return False


# the engineer


async def _forward(request: web.Request, url: str, timeout: aiohttp.ClientTimeout) -> web.Response:
    headers = {h: request.headers[h] for h in REQUEST_HEADERS if h in request.headers}
    body = await request.read() if request.can_read_body else None
    try:
        async with request.app[CLIENT].request(
            request.method,
            url,
            params=request.rel_url.query,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=False,
        ) as up:
            payload = await up.read()
            kept = {h: up.headers[h] for h in RESPONSE_HEADERS if h in up.headers}
            return web.Response(status=up.status, body=payload, headers=kept)
    except (aiohttp.ClientError, TimeoutError) as exc:
        # The path only: never the headers, which may carry the admin token.
        log.debug("engineer did not answer %s %s: %r", request.method, request.path, exc)
        return error(request, 502, "the engineer is not answering")


async def engine_status(request: web.Request) -> web.Response:
    return await _forward(
        request,
        f"{request.app[ENGINEER]}/api/v1/status",
        aiohttp.ClientTimeout(total=STATUS_SECS, connect=CONNECT_SECS),
    )


async def engine_control(request: web.Request) -> web.Response:
    path = request.match_info["path"]
    if not path or any(part in ("", ".", "..") for part in path.split("/")):
        return error(request, 404, "no such engineer route")
    return await _forward(
        request,
        f"{request.app[CONTROL]}/api/v1/{quote(path, safe='/')}",
        aiohttp.ClientTimeout(total=CONTROL_SECS, connect=CONNECT_SECS),
    )


async def engine_dash(request: web.Request) -> web.StreamResponse:
    """The engineer's dash WebSocket (#239), pumped both ways. Either side
    closing closes the other. Not a WebSocket upgrade is a 400, before the
    engineer is asked anything."""
    ws = web.WebSocketResponse(heartbeat=30.0)
    if not ws.can_prepare(request).ok:
        return error(request, 400, "a WebSocket upgrade is needed here")
    headers = {h: request.headers[h] for h in ("Authorization",) if h in request.headers}
    url = f"{request.app[ENGINEER]}/api/v1/dash"
    try:
        async with asyncio.timeout(STATUS_SECS):
            upstream = await request.app[CLIENT].ws_connect(url, headers=headers)
    except (aiohttp.ClientError, TimeoutError) as exc:
        log.debug("engineer dash did not answer: %r", exc)
        return error(request, 502, "the engineer is not answering")
    try:
        await ws.prepare(request)
    except BaseException:
        await upstream.close()  # the browser's side never opened: don't leave this one
        raise
    request.app[SOCKETS].add(ws)
    try:
        pumps = [
            asyncio.create_task(_pump(upstream, ws)),
            asyncio.create_task(_pump(ws, upstream)),
        ]
        _, pending = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await upstream.close()
        await ws.close(code=upstream.close_code or aiohttp.WSCloseCode.OK)
    return ws


async def _pump(
    src: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
    dst: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
) -> None:
    async for msg in src:
        if msg.type is aiohttp.WSMsgType.TEXT:
            await dst.send_str(msg.data)
        elif msg.type is aiohttp.WSMsgType.BINARY:
            await dst.send_bytes(msg.data)


# the web app


async def static(request: web.Request) -> web.StreamResponse:
    root = request.app[STATIC]
    rel = request.match_info["tail"]
    if rel.startswith("api/"):
        raise web.HTTPNotFound()
    target = (root / rel).resolve()
    if rel and target.is_relative_to(root) and target.is_file():
        return web.FileResponse(
            target, headers={"Cache-Control": IMMUTABLE if rel.startswith("assets/") else NO_CACHE}
        )
    index = root / "index.html"
    if rel.startswith("assets/") or not index.is_file():  # never index.html for a script
        raise web.HTTPNotFound()
    return web.FileResponse(index, headers={"Cache-Control": NO_CACHE})


# the app


def make_app(
    data_dir: Path,
    *,
    engineer_url: str = "http://those-who-run:9850",
    control_url: str = "http://those-who-run:9851",
    static_dir: Path | None = None,
) -> web.Application:
    app = web.Application(middlewares=[errors])
    app[DATA_DIR] = Path(data_dir)
    app[READER] = Reader(Path(data_dir))
    app[ENGINEER] = engineer_url.rstrip("/")
    app[CONTROL] = control_url.rstrip("/")
    app[SCHEMA] = encode(spec())
    app[SOCKETS] = weakref.WeakSet[web.WebSocketResponse]()
    app.cleanup_ctx.append(_client)
    app.on_shutdown.append(_close_sockets)

    r = app.router
    r.add_get("/healthz", healthz)
    r.add_get("/api/v1/openapi.json", openapi)
    r.add_get("/api/v1/sessions", list_sessions)
    r.add_get("/api/v1/sessions/{id}", get_session)
    r.add_get("/api/v1/sessions/{id}/laps", list_laps)
    r.add_get("/api/v1/sessions/{id}/laps/{lap}/trace", get_trace)
    r.add_get("/api/v1/sessions/{id}/same-track", same_track)
    r.add_get("/api/engine/status", engine_status)
    r.add_get("/api/engine/dash", engine_dash)
    r.add_route("*", "/api/engine/control/{path:.*}", engine_control)
    if static_dir is not None:
        app[STATIC] = Path(static_dir).resolve()
        r.add_get("/{tail:.*}", static)
    return app


async def _client(app: web.Application) -> AsyncIterator[None]:
    """One client session for the app's life, for every call to the engineer."""
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, connect=CONNECT_SECS),
        cookie_jar=aiohttp.DummyCookieJar(),  # the engineer's cookies are not kept
    ) as session:
        app[CLIENT] = session
        yield


async def _close_sockets(app: web.Application) -> None:
    sockets = app[SOCKETS]
    for ws in [*sockets]:
        with contextlib.suppress(Exception):
            await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b"shutting down")


def run(
    data_dir: Path,
    *,
    host: str,
    port: int,
    engineer_url: str,
    control_url: str,
    static_dir: Path | None = None,
) -> int:
    """Serve until SIGINT or SIGTERM."""
    app = make_app(
        data_dir, engineer_url=engineer_url, control_url=control_url, static_dir=static_dir
    )
    log.info(
        "pit wall on http://%s:%d, reading %s, engineer at %s",
        host,
        port,
        data_dir,
        engineer_url,
    )
    web.run_app(
        app,
        host=host,
        port=port,
        access_log_class=AccessLog,
        shutdown_timeout=SHUTDOWN_SECS,
        print=None,
    )
    return 0
