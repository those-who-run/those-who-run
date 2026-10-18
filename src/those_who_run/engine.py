"""The engine: turns a stream of RaceState into callouts, lap records and metrics."""

from __future__ import annotations

import logging
from dataclasses import replace

from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.metrics import Metrics
from those_who_run.pause import PauseClock
from those_who_run.pitstop import NO_STOPS, PitDetector, PitStatus
from those_who_run.rules.base import Rule
from those_who_run.rules.fuel import FuelRule
from those_who_run.sessionkind import DriverCheck, SessionDetector, SessionKind
from those_who_run.state import (
    Phase,
    RaceState,
    lap_time_posted,
    race_ended,
    race_restarted,
    race_started,
    racing_frame,
)
from those_who_run.store import SessionStore
from those_who_run.trackdetect import CONFIDENCE_RANK, TrackDetector, TrackMatch

log = logging.getLogger(__name__)

# A timed race has no FINISHED phase (no lap total to exceed). Its end is the
# first line crossing after the clock runs out, and GT7 shows it the way it
# shows the flag in a lap race: it takes the car over, throttle and brake at 0
# while it coasts (Suzuka East timed race, 2026-10-16: 15 s of it, then the
# results screen). Drivers never coast hands-off that long at racing speed:
# 1.8 s at most in every race recorded with a field.
FINISH_GRACE_SECS = 0.5  # inputs right at the line still count as the driver's
FINISH_COAST_SECS = 3.0


def joined_part_way(prev: RaceState | None, state: RaceState) -> bool:
    """The engineer started part way through a session (an upgrade, an OOM, a node
    reboot; Suzuka 2026-10-18, lap 7 at 124 km/h, #265): its first frame is a race
    frame past lap 1 with nothing before it. A start seen from the grid, the track
    screen or a loading screen has a frame before it. Joined on lap 1 it cannot be
    told from a flying start, which crosses the line at speed with nothing before
    it either when the engineer comes up on that frame, so it reads as a start."""
    return prev is None and state.in_race and state.current_lap > 1


# The pit lane is quiet from entry to exit (#244), apart from the rules whose
# ``pit_lane`` is "speak" (fuel: its calls are about the stop). Each other rule
# says whether a callout raised in the lane, or still queued at the entry, is
# held and spoken after the exit ("hold": a lap call where the lane crosses the
# line, SUGO 2026-10-18) or dropped ("drop": a place called a moment before the
# entry is the order before the stop, and the net change follows the exit).

# A pause never ends a session on its own (#229): GT7 keeps a paused race for as
# long as the PS5 stays on, and so does the engineer. The session ends paused when
# the feed is lost during the pause (the PS5 switched off or put to rest) or the
# engineer stops, or, with ``pause_limit_secs``, after a pause that long.


class Engine:
    def __init__(
        self,
        rules: list[Rule],
        queue: CalloutQueue,
        recorder: SessionStore | None = None,
        metrics: Metrics | None = None,
        pause_limit_secs: float = 0.0,
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
        self.pits = PitDetector()
        self.finished = False  # this session ended at the line (flag or timed finish)
        self._crossing: RaceState | None = None  # last line crossing of a timed race
        self._coast_since: float | None = None
        self.last_driving: RaceState | None = None  # last IN_RACE frame of this race
        self.driver = DriverCheck()
        self.replay = False  # a GT7 replay or demo race: ignored until the next start
        self._held: list[RaceState] = []  # an unflagged start, until DriverCheck decides
        self._held_prev: RaceState | None = None
        self.in_pit_lane = False  # as the rules were last told, see _apply_pits
        self.pit_held: list[Callout] = []  # raised in the pit lane, spoken after the exit
        self.pauses = PauseClock()
        self.pause_limit_secs = pause_limit_secs  # 0 is no limit, see the top
        self.ended_paused = False  # ended in a pause: ignored until the next start

    def process(self, state: RaceState) -> list[Callout]:
        """Feed one frame. A session that starts with GT7's cars-on-track flag off is
        held back, at most ``DriverCheck.window_secs``, until it is known to be a
        drive (its frames then go through as if never held), a replay (#243) or
        GT7's attract-mode demo race (#260).

        A frozen frame is read as the pause it is (``PauseClock``) before anything
        else sees it."""
        state = self.pauses.observe(state)
        prev = self.prev
        if self._held:
            self._held.append(state)
            self.prev = state
            verdict = self.driver.observe(state)
            self.driver.see(state)  # after: a menu that ends the start is no news of it
            if verdict is None:
                return []
            held, self._held = self._held, []
            if verdict == "drive":
                self.prev = self._held_prev
                return [c for s in held for c in self._step(s)]
            log.info(
                "ignoring a %s: GT7's cars-on-track flag is off from the start and %s",
                "replay" if verdict == "replay" else "demo race",
                self.driver.why,
            )
            self.replay = True
            recorder, last = self.recorder, self._held_prev
            if recorder is not None and recorder.session is not None and last is not None:
                log.info("closing open session on %s start", verdict)
                self._end_session(last)
            self.last_driving = None
            return []
        self.driver.see(state)
        starting = race_started(prev, state) or race_restarted(prev, state)
        if starting and not state.cars_on_track:
            self._held, self._held_prev = [state], prev
            self.driver.start(state)
            self.prev = state
            return []
        if (self.replay or self.ended_paused) and not starting:
            self.prev = state
            return []
        self.replay = self.ended_paused = False
        if (
            self.pause_limit_secs > 0
            and self.pauses.since is not None
            and state.t - self.pauses.since >= self.pause_limit_secs
            and self.session_open
            and self.last_driving is not None
        ):
            self._end_paused(state, f"paused for {self.pause_limit_secs / 60:.0f} min")
            self.prev = state
            return []
        return self._step(state)

    def feed_lost(self) -> bool:
        """The live watchdog lost the feed. During a pause that ends the session,
        paused (#229): the PS5 was switched off or put to rest. Lost while driving,
        the session stays open: the feed may come back. True if it ended."""
        if self.pauses.since is None or self.prev is None or self.last_driving is None:
            return False
        if not self.session_open:
            return False
        self._end_paused(self.prev, "the feed was lost")
        return True

    def close_session(self) -> None:
        """End the open session where the frames stop (the engineer stopping, or the
        end of a replay): paused when they stop in a pause."""
        if self.recorder is None or self.recorder.session is None or self.prev is None:
            return
        if self.pauses.since is not None:
            self._end_paused(self.prev, "the frames stopped")
            return
        self._end_session(self.prev)

    def _end_paused(self, state: RaceState, why: str) -> None:
        """End the session as of the start of its pause, and ignore the frames until
        the next start: if the race carries on after this, it is not watched."""
        log.info("session ended paused on lap %d: %s", state.current_lap, why)
        self._end_session(state)
        self.ended_paused = True
        self.last_driving = None
        self.track = None
        self.queue.clear()
        self.pit_held.clear()

    def _end_session(self, state: RaceState, finished: bool = False) -> None:
        """Close the open session with the pause clock's view of it."""
        if self.recorder is None or self.recorder.session is None:
            return
        self.recorder.end_session(
            state,
            finished=finished,
            paused_secs=self.pauses.paused_for(state.t),
            paused_since=self.pauses.since,
        )

    def _step(self, state: RaceState) -> list[Callout]:
        prev = self.prev
        restarted = race_restarted(prev, state)
        if race_started(prev, state) or restarted:
            if self.recorder is not None and self.recorder.session is not None and prev is not None:
                log.info("closing open session on race %s", "restart" if restarted else "start")
                self._end_session(prev)
            self.races_started += 1
            joined = joined_part_way(prev, state)
            log.info(
                "race start: track %s, %s laps, fuel %.1f/%.0f",
                state.track_id,
                state.total_laps or "timed",
                state.fuel_level,
                state.fuel_capacity,
            )
            if joined:
                log.info(
                    "joined part way: lap %d at %.0f km/h, no start seen",
                    state.current_lap,
                    state.speed_kph,
                )
            for rule in self.rules:
                rule.reset()
                rule.session = None
                rule.pits = NO_STOPS
                rule.joined = joined
            self.queue.clear()
            if restarted:
                self.tracks.reset()  # the car was teleported back to the grid
            self.track = None
            self.last_driving = None
            self.kinds.reset()
            if joined:
                self.kinds.join()
                self.tracks.join()
            self.pits.reset()
            self.in_pit_lane = False
            self.pit_held.clear()
            self.pauses.reset()
            self.finished = False
            self._crossing = None
            self._coast_since = None
            if self.recorder is not None:
                self.recorder.start_session(state, joined=joined)
            # A rolling start crosses the finish line before lap 1, so the
            # detector may already know the track when the session opens.
            if self.tracks.match.confidence != "none":
                self._apply_track(self.tracks.match)

        # Before the rules: the crossing that closes an in-lap can come on the very
        # frame after the pit cut, and the fuel rule must know it was in the pits.
        pit = self.pits.observe(state)
        released = []  # held in the pit lane, out now
        if pit is not None and self.session_open:
            released = self._apply_pits(pit, state)

        # Rules and the lap store compare against the last driving frame. A pause or
        # a loading screen in between hides nothing: GT7 posts a lap on a loading
        # frame when the car crosses the line in a pit cut-scene (into the pits at
        # Suzuka East 2026-10-15, out of them at Willow Springs 2026-10-17), so the
        # crossing is only visible from the frame before it.
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

        callouts: list[Callout] = released
        if state.in_race or racing_frame(seen, state):
            for rule in self.rules:
                try:
                    callouts.extend(rule.evaluate(seen, state))
                except Exception:  # noqa: BLE001
                    log.exception("rule %s failed", rule.name)
        callouts.extend(self._timed_finish(seen, state))
        if self.in_pit_lane:
            callouts = self._quiet(callouts)
        if state.phase is Phase.FINISHED:
            self.finished = True
        if self.finished and self.pit_held:
            callouts = self._release(state) + callouts  # finished in the lane: no exit
        if (
            race_ended(prev, state)
            and state.phase is not Phase.FINISHED
            and not self.finished
            and self.last_driving is not None
        ):
            for rule in self.rules:
                try:
                    callouts.extend(rule.on_end(self.last_driving, state))
                except Exception:  # noqa: BLE001
                    log.exception("rule %s failed at the end", rule.name)
        for c in callouts:
            self._push(c)

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
                self.recorder.set_pits(self.pits.status)  # fuel and time of a stop still open
                self._end_session(state, finished=self.finished)
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

    def _push(self, c: Callout) -> None:
        self.queue.push(c)
        log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
        if self.metrics is not None:
            self.metrics.callouts_total.labels(c.rule).inc()

    def _timed_finish(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        """Spot the end of a timed race with a field, see FINISH_COAST_SECS."""
        kind = self.kinds.kind
        if state.phase is Phase.PAUSED:
            self._coast_since = None  # a frozen car is not coasting
        if (
            self.finished
            or prev is None
            or state.phase is not Phase.IN_RACE
            or kind.kind != "timed_field"
            or not kind.cars_on_track
        ):
            return []
        if lap_time_posted(prev, state):
            self._crossing, self._coast_since = state, None
            return []
        crossing = self._crossing
        if crossing is None:
            return []
        if not (state.throttle == 0 and state.brake == 0 and state.speed_kph > 20):
            if state.t - crossing.t > FINISH_GRACE_SECS:
                self._crossing = None  # the driver is driving: just another lap
            self._coast_since = None
            return []
        if self._coast_since is None:
            self._coast_since = state.t
        if state.t - self._coast_since < FINISH_COAST_SECS:
            return []
        self.finished = True
        log.info(
            "timed race finished at the line, lap %d, P%s",
            crossing.current_lap - 1,
            crossing.position,
        )
        out: list[Callout] = []
        for rule in self.rules:
            try:
                out.extend(rule.on_finish(crossing))
            except Exception:  # noqa: BLE001
                log.exception("rule %s failed at the finish", rule.name)
        return out

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

    def _policy(self, callout: Callout) -> str:
        return next((r.pit_lane for r in self.rules if r.name == callout.rule), "hold")

    def _quiet(self, callouts: list[Callout]) -> list[Callout]:
        """Sort out callouts raised or queued in the pit lane: the ones to speak now
        are returned, the rest held for the exit or dropped (see the top)."""
        out = []
        for c in callouts:
            policy = self._policy(c)
            if policy == "speak":
                out.append(c)
            elif policy == "hold":
                self.pit_held.append(c)
                log.info("callout held for the pit exit (%s): %s", c.rule, c.text)
            else:
                self.queue.dropped += 1
                log.info("callout dropped in the pit lane (%s): %s", c.rule, c.text)
        return out

    def _release(self, state: RaceState) -> list[Callout]:
        """The held callouts, as raised now: the time in the lane does not age them."""
        out = [replace(c, created_at=state.t, hold=0.0) for c in self.pit_held]
        self.pit_held.clear()
        return out

    def _apply_pits(self, status: PitStatus, state: RaceState) -> list[Callout]:
        """Tell the rules, and quieten the queue at the entry. Returns the callouts
        held in the lane, to speak now it is left."""
        if status.teleports and status.teleports[-1].t == state.t:
            jump = status.teleports[-1]
            log.info("teleport on lap %d, not a pit stop: %s", jump.lap, jump.evidence)
        elif status.in_pit_lane:
            stop = status.stops[-1]
            log.info("pit entry on lap %d: %s", stop.in_lap, stop.evidence)
        else:
            stop = status.stops[-1]
            log.info(
                "pit exit on lap %s after %.1f s, fuel %.1f -> %.1f, tyres %s; stint %d",
                stop.out_lap,
                stop.pit_lane_secs or 0.0,
                stop.fuel_before,
                stop.fuel_after,
                "changed" if stop.tyres_changed else "kept",
                status.stint,
            )
        if self.recorder is not None and self.recorder.session is not None:
            self.recorder.set_pits(status)
        released = []
        if status.in_pit_lane and not self.in_pit_lane:
            self._quiet(self.queue.remove(lambda c: self._policy(c) != "speak"))
        elif not status.in_pit_lane:
            released = self._release(state)
        self.in_pit_lane = status.in_pit_lane
        for rule in self.rules:
            try:
                rule.on_pit(status)
            except Exception:  # noqa: BLE001
                log.exception("rule %s failed on pit update", rule.name)
        return released

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
