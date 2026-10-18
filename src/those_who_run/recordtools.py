"""What is in a recording: one line per session, for matching drives to notes.

Each outing recording (``GT7_RECORD_DIR``) is replayed through the engine and a
throwaway session store, so the answer is exactly what the live engineer would
have stored: session kind, track, car, laps, best lap and how it ended (the
flag, a quit, a restart, in a pause the recording stops in, or still open when
it stops). The minutes are the time not paused (#229).

Frames carry the PS5 link's own clock, which is not the time of day (it reads
as March 1970), so the throwaway store is given wall-clock time instead: the
outing's start from the file name, plus the time since the first frame after
the menu (the frame the recorder named the file on). Session ids, start times
and cards then match the ones the live engineer stored.
"""

from __future__ import annotations

import calendar
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import outing_order, read_recording
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import Phase, RaceState, race_restarted
from those_who_run.store import SessionStore


@dataclass(frozen=True, slots=True)
class RecordedSession:
    offset_secs: float  # from the first frame of the recording
    minutes: float  # pauses left out
    ended: str  # flag | quit | restart | paused | open
    summary: dict[str, Any]

    def line(self) -> str:
        s = self.summary
        card = build_card(s)
        what = card.title if card else f"{s.get('type', 'session')}, no full lap"
        result = card.description if card else ""
        kind = (s.get("session_kind") or {}).get("kind", "unknown")
        start = (s.get("session_kind") or {}).get("start", "unknown")
        best_field = dict(card.fields).get("Best lap") if card else None
        best = f"best {best_field}" if best_field else ""
        mins, secs = divmod(int(self.offset_secs), 60)
        started = s.get("started_at")
        parts = [
            time.strftime("%H:%M", time.localtime(started)) if started else "",
            f"+{mins:d}:{secs:02d}",
            f"{self.minutes:4.1f} min",
            what,
            result,
            s.get("car_name") or "",
            best,
            f"{kind}/{start}",
            self.ended,
        ]
        return "  ".join(p for p in parts if p)


def recording_started_at(path: Path) -> float:
    """Wall-clock time the outing began. ``OutingRecorder`` names each file after it,
    in UTC (``20261017-162118.jsonl.gz``, or ``20261017-162118-2.jsonl.gz`` for a
    second outing in the same second; the NUC's container clock is UTC, so files
    from before the recorder said so are UTC too); any other file falls back to its
    modification time, which is close enough to date a card."""
    stamp = outing_order(path)[0]  # without a -N suffix
    try:
        return calendar.timegm(time.strptime(stamp, "%Y%m%d-%H%M%S"))
    except ValueError:
        return path.stat().st_mtime


def summarise_recording(path: Path) -> tuple[list[RecordedSession], bool]:
    """The sessions in a recording, and whether the file ended cleanly."""
    out: list[RecordedSession] = []
    pending: list[dict[str, Any]] = []
    first_t: float | None = None
    anchor_t: float | None = None  # the first frame after the menu: the file's start
    started_at = recording_started_at(path)
    clock_t = [started_at]
    complete = True
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp), clock=lambda: clock_t[0], on_end=pending.append)
        engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
        prev: RaceState | None = None
        starts: list[float] = []

        def collect(ended: str, at: float) -> None:
            for s in pending:
                begun = starts.pop(0) if starts else at
                driving = s.get("driving_ms")
                minutes = (at - begun) / 60 if driving is None else driving / 60000
                ended = "paused" if s.get("ended_paused") else ended
                out.append(RecordedSession(begun - (first_t or at), minutes, ended, s))
            pending.clear()

        recording = read_recording(path)
        try:
            for state in recording:
                first_t = state.t if first_t is None else first_t
                if anchor_t is None and state.phase is not Phase.MENU:
                    anchor_t = state.t
                clock_t[0] = started_at + state.t - (anchor_t if anchor_t is not None else state.t)
                had_session = store.session is not None
                engine.process(state)
                if pending:
                    ended = "restart" if race_restarted(prev, state) else "quit"
                    ended = "flag" if pending[0].get("finished") else ended
                    collect(ended, state.t)
                if store.session is not None and (not had_session or len(starts) == 0):
                    starts.append(state.t)
                prev = state
            # False when the outing was still being written, or cut off by a crash.
            complete = recording.complete
            if store.session is not None and prev is not None:
                engine.close_session()
                collect("open", prev.t)
        finally:
            store.close()  # on every path: it owns a writer thread
    return out, complete


def list_recordings(directory: Path) -> list[Path]:
    """Recordings in ``directory``, oldest outing first."""
    return sorted(
        (p for p in Path(directory).iterdir() if p.name.endswith((".jsonl", ".jsonl.gz"))),
        key=outing_order,
    )
