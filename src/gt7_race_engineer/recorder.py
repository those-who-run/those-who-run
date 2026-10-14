"""Write one JSON per completed lap and a summary per race session."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gt7_race_engineer.state import RaceState, lap_completed, lap_time_posted

log = logging.getLogger(__name__)


@dataclass
class Session:
    session_id: str
    dir: Path
    started_at: float
    track_id: int | None
    total_laps: int
    fuel_at_start: float
    lap_start_fuel: float
    laps: list[dict[str, Any]] = field(default_factory=list)
    pending_lap: dict[str, Any] | None = None


class LapRecorder:
    def __init__(self, data_dir: Path, clock: Any = time.time) -> None:
        self.data_dir = Path(data_dir)
        self.clock = clock
        self.session: Session | None = None

    def start_session(self, state: RaceState) -> Session:
        base = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock()))
        session_id, n = base, 1
        while (self.data_dir / "sessions" / session_id).exists():
            n += 1
            session_id = f"{base}-{n}"
        sdir = self.data_dir / "sessions" / session_id
        sdir.mkdir(parents=True)
        self.session = Session(
            session_id=session_id,
            dir=sdir,
            started_at=self.clock(),
            track_id=state.track_id,
            total_laps=state.total_laps,
            fuel_at_start=state.fuel_level,
            lap_start_fuel=state.fuel_level,
        )
        log.info(
            "session %s started (track %s, %s laps)", session_id, state.track_id, state.total_laps
        )
        return self.session

    def observe(self, prev: RaceState | None, state: RaceState) -> None:
        s = self.session
        if s is None:
            return
        if lap_completed(prev, state):
            assert prev is not None
            s.pending_lap = {
                "lap": prev.current_lap,
                "fuel_start": s.lap_start_fuel,
                "fuel_end": state.fuel_level,
                "fuel_used": round(s.lap_start_fuel - state.fuel_level, 3),
                "track_id": state.track_id,
                "recorded_at": self.clock(),
            }
            s.lap_start_fuel = state.fuel_level
            # In practice the lap time lands in the same frame; if it already
            # has, finish the record now rather than waiting for a change.
            if lap_time_posted(prev, state):
                self._complete_lap(state)
        elif s.pending_lap is not None and lap_time_posted(prev, state):
            self._complete_lap(state)

    def _complete_lap(self, state: RaceState) -> None:
        s = self.session
        if s is None or s.pending_lap is None:
            return
        lap = s.pending_lap
        lap["lap_time_ms"] = state.last_lap_ms
        lap["best_lap_ms"] = state.best_lap_ms
        s.pending_lap = None
        s.laps.append(lap)
        path = s.dir / f"lap-{lap['lap']:02d}.json"
        path.write_text(json.dumps(lap, indent=2), encoding="utf-8")

    def end_session(self, state: RaceState) -> Path | None:
        s = self.session
        if s is None:
            return None
        if s.pending_lap is not None and state.last_lap_ms > 0:
            self._complete_lap(state)
        summary = {
            "session_id": s.session_id,
            "started_at": s.started_at,
            "ended_at": self.clock(),
            "track_id": s.track_id,
            "total_laps": s.total_laps,
            "laps_completed": len(s.laps),
            "best_lap_ms": state.best_lap_ms if state.best_lap_ms > 0 else None,
            "fuel_at_start": s.fuel_at_start,
            "fuel_at_end": state.fuel_level,
            "fuel_used": round(sum(lap["fuel_used"] for lap in s.laps), 3),
            "laps": s.laps,
        }
        path = s.dir / "summary.json"
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        log.info("session %s ended after %d laps", s.session_id, len(s.laps))
        self.session = None
        return path
