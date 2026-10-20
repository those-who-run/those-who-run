"""The pit wall API's response bodies, and its route list for the schema (#236).

Values, not card strings (ADR 0004 point 6): times in milliseconds, positions
and counts as numbers, flags as booleans. The browser formats them. Labels
whose logic lives in Python (the session kind's label, the track's name,
whether a position means anything) come as strings or booleans beside the
values, and the card's ``title`` and ``result`` stay for the results cards.

``LapRow`` and ``Trace`` are what ``data.py`` returns, so the page, the API and
the schema share one declaration. Every field here is in the JSON, in this
order; a property (``LapRow.time``) is not. Add a route to ``ROUTES`` when you
add it to ``server.py``: a test checks that every route the app has is here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from those_who_run.openapi import Param, Route, doc
from those_who_run.results import race_time

MAX_POINTS = 10000  # the most a trace may ask for: a lap at 60 Hz is about 6,000 frames
DEFAULT_POINTS = 1500


@dataclass(frozen=True, slots=True)
class Track:
    """The track as the detector placed it."""

    id: int | None = doc("GT7's track id, when the detector named one, sure or not")
    name: str = doc('The name to show: "Unknown track" when the detector is not sure')
    sure: bool = doc("The detector is sure (probable or confirmed): same-track compare uses it")
    evidence: str | None = doc("Why the detector placed it there, in a sentence")


@dataclass(frozen=True, slots=True)
class Session:
    """One session: what its results card is built from, as values."""

    session_id: str = doc('The session id, "20261017-162118"')
    title: str = doc('The results card title, "Circuit Gilles Villeneuve · 12-lap race"')
    result: str = doc('The results card line, "🚩 Finished P3 of 20 in 21:06.182"')
    started_at: float = doc("Unix time the session started")
    ended_at: float | None = doc("Unix time it ended; null while it is still open")
    closed: bool = doc("summary.json is written: the session has ended")
    kind: str = doc('Session kind key (sessionkind.Kind), "unknown" when not recorded')
    kind_label: str = doc('The kind as the card names it: "12-lap race", "time trial"')
    track: Track = doc("Where it was driven")
    car: str | None = doc("The car's name, null when GT7 sent an unknown code")
    car_code: int | None = doc("GT7's car code")
    finished: bool = doc("The race was finished: GT7 showed the result")
    final_position: int | None = doc("Position at the end; show it only if position_shown")
    total_cars: int | None = doc("Cars in the field")
    position_shown: bool = doc("A position means something here: a field GT7 flags")
    total_time_ms: int | None = doc("Race time of a finished race")
    best_lap_ms: int | None = doc("The best lap as the card picks it (GT7's own best first)")
    best_lap_no: int | None = doc("Which lap that was")
    laps_completed: int = doc("Laps completed")
    total_laps: int = doc("Laps in the race; 0 for a timed or open session")
    fuel_use: bool | None = doc("Fuel use is on; false means the fuel figures mean nothing")
    fuel_used: float | None = doc("Fuel burned over the session, in GT7's units (refuels left out)")
    fuel_capacity: float | None = doc("The tank, in GT7's units: fuel as a share of it")
    fuel_by_stint: list[float] = doc("Fuel burned in each stint, as the card's fuel line has it")
    pit_stops: int = doc("Pit stops made")
    driving_ms: int | None = doc("Time not paused (#229); null for older and open sessions")
    paused_ms: int | None = doc("Time paused (#229)")
    joined_on_lap: int | None = doc("The engineer joined part way, on this lap (#265)")
    continued: bool = doc("Continued across an engineer restart (#273)")
    restart_laps: list[int] = doc("The laps an engineer restart fell in (#273)")


@dataclass(frozen=True, slots=True)
class LapRow:
    """One lap in the lap table."""

    lap: int = doc("Lap number")
    time_ms: int | None = doc("Lap time; null for a partial lap or an untimed crossing")
    complete: bool = doc("The lap was driven to the line")
    fuel_start: float | None = doc("Fuel at the lap's start, GT7's units")
    fuel_end: float | None = doc("Fuel at its end")
    fuel_used: float | None = doc("Fuel used over the lap (negative when refuelled)")
    position: int | None = doc("Position at the line; null where a position means nothing")
    frames: int = doc("Telemetry frames stored for the lap")
    file: str = doc("The lap's Parquet file in the session directory")
    top_speed_kph: float | None = doc("Top speed; null when the lap file is missing")
    pit: bool = doc("The in-lap of a pit stop")
    out_lap: bool = doc("The lap after a pit stop")
    invalid: bool = doc("No lap time to compare: a partial lap or an untimed crossing")
    best: bool = doc("The session's best lap, as the card picks it")
    fuel_use: bool = doc(
        "False when the session's fuel use is off: its fuel means nothing", default=True
    )
    restart: bool = doc("An engineer restart fell in this lap (#273): partly seen", default=False)
    clean: bool = doc(
        "Counts towards an average: not pit, out, partial or restart (#298)", init=False
    )

    def __post_init__(self) -> None:
        clean = not (self.pit or self.out_lap or self.invalid or self.restart)
        object.__setattr__(self, "clean", clean)  # frozen: set once, from the flags

    @property
    def time(self) -> str:
        return race_time(self.time_ms) if self.time_ms else ""

    @property
    def flags(self) -> str:
        """Short text for the table: "best", "pit", "out", "partial", "no time"."""
        out = []
        if self.best:
            out.append("best")
        if self.pit:
            out.append("pit")
        if self.out_lap:
            out.append("out")
        if self.restart:
            out.append("restart")
        if self.invalid:
            out.append("partial" if not self.complete else "no time")
        return ", ".join(out)


@dataclass(frozen=True, slots=True)
class Trace:
    """One lap's channels against time from the lap start, for lap compare and
    its track map. Thinned to the points asked for, keeping each stretch's
    slowest and fastest frame, so braking points and top speeds survive, and
    both frames either side of a position jump (the pit cut-scene)."""

    session_id: str = doc("The session")
    lap: int = doc("The lap")
    t: tuple[float, ...] = doc("Seconds from the lap's first frame, gaps capped at 0.1 s")
    speed_kph: tuple[float, ...] = doc("Speed")
    throttle_pct: tuple[float, ...] = doc("Throttle, 0 to 100")
    brake_pct: tuple[float, ...] = doc("Brake, 0 to 100")
    gear: tuple[int, ...] = doc("Gear; 0 is neutral or reverse")
    rpm: tuple[float, ...] = doc("Engine speed")
    x: tuple[float, ...] = doc("The car's position on GT7's x axis, in metres, to 0.1 m")
    z: tuple[float, ...] = doc("The car's position on GT7's z axis; with x, the lap in plan")

    def __len__(self) -> int:
        return len(self.t)


_COUNT = "Sessions this value would leave, with the other filters applied (not its own)"


@dataclass(frozen=True, slots=True)
class FilterOption:
    value: str = doc("The value, as its query parameter takes it")
    count: int = doc(_COUNT)


@dataclass(frozen=True, slots=True)
class KindOption:
    value: str = doc("The kind key, as ?kind= takes it")
    label: str = doc("The kind's name")
    count: int = doc(_COUNT)


@dataclass(frozen=True, slots=True)
class FilterOptions:
    """The values each filter can take, from every session, each with a count."""

    track: list[FilterOption] = doc("Track names, as Session.track.name has them")
    car: list[FilterOption] = doc("Car names")
    kind: list[KindOption] = doc("Session kinds")


@dataclass(frozen=True, slots=True)
class SessionList:
    """Sessions newest first, filtered, and what the filters can take."""

    sessions: list[Session] = doc("The sessions that match, newest first")
    options: FilterOptions = doc("Filter values from every session, not just these")
    total: int = doc("Sessions in the store")
    matched: int = doc("Sessions that match the filters: the length of sessions")


@dataclass(frozen=True, slots=True)
class SameTrack:
    sessions: list[Session] = doc("Other sessions at the same track, newest first")


@dataclass(frozen=True, slots=True)
class LapList:
    session_id: str = doc("The session")
    laps: list[LapRow] = doc("Its laps in order")


@dataclass(frozen=True, slots=True)
class Health:
    """The pit wall's health: unhealthy only when the data directory can't be read."""

    ok: bool = doc("The data directory is readable")
    version: str = doc("The pit wall's version")
    index: bool = doc("The index exists: false on a new volume until the engineer writes")
    engineer: bool = doc("The engineer answered; down never makes the pit wall unhealthy")


_SESSION_ID = Param("id", "path", 'The session id, "20261017-162118"')
_LAP = Param("lap", "path", "The lap number", {"type": "integer", "minimum": 0})


def _filter(name: str, what: str) -> Param:
    return Param(name, "query", f"Only sessions with this {what}; empty matches all")


def _date(name: str, when: str) -> Param:
    return Param(
        name,
        "query",
        f'Only sessions started {when} this day, in tz (else the pit wall\'s zone): "2026-10-17"',
        {"type": "string", "format": "date"},
    )


# Every route the app has, beside the models it returns. The WebSocket and the
# control pass-through are not here: their shapes belong to the engineer.
ROUTES: tuple[Route, ...] = (
    Route(
        "GET",
        "/api/v1/sessions",
        "Sessions, newest first, with the card's facts as values",
        SessionList,
        "listSessions",
        params=(
            _filter("track", "track name"),
            _filter("car", "car name"),
            _filter("kind", "session kind key"),
            _date("from", "on or after"),
            _date("to", "on or before"),
            Param(
                "tz",
                "query",
                'The time zone from and to are days in, an IANA name: "Europe/Dublin".'
                " The browser's own; without it, the pit wall's zone (UTC in its container)",
            ),
        ),
        errors=(400, 503),
        etag=True,
    ),
    Route(
        "GET",
        "/api/v1/sessions/{id}",
        "One session",
        Session,
        "getSession",
        params=(_SESSION_ID,),
        errors=(404, 503),
        etag=True,
    ),
    Route(
        "GET",
        "/api/v1/sessions/{id}/laps",
        "A session's lap table",
        LapList,
        "listLaps",
        params=(_SESSION_ID,),
        errors=(404, 503),
        etag=True,
    ),
    Route(
        "GET",
        "/api/v1/sessions/{id}/laps/{lap}/trace",
        "A lap's speed, throttle, brake, gear and RPM against time",
        Trace,
        "getTrace",
        params=(
            _SESSION_ID,
            _LAP,
            Param(
                "points",
                "query",
                "The most points to send",
                {"type": "integer", "minimum": 1, "maximum": MAX_POINTS, "default": DEFAULT_POINTS},
            ),
        ),
        errors=(400, 404, 503),
        etag=True,
    ),
    Route(
        "GET",
        "/api/v1/sessions/{id}/same-track",
        "The other sessions at this session's track, for lap compare",
        SameTrack,
        "listSameTrack",
        params=(_SESSION_ID,),
        errors=(404, 503),
        etag=True,
    ),
    Route("GET", "/api/v1/openapi.json", "This schema", dict[str, Any], "getOpenApi"),
    Route("GET", "/healthz", "The pit wall's health", Health, "getHealth", unhealthy=True),
)
