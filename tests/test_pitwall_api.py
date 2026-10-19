"""The pit wall's data API (#236): routes, schema, read-only, the engineer proxy,
the web app's files, caching and concurrency, over stores the engineer wrote."""

import asyncio
import dataclasses
import gzip
import hashlib
import importlib.util
import json
import logging
import os
import socket
import sqlite3
import stat
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiohttp import ClientWebSocketResponse, WSMsgType, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer

from those_who_run import __version__, openapi
from those_who_run.__main__ import main
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.pitwall import api_models, data, server
from those_who_run.replay import read_recording
from those_who_run.rules import build_rules
from those_who_run.store import SessionStore

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
RACE = "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz"
PIT_STOP = "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz"
DRIFT = "real-nuc-tsukuba-brz-drift-2026-10-15.jsonl.gz"
T0 = 1792087200.0  # 2026-10-15 18:00 UTC
DAY = 86400.0
TOKEN = "Bearer not-a-real-admin-token-236"

_spec = importlib.util.spec_from_file_location("openapi_script", ROOT / "scripts" / "openapi.py")
assert _spec is not None and _spec.loader is not None
openapi_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(openapi_script)

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes"
)


def drive(root: Path, frames, at: float, close: bool = True) -> None:
    """Frames through an engine into the store at ``root``, from ``at``."""
    first = frames[0].t
    clock = [at]
    store = SessionStore(root, clock=lambda: clock[0])
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    for f in frames:
        clock[0] = at + f.t - first
        engine.process(f)
    if close and store.session is not None and engine.prev is not None:
        store.end_session(engine.prev)
    store.close()


def recording(name: str) -> list:
    return list(read_recording(FIXTURES / name, strict=True))


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """The race, the pit stop twice (for same-track) and the drift session, by the
    engineer's store, which is then closed."""
    root = tmp_path_factory.mktemp("store")
    drive(root, recording(RACE), T0)
    stop = recording(PIT_STOP)
    drive(root, stop, T0 + DAY)
    drive(root, stop, T0 + 2 * DAY)
    drive(root, recording(DRIFT), T0 + 3 * DAY)
    return root


@pytest.fixture
def store(built, tmp_path) -> Path:
    """A copy of the built store each test may change."""
    root = tmp_path / "data"
    import shutil

    shutil.copytree(built, root)
    return root


async def start(app: web.Application) -> TestClient:
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.fixture
async def api(store) -> AsyncIterator[TestClient]:
    """The pit wall over ``store``, with no engineer anywhere."""
    client = await start(server.make_app(store, engineer_url=f"http://127.0.0.1:{closed_port()}"))
    yield client
    await client.close()


def closed_port() -> int:
    """A port nothing listens on: connecting is refused at once."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def plain(value) -> object:
    """A model as the JSON a client reads it back as."""
    return json.loads(json.dumps(dataclasses.asdict(value)))


# AC1: what data.py returns, as JSON


async def test_sessions_laps_and_traces_are_what_data_returns(api, store):
    rows = data.list_sessions(store)
    assert len(rows) >= 3
    resp = await api.get("/api/v1/sessions")
    assert resp.status == 200
    body = await resp.json()
    assert body["sessions"] == [plain(r.values) for r in rows]
    assert [s["session_id"] for s in body["sessions"]] == [r.session_id for r in rows]
    options = data.filter_options(rows)
    assert [t["value"] for t in body["options"]["track"]] == options["track"]
    assert [c["value"] for c in body["options"]["car"]] == options["car"]
    assert [k["value"] for k in body["options"]["kind"]] == options["kind"]

    for row in rows:
        sid = row.session_id
        resp = await api.get(f"/api/v1/sessions/{sid}")
        assert await resp.json() == plain(row.values)
        resp = await api.get(f"/api/v1/sessions/{sid}/laps")
        laps = data.lap_summaries(store, sid)
        assert (await resp.json())["laps"] == [plain(lap) for lap in laps]
        for lap in laps:
            resp = await api.get(f"/api/v1/sessions/{sid}/laps/{lap.lap}/trace")
            trace = data.lap_trace(store, sid, lap.lap)
            assert trace is not None
            assert await resp.json() == plain(trace)


async def test_session_values_follow_the_card(api, store):
    """ADR 0004 point 6: values beside the card strings, never only the strings."""
    race, *_ = [r for r in data.list_sessions(store) if r.track_id == 100002]
    body = await (await api.get(f"/api/v1/sessions/{race.session_id}")).json()
    assert set(body) == {f.name for f in dataclasses.fields(api_models.Session)}
    assert body["title"] == race.title and body["result"] == race.result
    assert body["track"] == {
        "id": 100002,
        "name": "Circuit Gilles Villeneuve",
        "sure": True,
        "evidence": body["track"]["evidence"],
    }
    assert body["kind"] == "lap_race" and body["kind_label"] == "12-lap race"
    assert (body["final_position"], body["total_cars"], body["position_shown"]) == (15, 20, True)
    assert body["best_lap_ms"] == 97524 and body["best_lap_no"] == 1
    assert not body["finished"] and body["total_time_ms"] is None
    assert body["laps_completed"] == 2 and body["total_laps"] == 12

    stop = (
        await (
            await api.get("/api/v1/sessions", params={"track": "Suzuka Circuit East Course"})
        ).json()
    )["sessions"][0]
    assert stop["finished"] and stop["pit_stops"] == 1 and len(stop["fuel_by_stint"]) == 2
    assert stop["result"].startswith("🚩 Finished P1 of 2 in ")
    laps = (await (await api.get(f"/api/v1/sessions/{stop['session_id']}/laps")).json())["laps"]
    assert [(x["lap"], x["pit"], x["out_lap"], x["clean"]) for x in laps if not x["clean"]] == [
        (3, True, False, False),
        (4, False, True, False),
    ]


async def test_filters(api, store):
    rows = data.list_sessions(store)
    for key, value in (("kind", "lap_race"), ("track", rows[0].track), ("car", rows[0].car)):
        want = data.filter_sessions(rows, data.SessionFilter(**{key: value}))
        body = await (await api.get("/api/v1/sessions", params={key: value})).json()
        assert [s["session_id"] for s in body["sessions"]] == [r.session_id for r in want]
    body = await (await api.get("/api/v1/sessions", params={"kind": "no-such-kind"})).json()
    assert body["sessions"] == [] and body["options"]["track"]  # options are from every session
    assert all(t["count"] == 0 for t in body["options"]["track"])  # a choice that empties it


def day(at: float) -> str:
    """The local day a session started at ``at`` is on, as ``?from=`` takes it."""
    return datetime.fromtimestamp(at).date().isoformat()


async def test_date_filter(api, store):
    """#318 AC1: from and to are inclusive local days on started_at."""
    rows = data.list_sessions(store)
    assert len(rows) == 3  # the drift session never starts one

    async def ids(**params: str) -> list[str]:
        body = await (await api.get("/api/v1/sessions", params=params)).json()
        return [s["session_id"] for s in body["sessions"]]

    def started(lo: float, hi: float) -> list[str]:
        return [r.session_id for r in rows if day(lo) <= day(r.started_at) <= day(hi)]

    pit_stops = started(T0 + DAY, T0 + 2 * DAY)
    assert len(pit_stops) == 2
    assert await ids(**{"from": day(T0 + DAY), "to": day(T0 + 2 * DAY)}) == pit_stops
    assert await ids(**{"from": day(T0 + 2 * DAY)}) == started(T0 + 2 * DAY, T0 + 2 * DAY)
    assert await ids(**{"from": day(T0 + 3 * DAY)}) == []
    assert await ids(to=day(T0)) == started(T0, T0)
    one_day = day(T0 + DAY)
    assert await ids(**{"from": one_day, "to": one_day}) == started(T0 + DAY, T0 + DAY)
    assert await ids(**{"from": day(T0 + 3 * DAY), "to": day(T0)}) == []
    assert await ids(**{"from": "", "to": ""}) == [r.session_id for r in rows]


async def test_dates_are_days_in_the_viewers_zone(tmp_path):
    """The pit wall runs in UTC; the viewer may not. A race at 23:30 UTC on
    17 October is on the 18th in Dublin (IST, UTC+1), and one at 23:30 UTC on
    25 October, after the clocks go back, is on the 25th there too."""
    stop = recording(PIT_STOP)
    before = datetime(2026, 10, 17, 23, 30, tzinfo=UTC).timestamp()
    after = datetime(2026, 10, 25, 23, 30, tzinfo=UTC).timestamp()
    drive(tmp_path, stop, before)
    drive(tmp_path, stop, after)
    api = await start(server.make_app(tmp_path, engineer_url=f"http://127.0.0.1:{closed_port()}"))
    try:
        newer, older = (r.session_id for r in data.list_sessions(tmp_path))

        async def on(day: str, tz: str | None) -> list[str]:
            params = {"from": day, "to": day} | ({"tz": tz} if tz else {})
            resp = await api.get("/api/v1/sessions", params=params)
            body = await resp.json()
            assert body["matched"] == len(body["sessions"])
            counts = sum(t["count"] for t in body["options"]["track"])
            assert counts == body["matched"]  # the counts follow the zone
            return [s["session_id"] for s in body["sessions"]]

        assert await on("2026-10-17", "UTC") == [older]
        assert await on("2026-10-18", "UTC") == []
        assert await on("2026-10-17", "Europe/Dublin") == []
        assert await on("2026-10-18", "Europe/Dublin") == [older]
        assert await on("2026-10-25", "Europe/Dublin") == [newer]
        assert await on("2026-10-26", "Europe/Dublin") == []
        assert await on("2026-10-25", "America/New_York") == [newer]

        utc = await api.get("/api/v1/sessions", params={"tz": "UTC"})
        dublin = await api.get("/api/v1/sessions", params={"tz": "Europe/Dublin"})
        assert utc.headers["ETag"] != dublin.headers["ETag"]  # the zone is in the key
        again = await api.get(
            "/api/v1/sessions",
            params={"tz": "Europe/Dublin"},
            headers={"If-None-Match": dublin.headers["ETag"]},
        )
        assert again.status == 304
        for bad in ("Europe/Nowhere", "../../etc/passwd", "/etc/localtime", "UTC+1"):
            resp = await api.get("/api/v1/sessions", params={"tz": bad})
            assert resp.status == 400
            assert await resp.json() == {"error": "tz is a time zone name, Europe/Dublin"}
    finally:
        await api.close()


@pytest.mark.parametrize(
    "value", ["yesterday", "2026-13-01", "2026-10-1", "20261017", "1792087200"]
)
async def test_a_bad_date_is_a_400(api, value):
    for name in ("from", "to"):
        resp = await api.get("/api/v1/sessions", params={name: value})
        assert resp.status == 400
        assert await resp.json() == {"error": f"{name} is a date, YYYY-MM-DD"}


async def test_total_and_matched(api, store):
    """#318 AC2: total is the store, matched the sessions after the filters."""
    rows = data.list_sessions(store)
    suzuka = "Suzuka Circuit East Course"
    for params, want in (
        ({}, len(rows)),
        ({"track": suzuka}, 2),
        ({"track": suzuka, "from": day(T0 + 2 * DAY)}, 1),
        ({"track": suzuka, "kind": "no-such-kind"}, 0),
    ):
        body = await (await api.get("/api/v1/sessions", params=params)).json()
        assert body["total"] == len(rows) == 3
        assert body["matched"] == len(body["sessions"]) == want


async def test_option_counts_leave_out_their_own_filter(api, store):
    """#318 AC3, R3: each option counts the sessions it would leave with the
    other filters as they are."""
    rows = data.list_sessions(store)
    races = [r for r in rows if r.kind == "lap_race"]
    assert races
    body = await (await api.get("/api/v1/sessions", params={"kind": "lap_race"})).json()
    tracks = {t["value"]: t["count"] for t in body["options"]["track"]}
    assert set(tracks) == {r.track for r in rows}  # every track, even with none left
    assert tracks == {t: sum(r.track == t for r in races) for t in tracks}
    assert tracks == {"Circuit Gilles Villeneuve": 1, "Suzuka Circuit East Course": 2}
    params = {"kind": "lap_race", "from": day(T0 + DAY)}
    later = await (await api.get("/api/v1/sessions", params=params)).json()
    tracks = {t["value"]: t["count"] for t in later["options"]["track"]}
    assert tracks == {"Circuit Gilles Villeneuve": 0, "Suzuka Circuit East Course": 2}
    # the kind's own options ignore the kind chosen: every kind still counts
    kinds = {k["value"]: k["count"] for k in body["options"]["kind"]}
    assert kinds == {k: sum(r.kind == k for r in rows) for k in kinds}
    assert sum(kinds.values()) == len(rows)

    # two filters: track counts follow the date, car counts the track and the date
    suzuka = "Suzuka Circuit East Course"
    since = day(T0 + 2 * DAY)
    params = {"track": suzuka, "from": since}
    body = await (await api.get("/api/v1/sessions", params=params)).json()
    later = [r for r in rows if day(r.started_at) >= since]
    tracks = {t["value"]: t["count"] for t in body["options"]["track"]}
    assert tracks == {t: sum(r.track == t for r in later) for t in tracks}
    both = [r for r in later if r.track == suzuka]
    cars = {c["value"]: c["count"] for c in body["options"]["car"]}
    assert cars == {c: sum(r.car == c for r in both) for c in cars}
    assert body["matched"] == len(both) == 1


async def test_each_filter_has_its_own_etag(api):
    """#318 R5: the filters are part of the cache key."""
    every = await api.get("/api/v1/sessions")
    races = await api.get("/api/v1/sessions", params={"kind": "lap_race"})
    assert every.headers["ETag"] != races.headers["ETag"]
    again = await api.get(
        "/api/v1/sessions",
        params={"kind": "lap_race"},
        headers={"If-None-Match": races.headers["ETag"]},
    )
    assert again.status == 304
    # an empty value is no filter: the same body, the same tag
    empty = await api.get("/api/v1/sessions", params={"track": "", "from": ""})
    assert empty.headers["ETag"] == every.headers["ETag"]


async def test_same_track(api, store):
    rows = data.list_sessions(store)
    for row in rows:
        body = await (await api.get(f"/api/v1/sessions/{row.session_id}/same-track")).json()
        want = data.same_track_sessions(row, rows)
        assert [s["session_id"] for s in body["sessions"]] == [r.session_id for r in want]
    suzuka = [r for r in rows if r.track == "Suzuka Circuit East Course"]
    assert len(suzuka) == 2


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/api/v1/sessions/20990101-000000", 404),
        ("/api/v1/sessions/bad%20id", 404),
        ("/api/v1/sessions/..%2Fetc", 404),  # a hand-edited link (was AppTest's, #238 R6)
        ("/api/v1/sessions/..%2Fetc/laps", 404),
        ("/api/v1/sessions/20990101-000000/laps", 404),
        ("/api/v1/sessions/20990101-000000/same-track", 404),
        ("/api/v1/sessions/20990101-000000/laps/1/trace", 404),
        ("/api/v1/nope", 404),
    ],
)
async def test_missing_things_are_json_404s(api, path, status):
    resp = await api.get(path)
    assert resp.status == status
    assert "error" in await resp.json()


async def test_trace_parameters(api, store):
    sid = data.list_sessions(store)[-1].session_id
    for query in ("points=0", f"points={api_models.MAX_POINTS + 1}", "points=many"):
        resp = await api.get(f"/api/v1/sessions/{sid}/laps/1/trace?{query}")
        assert resp.status == 400, query
    assert (await api.get(f"/api/v1/sessions/{sid}/laps/x/trace")).status == 400
    assert (await api.get(f"/api/v1/sessions/{sid}/laps/99/trace")).status == 404
    body = await (await api.get(f"/api/v1/sessions/{sid}/laps/1/trace?points=20")).json()
    assert len(body["t"]) <= 20


async def test_a_lap_file_gone_is_a_404(api, store):
    row = data.list_sessions(store)[-1]
    lap = data.lap_summaries(store, row.session_id)[0]
    (store / "sessions" / row.session_id / lap.file).unlink()
    resp = await api.get(f"/api/v1/sessions/{row.session_id}/laps/{lap.lap}/trace")
    assert resp.status == 404


async def test_a_corrupt_lap_file_is_a_json_error_and_the_rest_still_reads(api, store):
    """A lap file that isn't Parquet: the page's error state, not a crash, and the
    other laps and sessions still read (was AppTest's, #238 R6)."""
    row = data.list_sessions(store)[-1]
    laps = data.lap_summaries(store, row.session_id)
    (store / "sessions" / row.session_id / laps[1].file).write_bytes(b"not parquet")
    for path in ("laps", f"laps/{laps[1].lap}/trace"):
        resp = await api.get(f"/api/v1/sessions/{row.session_id}/{path}")
        assert resp.status == 500 and "error" in await resp.json(), path
    resp = await api.get(f"/api/v1/sessions/{row.session_id}/laps/{laps[0].lap}/trace")
    assert resp.status == 200
    assert (await api.get("/api/v1/sessions")).status == 200


# R10: traces keep peaks


def test_thinned_trace_keeps_the_peaks_and_the_ends(store):
    row = next(r for r in data.list_sessions(store) if r.track_id == 100002)
    full = data.lap_trace(store, row.session_id, 1, max_points=api_models.MAX_POINTS)
    thin = data.lap_trace(store, row.session_id, 1, max_points=40)
    assert full is not None and thin is not None
    assert len(full) > 40 >= len(thin) > 20
    assert max(thin.speed_kph) == max(full.speed_kph)
    assert min(thin.speed_kph) == min(full.speed_kph)
    assert thin.t[0] == 0.0 and thin.t[-1] == full.t[-1]
    assert list(thin.t) == sorted(thin.t)
    assert len(data.lap_trace(store, row.session_id, 1, max_points=3) or ()) <= 3


def test_an_open_session_has_values_from_the_index(tmp_path, sim):
    race = sim(total_laps=5, burn=5).menu().at_track().race([98000, 97000], finish=False)
    drive(tmp_path, race.frames, T0, close=False)
    (row,) = data.list_sessions(tmp_path)
    v = row.values
    assert v is not None and not v.closed and v.ended_at is None
    assert v.result.startswith("Running") and v.kind_label == "5-lap race"
    assert v.pit_stops == 0 and v.driving_ms is None and not v.continued
    assert v.best_lap_no is not None


# AC2: the schema


def test_schema_current(tmp_path):
    assert openapi_script.main(["--check"]) == 0, "run `make openapi` and commit web/openapi.json"
    committed = json.loads((ROOT / "web" / "openapi.json").read_text())
    assert committed == openapi.spec()
    paths = set(committed["paths"])
    app = server.make_app(tmp_path, static_dir=tmp_path)
    for resource in app.router.resources():
        path = resource.canonical
        if path == "/{tail}":  # the web app's files
            continue
        assert path in paths or path in server.FORWARDED, f"{path} is not in the schema"
    stale = tmp_path / "openapi.json"
    assert openapi_script.main([], out=stale) == 0
    assert openapi_script.main(["--check"], out=stale) == 0
    stale.write_text("{}\n")
    assert openapi_script.main(["--check"], out=stale) == 1
    assert openapi_script.main(["--check"], out=tmp_path / "missing.json") == 1


async def test_schema_is_served(api):
    resp = await api.get("/api/v1/openapi.json")
    assert resp.status == 200
    assert await resp.json() == json.loads((ROOT / "web" / "openapi.json").read_text())


def test_schema_types():
    comps: dict = {}
    assert openapi.schema_for(int | None, comps) == {"type": ["integer", "null"]}
    assert openapi.schema_for(tuple[float, ...], comps) == {
        "type": "array",
        "items": {"type": "number"},
    }
    assert openapi.schema_for(api_models.Track | None, comps) == {
        "anyOf": [{"$ref": "#/components/schemas/Track"}, {"type": "null"}]
    }
    assert openapi.schema_for(dict[str, int], comps)["additionalProperties"] == {"type": "integer"}
    from typing import Literal

    assert openapi.schema_for(Literal["a", "b"], comps) == {"enum": ["a", "b"]}
    track = comps["Track"]
    assert track["required"] == ["id", "name", "sure", "evidence"]
    assert track["description"] == "The track as the detector placed it."
    session = openapi.schema_for(api_models.Session, comps)
    assert session == {"$ref": "#/components/schemas/Session"}
    assert comps["Session"]["properties"]["track"]["allOf"] == [
        {"$ref": "#/components/schemas/Track"}
    ]
    assert "description" not in comps.get("KindOption", openapi._object(api_models.KindOption, {}))
    with pytest.raises(TypeError):
        openapi.schema_for(set[int], comps)


# AC3: read-only


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Every file but SQLite's -wal and -shm, by size and content."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.endswith(("-wal", "-shm")):
            out[str(p.relative_to(root))] = (
                p.stat().st_mtime_ns,
                hashlib.sha256(p.read_bytes()).hexdigest(),
            )
    return out


def read_only(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def writable(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        p.chmod(p.stat().st_mode | stat.S_IWUSR)


@needs_non_root
async def test_every_route_works_read_only_and_writes_nothing(store):
    """ADR 0001 point 2: sessions/ read-only, the engineer's store closed."""
    assert not (store / "index.sqlite-shm").exists(), "the engineer closed cleanly"
    before = snapshot(store)
    read_only(store / "sessions")
    client = await start(server.make_app(store, engineer_url=f"http://127.0.0.1:{closed_port()}"))
    try:
        sid = data.list_sessions(store)[0].session_id
        for path in (
            "/healthz",
            "/api/v1/openapi.json",
            "/api/v1/sessions",
            f"/api/v1/sessions/{sid}",
            f"/api/v1/sessions/{sid}/laps",
            f"/api/v1/sessions/{sid}/laps/1/trace",
            f"/api/v1/sessions/{sid}/same-track",
        ):
            resp = await client.get(path)
            assert resp.status == 200, path
        db = data.open_index(store)
        assert db is not None
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM sessions")
        db.close()
    finally:
        await client.close()
        writable(store / "sessions")
    assert snapshot(store) == before


def test_no_secret_is_read():
    """R3: the server reads no token from the environment."""
    source = (ROOT / "src" / "those_who_run" / "pitwall" / "server.py").read_text()
    assert "environ" not in source and "getenv" not in source
    assert "those_who_run.engine" not in source and "those_who_run.store" not in source


# AC4, AC5: the engineer, forwarded


def stub_engineer(seen: list) -> tuple[web.Application, web.Application]:
    """The engineer's two ports: status and dash on one, control on the other."""

    async def status(request: web.Request) -> web.Response:
        seen.append(("status", dict(request.headers)))
        return web.json_response(
            {"state": "idle", "version": "stub"}, headers={"Set-Cookie": "a=b"}
        )

    async def dash(request: web.Request) -> web.WebSocketResponse:
        seen.append(("dash", dict(request.headers)))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        for n in range(1, 4):
            await ws.send_str(json.dumps({"n": n}))
        msg = await ws.receive()
        await ws.send_str(f"echo:{msg.data}")
        await ws.close()
        return ws

    async def control(request: web.Request) -> web.Response:
        seen.append(("control", dict(request.headers)))
        body = await request.text()
        return web.json_response(
            {
                "path": request.path,
                "method": request.method,
                "query": request.query_string,
                "body": body,
                "authorization": request.headers.get("Authorization"),
            },
            status=201 if request.method == "POST" else 200,
            headers={"ETag": '"c1"', "Connection": "keep-alive"},
        )

    read = web.Application()
    read.router.add_get("/api/v1/status", status)
    read.router.add_get("/api/v1/dash", dash)
    ctl = web.Application()
    ctl.router.add_route("*", "/api/v1/{path:.*}", control)
    return read, ctl


@pytest.fixture
async def proxied(store) -> AsyncIterator[tuple[TestClient, list]]:
    seen: list = []
    read, ctl = stub_engineer(seen)
    read_srv, ctl_srv = TestServer(read), TestServer(ctl)
    await read_srv.start_server()
    await ctl_srv.start_server()
    client = await start(
        server.make_app(
            store,
            engineer_url=str(read_srv.make_url("/")),
            control_url=str(ctl_srv.make_url("/")),
        )
    )
    yield client, seen
    await client.close()
    await read_srv.close()
    await ctl_srv.close()


async def test_status_and_control_are_forwarded(proxied, caplog):
    client, seen = proxied
    caplog.set_level(logging.DEBUG)
    resp = await client.get("/api/engine/status", headers={"Cookie": "session=x"})
    assert resp.status == 200
    assert await resp.json() == {"state": "idle", "version": "stub"}
    assert "Set-Cookie" not in resp.headers
    assert "Cookie" not in seen[-1][1]

    resp = await client.get("/api/engine/control/config?full=1", headers={"Authorization": TOKEN})
    body = await resp.json()
    assert body == {
        "path": "/api/v1/config",
        "method": "GET",
        "query": "full=1",
        "body": "",
        "authorization": TOKEN,
    }
    assert resp.headers["ETag"] == '"c1"'
    resp = await client.post(
        "/api/engine/control/setup/fuel",
        json={"laps": 12},
        headers={"Authorization": TOKEN, "X-Forwarded-For": "1.2.3.4"},
    )
    assert resp.status == 201
    body = await resp.json()
    assert body["path"] == "/api/v1/setup/fuel" and json.loads(body["body"]) == {"laps": 12}
    assert "X-Forwarded-For" not in seen[-1][1]
    assert (await client.get("/api/engine/control/a//b")).status == 404
    assert TOKEN not in caplog.text and "not-a-real-admin-token" not in caplog.text


async def test_dash_websocket_is_pumped_both_ways(proxied):
    client, _ = proxied
    async with client.ws_connect("/api/engine/dash") as ws:
        got = [json.loads((await ws.receive(timeout=2)).data)["n"] for _ in range(3)]
        assert got == [1, 2, 3]
        await ws.send_str("hello")
        assert (await ws.receive(timeout=2)).data == "echo:hello"
        msg = await ws.receive(timeout=2)
        assert msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)


async def test_dash_without_an_upgrade_is_a_400_and_the_engineer_is_not_asked(proxied):
    client, seen = proxied
    resp = await client.get("/api/engine/dash")
    assert resp.status == 400 and "error" in await resp.json()
    assert not [name for name, _ in seen if name == "dash"]


async def test_dash_closes_the_engineer_side_when_the_browser_side_fails(proxied, monkeypatch):
    client, seen = proxied
    closed = []
    real_close = ClientWebSocketResponse.close

    async def close(self, **kwargs):
        closed.append(self)
        return await real_close(self, **kwargs)

    real_prepare = web.WebSocketResponse.prepare

    async def broken(self, request):
        if request.path != "/api/engine/dash":  # the stub engineer's side opens
            return await real_prepare(self, request)
        raise ConnectionResetError("the browser went away")

    monkeypatch.setattr(ClientWebSocketResponse, "close", close)
    monkeypatch.setattr(web.WebSocketResponse, "prepare", broken)
    resp = await client.get(
        "/api/engine/dash",
        headers={
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        },
    )
    assert resp.status == 500
    assert [name for name, _ in seen if name == "dash"] and len(closed) == 1


# AC6: no engineer


async def test_no_engineer_is_a_quick_502_and_data_still_works(api):
    t0 = time.monotonic()
    resp = await api.get("/api/engine/status")
    assert resp.status == 502 and "error" in await resp.json()
    assert time.monotonic() - t0 < 2
    assert (await api.get("/api/engine/control/config")).status == 502
    with pytest.raises(WSServerHandshakeError) as caught:
        await api.ws_connect("/api/engine/dash")
    assert caught.value.status == 502
    resp = await api.get("/healthz")
    assert resp.status == 200
    assert await resp.json() == {
        "ok": True,
        "version": __version__,
        "index": True,
        "engineer": False,
    }
    assert (await api.get("/api/v1/sessions")).status == 200


async def test_an_engineer_that_never_answers_is_a_502_within_2_s(store):
    """Accepted but never answered: the timeouts, not a refused connection."""
    with socket.socket() as hung:
        hung.bind(("127.0.0.1", 0))
        hung.listen(8)
        url = f"http://127.0.0.1:{hung.getsockname()[1]}"
        client = await start(server.make_app(store, engineer_url=url, control_url=url))
        try:
            t0 = time.monotonic()
            resp = await client.get("/api/engine/status")
            assert resp.status == 502 and time.monotonic() - t0 < 2
            t0 = time.monotonic()
            resp = await client.get("/healthz")
            assert resp.status == 200 and time.monotonic() - t0 < 1
            assert not (await resp.json())["engineer"]
        finally:
            await client.close()


async def test_health_on_a_new_volume_and_a_missing_one(tmp_path):
    client = await start(
        server.make_app(tmp_path, engineer_url=f"http://127.0.0.1:{closed_port()}")
    )
    try:
        body = await (await client.get("/healthz")).json()
        assert body["ok"] and not body["index"]
        assert (await (await client.get("/api/v1/sessions")).json())["sessions"] == []
    finally:
        await client.close()
    client = await start(server.make_app(tmp_path / "missing"))
    try:
        resp = await client.get("/healthz")
        assert resp.status == 503 and not (await resp.json())["ok"]
    finally:
        await client.close()


async def test_health_reports_a_live_engineer(proxied):
    client, _ = proxied
    assert (await (await client.get("/healthz")).json())["engineer"] is True


# AC7: the web app's files


@pytest.fixture
async def site(store, tmp_path) -> AsyncIterator[TestClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>pit wall</title>")
    (dist / "assets" / "app-3f9a.js").write_text("console.log(1)")
    (dist / "manifest.webmanifest").write_text("{}")
    (tmp_path / "secret.txt").write_text("not served")
    client = await start(server.make_app(store, static_dir=dist))
    yield client
    await client.close()


async def test_client_routes_get_index_html(site):
    for path in ("/", "/sessions/20261017-162118", "/?session=20261017-162118"):
        resp = await site.get(path)
        assert resp.status == 200, path
        assert "<title>pit wall</title>" in await resp.text()
        assert resp.headers["Cache-Control"] == "no-cache"
    resp = await site.get("/assets/app-3f9a.js")
    assert resp.status == 200 and "immutable" in resp.headers["Cache-Control"]
    resp = await site.get("/manifest.webmanifest")
    assert resp.headers["Cache-Control"] == "no-cache"
    assert (await site.get("/assets/app-0000.js")).status == 404
    assert (await site.get("/%2E%2E/secret.txt")).status in (200, 404)
    assert "not served" not in await (await site.get("/%2E%2E/secret.txt")).text()
    resp = await site.get("/api/v1/nope")
    assert resp.status == 404 and "error" in await resp.json()
    assert (await site.get("/api/v1/sessions")).status == 200


async def test_no_index_html_is_a_404(store, tmp_path):
    client = await start(server.make_app(store, static_dir=tmp_path))
    try:
        assert (await client.get("/sessions/x")).status == 404
    finally:
        await client.close()


# AC8, R8: reads in a thread


async def test_the_list_does_not_wait_for_traces(api, store, monkeypatch):
    sid = data.list_sessions(store)[0].session_id
    release = threading.Event()
    started = threading.Semaphore(0)
    real = data.lap_trace

    def slow_trace(*args, **kwargs):
        started.release()
        release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(data, "lap_trace", slow_trace)
    traces = [
        asyncio.create_task(api.get(f"/api/v1/sessions/{sid}/laps/{lap}/trace")) for lap in (1, 2)
    ]
    for _ in range(2):
        assert await asyncio.to_thread(started.acquire, True, 5)
    resp = await asyncio.wait_for(api.get("/api/v1/sessions"), 2)
    assert resp.status == 200
    assert not any(t.done() for t in traces), "the list came back while both traces were reading"
    release.set()
    assert [(await t).status for t in traces] == [200, 200]


# R9, R9a: ETags and gzip


async def test_etag_until_the_engineer_writes(api, store):
    resp = await api.get("/api/v1/sessions")
    etag = resp.headers["ETag"]
    assert etag.startswith('W/"') and resp.headers["Cache-Control"] == "no-cache"
    resp = await api.get("/api/v1/sessions", headers={"If-None-Match": etag})
    assert resp.status == 304 and resp.headers["ETag"] == etag

    sid = data.list_sessions(store)[0].session_id
    trace = await api.get(f"/api/v1/sessions/{sid}/laps/1/trace")
    trace_etag = trace.headers["ETag"]

    # the engineer commits: the index moves on
    db = sqlite3.connect(store / "index.sqlite")
    db.execute("UPDATE sessions SET best_lap_ms = best_lap_ms")
    db.commit()
    db.close()
    later = time.time() + 5
    os.utime(store / "index.sqlite", (later, later))
    resp = await api.get("/api/v1/sessions", headers={"If-None-Match": etag})
    assert resp.status == 200 and resp.headers["ETag"] != etag
    # a lap file does not change once indexed: its trace is still current
    resp = await api.get(
        f"/api/v1/sessions/{sid}/laps/1/trace", headers={"If-None-Match": trace_etag}
    )
    assert resp.status == 304


async def test_large_json_is_gzipped(api, store):
    sid = data.list_sessions(store)[0].session_id
    resp = await api.get(
        f"/api/v1/sessions/{sid}/laps/1/trace",
        headers={"Accept-Encoding": "gzip"},
        auto_decompress=False,
    )
    assert resp.headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(await resp.read()))["lap"] == 1
    small = await api.get("/api/v1/sessions/nope", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in small.headers
    plain_resp = await api.get(
        f"/api/v1/sessions/{sid}/laps/1/trace", headers={"Accept-Encoding": "identity"}
    )
    assert "Content-Encoding" not in plain_resp.headers


# errors


async def test_a_busy_index_is_a_503_and_a_bug_a_500(api, monkeypatch, caplog):
    def busy(_data_dir):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(data, "list_sessions", busy)
    resp = await api.get("/api/v1/sessions?track=busy")
    assert resp.status == 503 and "busy" in (await resp.json())["error"]

    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(data, "lap_file", broken)
    with caplog.at_level(logging.ERROR):
        resp = await api.get("/api/v1/sessions/20261015-180019/laps/1/trace")
    assert resp.status == 500 and (await resp.json()) == {"error": "internal server error"}
    assert "boom" in caplog.text


# the command


def test_pitwall_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run(app, **kwargs):
        seen["app"], seen["kwargs"] = app, kwargs

    monkeypatch.setattr(server.web, "run_app", fake_run)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GT7_ENGINEER_URL", "http://engineer:9850/")
    monkeypatch.setenv("GT7_PITWALL_PORT", "9999")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("x")
    assert main(["pitwall", "--static", str(tmp_path / "dist")]) == 0
    assert seen["kwargs"]["port"] == 9999 and seen["kwargs"]["host"] == "0.0.0.0"
    assert seen["app"][server.ENGINEER] == "http://engineer:9850"
    assert seen["app"][server.CONTROL] == "http://those-who-run:9851"
    assert main(["pitwall", "--port", "9853", "--address", "127.0.0.1"]) == 0
    assert seen["kwargs"]["port"] == 9853 and seen["kwargs"]["host"] == "127.0.0.1"
    assert main(["pitwall", "--static", str(tmp_path / "nothing")]) == 2
    monkeypatch.setenv("GT7_PITWALL_PORT", "not-a-port")
    assert main(["pitwall"]) == 2


def test_static_from_the_environment(monkeypatch, tmp_path):
    """The pitwall image sets GT7_PITWALL_STATIC=/app/web (#237 R9); --static wins."""
    seen = {}
    monkeypatch.setattr(server.web, "run_app", lambda app, **kw: seen.update(app=app))
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
    for name in ("image", "flag"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "index.html").write_text(name)
    monkeypatch.setenv("GT7_PITWALL_STATIC", str(tmp_path / "image"))
    assert main(["pitwall"]) == 0
    assert seen["app"][server.STATIC] == (tmp_path / "image").resolve()
    assert main(["pitwall", "--static", str(tmp_path / "flag")]) == 0
    assert seen["app"][server.STATIC] == (tmp_path / "flag").resolve()
    monkeypatch.setenv("GT7_PITWALL_STATIC", str(tmp_path / "nothing"))
    assert main(["pitwall"]) == 2


# The engineer extra's packages: the pitwall image has none of them.
NOT_IN_THE_PITWALL_IMAGE = (
    "discord",
    "piper",
    "onnxruntime",
    "gt_telem",
    "prometheus_client",
    "numpy",
)


def test_pitwall_needs_only_the_core_install(tmp_path):
    """The slim image (#237 R9) installs aiohttp, DuckDB and PyYAML only: the CLI
    loads every command module, so none may import an engineer package at the top,
    and the pit wall serves its data with them all gone."""
    code = f"""
import sys
for name in {NOT_IN_THE_PITWALL_IMAGE!r}:
    sys.modules[name] = None  # import fails, as when the package is not installed
from those_who_run.cli import build_parser
from those_who_run.pitwall import data, server
build_parser().parse_args(["pitwall"])
server.make_app(sys.argv[1])
print(len(data.list_sessions(__import__("pathlib").Path(sys.argv[1]))))
"""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0"


def test_access_log_has_the_path_only(caplog):
    class Req:
        remote, method, path = "127.0.0.1", "GET", "/api/engine/control/config"
        path_qs = path + "?token=leak"

    class Resp:
        status = 200

    with caplog.at_level(logging.DEBUG, logger="those_who_run.pitwall.server"):
        server.AccessLog(logging.getLogger("x"), "").log(Req(), Resp(), 0.001)  # type: ignore[arg-type]
    assert "/api/engine/control/config" in caplog.text and "leak" not in caplog.text
