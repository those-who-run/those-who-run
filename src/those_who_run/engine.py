"""The engine: turns a stream of RaceState into callouts, lap records and metrics."""

from __future__ import annotations

import logging

from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.metrics import Metrics
from those_who_run.rules.base import Rule
from those_who_run.rules.fuel import FuelRule
from those_who_run.sessionkind import SessionDetector, SessionKind
from those_who_run.state import (
    Phase,
    RaceState,
    race_ended,
    race_restarted,
    race_started,
    racing_frame,
)
from those_who_run.store import SessionStore
from those_who_run.trackdetect import CONFIDENCE_RANK, TrackDetector, TrackMatch

log = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        rules: list[Rule],
        queue: CalloutQueue,
        recorder: SessionStore | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.rules = rules
        self.queue = queue
        self.recorder = recorder
        self.metrics = metrics
        self.prev: RaceState | None = None
        self.races_started = 0
        self.tracks = TrackDetector()
        self.track: TrackMatch | None = None  # best match applied to the open session
        self.kinds = SessionDetector()
        self.last_driving: RaceState | None = None  # last IN_RACE frame of this race

    def process(self, state: RaceState) -> list[Callout]:
        prev = self.prev
        restarted = race_restarted(prev, state)
        if race_started(prev, state) or restarted:
            if self.recorder is not None and self.recorder.session is not None and prev is not None:
                log.info("closing open session on race %s", "restart" if restarted else "start")
                self.recorder.end_session(prev)
            self.races_started += 1
            log.info(
                "race start: track %s, %s laps, fuel %.1f/%.0f",
                state.track_id,
                state.total_laps or "timed",
                state.fuel_level,
                state.fuel_capacity,
            )
            for rule in self.rules:
                rule.reset()
            self.queue.clear()
            if restarted:
                self.tracks.reset()  # the car was teleported back to the grid
            self.track = None
            self.last_driving = None
            self.kinds.reset()
            if self.recorder is not None:
                self.recorder.start_session(state)
            # A rolling start crosses the finish line before lap 1, so the
            # detector may already know the track when the session opens.
            if self.tracks.match.confidence != "none":
                self._apply_track(self.tracks.match)

        # Rules and the lap store compare against the last driving frame. A pause or
        # a loading screen in between hides nothing: GT7 posts the pit-in lap on a
        # loading frame when the car crosses the line into the pit cut-scene
        # (2026-10-15), so the crossing is only visible from the frame before it.
        seen = prev
        if (
            prev is not None
            and prev.phase in (Phase.LOADING, Phase.PAUSED)
            and state.phase in (Phase.IN_RACE, Phase.FINISHED)
            and self.last_driving is not None
            and not restarted
        ):
            seen = self.last_driving
            for rule in self.rules:
                try:
                    rule.on_bridge(prev.phase)
                except Exception:  # noqa: BLE001
                    log.exception("rule %s failed on bridge", rule.name)

        callouts: list[Callout] = []
        if state.in_race or racing_frame(seen, state):
            for rule in self.rules:
                try:
                    callouts.extend(rule.evaluate(seen, state))
                except Exception:  # noqa: BLE001
                    log.exception("rule %s failed", rule.name)
        for c in callouts:
            self.queue.push(c)
            log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
            if self.metrics is not None:
                self.metrics.callouts_total.labels(c.rule).inc()

        match = self.tracks.observe(state)
        if match is not None and self.session_open:
            self._apply_track(match)
        kind = self.kinds.observe(state)
        if kind is not None and self.session_open:
            self._apply_kind(kind)

        if self.recorder is not None:
            self.recorder.observe(seen, state)
            if race_ended(prev, state) and self.recorder.session is not None:
                log.info("race end at lap %d", state.current_lap)
                if self.track is not None and self.tracks.match.decision == self.track.decision:
                    self.recorder.set_track(self.tracks.match)  # final candidates and fit
                self.recorder.end_session(state)
                self.track = None

        if self.metrics is not None:
            self.metrics.observe_state(state)
            self.metrics.observe_dropped(self.queue.dropped)
            for rule in self.rules:
                if isinstance(rule, FuelRule) and rule.laps_remaining is not None:
                    self.metrics.fuel_laps_remaining.set(rule.laps_remaining)

        if state.in_race:
            self.last_driving = state
        elif race_ended(prev, state):
            self.last_driving = None
        self.prev = state
        return callouts

    @property
    def session_open(self) -> bool:
        return self.recorder is None or self.recorder.session is not None

    @property
    def kind(self) -> SessionKind:
        return self.kinds.kind

    def _apply_kind(self, kind: SessionKind) -> None:
        log.info("session %s: %s", kind.kind, kind.evidence)
        if self.recorder is not None and self.recorder.session is not None:
            self.recorder.set_kind(kind)
        if self.metrics is not None:
            self.metrics.set_session(kind)
        for rule in self.rules:
            try:
                rule.on_session(kind)
            except Exception:  # noqa: BLE001
                log.exception("rule %s failed on session update", rule.name)

    def _apply_track(self, match: TrackMatch) -> None:
        """Keep the best answer the session has had; never downgrade on a blip. A
        layout the detector has ruled out is not a blip: the answer was wrong."""
        if (
            self.track is not None
            and CONFIDENCE_RANK[match.confidence] < CONFIDENCE_RANK[self.track.confidence]
            and (self.track.track_id is None or self.tracks.is_alive(self.track.track_id))
        ):
            return
        if self.track is not None and match.decision == self.track.decision:
            return
        self.track = match
        log.info(
            "track %s: %s (%s), %s",
            match.confidence,
            match.name,
            match.track_id,
            match.evidence,
        )
        if self.recorder is not None and self.recorder.session is not None:
            self.recorder.set_track(match)
        if self.metrics is not None:
            self.metrics.set_track(match)
        for rule in self.rules:
            try:
                rule.on_track(match)
            except Exception:  # noqa: BLE001
                log.exception("rule %s failed on track update", rule.name)
