"""What is in a recording: one line per session, for matching drives to notes.

Each outing recording (``GT7_RECORD_DIR``) is replayed through the engine and a
throwaway session store, so the answer is exactly what the live engineer would
have stored: session kind, track, car, laps, best lap and how it ended (the
flag, a quit, a restart, or still open when the recording stops).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES
from those_who_run.engine import Engine
from those_who_run.replay import read_recording
from those_who_run.results import build_card
from those_who_run.rules import build_rules
from those_who_run.state import RaceState, race_restarted
from those_who_run.store import SessionStore


@dataclass(frozen=True, slots=True)
class RecordedSession:
    offset_secs: float  # from the first frame of the recording
    minutes: float
    ended: str  # flag | quit | restart | open
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
        parts = [
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


def summarise_recording(path: Path) -> tuple[list[RecordedSession], bool]:
    """The sessions in a recording, and whether the file ended cleanly."""
    out: list[RecordedSession] = []
    pending: list[dict[str, Any]] = []
    first_t: float | None = None
    clock_t = [0.0]
    complete = True
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp), clock=lambda: clock_t[0], on_end=pending.append)
        engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
        prev: RaceState | None = None
        starts: list[float] = []

        def collect(ended: str, at: float) -> None:
            for s in pending:
                begun = starts.pop(0) if starts else at
                out.append(RecordedSession(begun - (first_t or at), (at - begun) / 60, ended, s))
            pending.clear()

        try:
            for state in read_recording(path):
                first_t = state.t if first_t is None else first_t
                clock_t[0] = state.t
                had_session = store.session is not None
                engine.process(state)
                if pending:
                    ended = "restart" if race_restarted(prev, state) else "quit"
                    ended = "flag" if pending[0].get("finished") else ended
                    collect(ended, state.t)
                if store.session is not None and (not had_session or len(starts) == 0):
                    starts.append(state.t)
                prev = state
        except EOFError:
            complete = False  # the outing was still being written
        if store.session is not None and prev is not None:
            store.end_session(prev)
            collect("open", prev.t)
        store.close()
    return out, complete


def list_recordings(directory: Path) -> list[Path]:
    return sorted(p for p in Path(directory).iterdir() if p.name.endswith((".jsonl", ".jsonl.gz")))
