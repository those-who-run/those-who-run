"""The engine: turns a stream of RaceState into callouts, lap records and metrics."""

from __future__ import annotations

import logging

from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.metrics import Metrics
from those_who_run.rules.base import Rule
from those_who_run.rules.fuel import FuelRule
from those_who_run.state import (
    RaceState,
    race_ended,
    race_restarted,
    race_started,
    racing_frame,
)
from those_who_run.store import SessionStore

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
            if self.recorder is not None:
                self.recorder.start_session(state)

        callouts: list[Callout] = []
        if state.in_race or racing_frame(prev, state):
            for rule in self.rules:
                try:
                    callouts.extend(rule.evaluate(prev, state))
                except Exception:  # noqa: BLE001
                    log.exception("rule %s failed", rule.name)
        for c in callouts:
            self.queue.push(c)
            log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
            if self.metrics is not None:
                self.metrics.callouts_total.labels(c.rule).inc()

        if self.recorder is not None:
            self.recorder.observe(prev, state)
            if race_ended(prev, state) and self.recorder.session is not None:
                log.info("race end at lap %d", state.current_lap)
                self.recorder.end_session(state)

        if self.metrics is not None:
            self.metrics.observe_state(state)
            self.metrics.observe_dropped(self.queue.dropped)
            for rule in self.rules:
                if isinstance(rule, FuelRule) and rule.laps_remaining is not None:
                    self.metrics.fuel_laps_remaining.set(rule.laps_remaining)

        self.prev = state
        return callouts
