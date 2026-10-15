"""Brief the driver once the race is under way: track, distance, grid slot.

Spoken a couple of seconds after the first driving frame, because GT7 takes a
frame or two to settle the grid position (qualifying reported P20 and then P1 on
consecutive frames, 2026-10-14). The track comes from the detector through
``on_track``. On a rolling start it is usually known before the lights; on a
standing start it is not, so the name is spoken on its own once the detector
names a track. A changed verdict later in the race is spoken again; a confidence
upgrade for the same track is not.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import RaceState
from those_who_run.trackdetect import CONFIDENCE_RANK, TrackMatch
from those_who_run.verbalise import laps_words, number_words, tidy_sentence, track_words


class StartBriefRule(Rule):
    name = "start_brief"
    default_priority = 8

    def reset(self) -> None:
        self.settle_secs = float(self.cfg.get("settle_secs", 2.0))
        self.announce_track = bool(self.cfg.get("announce_track", True))
        min_confidence = str(self.cfg.get("min_confidence", "probable"))
        self.min_rank = CONFIDENCE_RANK.get(min_confidence, CONFIDENCE_RANK["probable"])
        self.started_at: float | None = None
        self.start_lap = 0
        self.briefed = False
        self.track: TrackMatch | None = None
        self.track_spoken_id: int | None = None
        self.pending_track: TrackMatch | None = None

    def on_track(self, match: TrackMatch) -> None:
        if match.track_id is None or CONFIDENCE_RANK[match.confidence] < self.min_rank:
            return
        self.track = match
        if self.briefed and self.announce_track and match.track_id != self.track_spoken_id:
            # A callout needs a frame time, so it is built on the next evaluated frame.
            self.pending_track = match

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if self.started_at is None:
            self.started_at = state.t
            self.start_lap = state.current_lap
        out: list[Callout] = []
        if self.pending_track is not None:
            match, self.pending_track = self.pending_track, None
            if match.track_id != self.track_spoken_id:
                self.track_spoken_id = match.track_id
                out.append(self.callout(self._track_phrase(match), state))
        if self.briefed or state.t - self.started_at < self.settle_secs:
            return out

        self.briefed = True
        parts: list[str] = []
        if self.track is not None:
            parts.append(self._track_phrase(self.track))
            self.track_spoken_id = self.track.track_id
        if state.has_lap_count:
            if self.start_lap <= 1:
                parts.append(
                    self.template("template_laps", "{laps}.").format(
                        laps=laps_words(state.total_laps)
                    )
                )
            elif state.laps_left:
                # Joined mid-race (the engineer was restarted): say what is left.
                parts.append(
                    self.template("template_laps_to_go", "{laps} to go.").format(
                        laps=laps_words(state.laps_left)
                    )
                )
        elif _has_field(state):
            # No lap total and other cars: a timed race (or qualifying, which GT7
            # reports the same way). A lone car with no lap total is practice.
            parts.append(self.template("template_timed", "Timed race."))
        if _has_field(state) and state.position is not None:
            parts.append(
                self.template("template_position", "P {p} of {total}.").format(
                    p=number_words(state.position), total=number_words(state.total_cars)
                )
            )
        if parts:
            out.append(self.callout(_sentences(parts), state))
        return out

    def _track_phrase(self, match: TrackMatch) -> str:
        name = track_words(match.name or f"track {match.track_id}")
        return tidy_sentence(self.template("template_track", "{track}.").format(track=name))


def _has_field(state: RaceState) -> bool:
    return state.is_race and state.total_cars > 1


def _sentences(parts: list[str]) -> str:
    """Each part is a sentence of its own; templates built from number words start lowercase."""
    return tidy_sentence(" ".join(p[:1].upper() + p[1:] for p in parts if p))
