"""What the engineer is doing right now: ``GET /api/v1/status`` on 9850 (#292).

The pit wall shows it in its header and pins the live session to the top of its
list; a browser reaches it as ``/api/engine/status`` through the pit wall's
proxy (ADR 0003 point 6). Port 9850 is read-only with no token (ADR 0001 point
3), so the body holds no token, no secret and no PS5 or Discord id: only what
the results card shows anyone, and the position only where the card shows it.

It is built from what the engine already holds, between frames, with no I/O
and in constant time, so a poll never holds up the telemetry loop. The models
are plain dataclasses (no pydantic), and :data:`ROUTES` puts them in the pit
wall's schema (:func:`those_who_run.openapi.spec`, ``web/openapi.json``). No
engine imports at run time: the pit wall imports this module for the schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from those_who_run.cars import car_name
from those_who_run.openapi import Route, doc
from those_who_run.results import position_shown
from those_who_run.sessionkind import Kind
from those_who_run.state import Phase

if TYPE_CHECKING:
    from those_who_run.engine import Engine
    from those_who_run.store import Session

# ``idle`` exactly when /healthz says ``idle`` (#272). A demo or a replay keeps
# driving frames coming, so it is busy, as a drive is.
Activity = Literal["idle", "driving", "paused", "replay", "demo"]


@dataclass(frozen=True, slots=True)
class TrackSeen:
    """The track as the detector has placed it so far."""

    id: int | None = doc("GT7's track id; null when only the circuit is known (Fuji's layouts)")
    name: str | None = doc("The track's name, or the circuit's")
    sure: bool = doc("The detector is sure (probable or confirmed), as the pit wall's Track")


@dataclass(frozen=True, slots=True)
class LiveSession:
    """The session the engineer has open, as of the last frame."""

    id: str = doc('The session id, as the pit wall lists it: "20261017-162118"')
    kind: Kind = doc('Session kind key (sessionkind.Kind), "unknown" until it is known')
    track: TrackSeen | None = doc("Where it is being driven; null until the detector has a match")
    car: str | None = doc("The car's name; null when GT7 sent no car code")
    lap: int | None = doc("The lap of the last driving frame")
    laps_total: int | None = doc("Laps in the race; null for a timed session")
    position: int | None = doc("Position now; null where the results card hides it")
    cars: int | None = doc("Cars in the field; null where the results card hides the position")


@dataclass(frozen=True, slots=True)
class TelemetryLink:
    """The PS5's telemetry feed."""

    connected: bool = doc("Packets arrived within GT7_TELEMETRY_TIMEOUT_SECS")
    last_packet_age_s: float | None = doc("Seconds since the last frame; null before the first")


@dataclass(frozen=True, slots=True)
class EngineStatus:
    """What the engineer is doing right now (#292)."""

    version: str = doc("The engineer's version")
    started_at: float = doc("Unix time the engineer started")
    activity: Activity = doc("What it is doing; idle exactly when its /healthz says idle")
    idle_secs: float = doc("Seconds since the last driving frame; 0 while driving")
    telemetry: TelemetryLink = doc("The telemetry feed")
    voice_connected: bool = doc("Joined to the Discord voice channel")
    session: LiveSession | None = doc("The open session; null when none is open")

    def body(self) -> dict[str, Any]:
        return asdict(self)


# For the pit wall's schema (``openapi.spec``): the route as the browser
# reaches it, through the pit wall's proxy (ADR 0003 point 6).
ROUTES: tuple[Route, ...] = (
    Route(
        "GET",
        "/api/engine/status",
        "What the engineer is doing right now, from its /api/v1/status",
        EngineStatus,
        "getEngineStatus",
        errors=(502,),
        tag="engineer",
    ),
)


def activity(engine: Engine, idle: bool) -> Activity:
    """``idle`` from /healthz; otherwise a replay or a demo the engine is
    ignoring, a pause, or driving. A start the engine is still judging (at most
    ``DriverCheck.window_secs``) is driving until it knows otherwise."""
    if idle:
        return "idle"
    if engine.replay:
        return engine.ignoring
    if engine.prev is not None and engine.prev.phase is Phase.PAUSED:
        return "paused"
    return "driving"


def live_session(engine: Engine, session: Session | None) -> LiveSession | None:
    """The store's open session as the engine last saw it: lap and position from
    the last driving frame (the frame just processed, mid-race)."""
    if session is None:
        return None
    frame = engine.last_driving or engine.prev
    kind, track = engine.kind, engine.track
    shown = frame is not None and position_shown(kind.record())
    return LiveSession(
        id=session.session_id,
        kind=kind.kind,
        track=None
        if track is None
        else TrackSeen(track.track_id, track.name, track.confidence in ("probable", "confirmed")),
        # Cached: the store named the car when it opened the session.
        car=car_name(session.car_code),
        lap=frame.current_lap if frame is not None else None,
        laps_total=(frame.total_laps if frame is not None else session.total_laps) or None,
        # An early frame can carry 0 or -1 for either (RaceState.position is
        # None then): null, as where the card hides them.
        position=frame.position if shown and frame is not None else None,
        cars=frame.total_cars if shown and frame is not None and frame.total_cars > 0 else None,
    )
