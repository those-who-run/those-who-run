"""Sum up the race when the chequered flag falls.

Spoken on the first FINISHED frame: finishing position, best lap and fuel used.
The position is read straight off the flag frame, which also covers a place
gained in the final seconds that the position rule's settle window would have
swallowed (recording 2026-10-14: "Up to sixth" was lost to the flag). The best
lap is GT7's own from the flag frame; when GT7 has none (time trial) it is the
best posted lap, skipping lap 1 of a lap-count race as GT7 does (lap 1 starts on
the grid, ahead of the line, and is short). Fuel used sums the
drops frame by frame, so a pit stop does not cancel the first stint.

Situational pools, used when configured: ``template_position_win`` and
``template_position_podium``. ``template_fuel`` may use ``{fuel}`` (used, as a
percentage of the tank) or ``{fuel_left}``.

Timed races never reach FINISHED (GT7 reports no lap total), so they get no
summary yet; that needs a timed-race recording to settle what the end looks like.

A solo session (time trial, practice, solo laps) has no flag either. Leaving
it, with at least ``quit_min_laps`` laps done, gets ``template_quit``: laps done
and the best lap. ``quit_kinds`` lists the session kinds that get it; a quit
race is a retirement and stays quiet by default.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import Phase, RaceState, lap_time_posted
from those_who_run.verbalise import (
    lap_time_words,
    laps_words,
    number_words,
    ordinal_words,
    percent_words,
    tidy_sentence,
)


class RaceSummaryRule(Rule):
    name = "race_summary"
    default_priority = 25  # after the final lap time, which is posted on the same frame

    def reset(self) -> None:
        self.min_fuel = float(self.cfg.get("min_fuel", 1.0))
        self.fuel_used = 0.0
        self.last_fuel: float | None = None
        self.best_ms = 0
        self.best_any_ms = 0  # lap 1 included, for a solo run with nothing else
        self.laps_done = 0
        self.announced = False
        self.quit_kinds = set(self.cfg.get("quit_kinds", ["solo_timed", "solo_laps"]))
        self.quit_min_laps = int(self.cfg.get("quit_min_laps", 1))

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if self.last_fuel is not None and state.fuel_level < self.last_fuel:
            self.fuel_used += self.last_fuel - state.fuel_level
        self.last_fuel = state.fuel_level
        if lap_time_posted(prev, state):
            self.laps_done += 1
            if self.best_any_ms <= 0 or state.last_lap_ms < self.best_any_ms:
                self.best_any_ms = state.last_lap_ms
            if not (state.has_lap_count and prev is not None and prev.current_lap <= 1) and (
                self.best_ms <= 0 or state.last_lap_ms < self.best_ms
            ):
                self.best_ms = state.last_lap_ms
        if self.announced or state.phase is not Phase.FINISHED:
            return []
        self.announced = True

        position = ""
        if self.has_field(state) and state.position is not None:
            keys = ["template_position"]
            if state.position == 1:
                keys.insert(0, "template_position_win")
            elif state.position <= 3:
                keys.insert(0, "template_position_podium")
            position = self.first_template(keys, "Finished {position}.").format(
                position=ordinal_words(state.position), p=number_words(state.position)
            )
        best = ""
        best_ms = state.best_lap_ms if state.best_lap_ms > 0 else self.best_ms
        if best_ms > 0:
            best = self.template("template_best", "Best lap {time}.").format(
                time=lap_time_words(best_ms)
            )
        fuel = ""
        if state.fuel_capacity > 0 and self.fuel_used >= self.min_fuel:
            fuel = self.template("template_fuel", "Fuel used {fuel}.").format(
                fuel=percent_words(100.0 * self.fuel_used / state.fuel_capacity),
                fuel_left=percent_words(100.0 * max(state.fuel_level, 0.0) / state.fuel_capacity),
            )
        text = self.template("template", "Chequered flag. {position} {best} {fuel}").format(
            position=position, best=best, fuel=fuel
        )
        return [self.callout(tidy_sentence(text), state)]

    def on_end(self, last: RaceState, state: RaceState) -> list[Callout]:
        kind = self.session.kind if self.session is not None else "unknown"
        # GT7's counter knows laps the engineer joined too late to see.
        laps = max(self.laps_done, last.current_lap - 1)
        if self.announced or kind not in self.quit_kinds or laps < self.quit_min_laps:
            return []
        self.announced = True
        best_ms = last.best_lap_ms if last.best_lap_ms > 0 else self.best_ms or self.best_any_ms
        best = ""
        if best_ms > 0:
            best = self.template("template_best", "Best lap {time}.").format(
                time=lap_time_words(best_ms)
            )
        laps_text = laps_words(laps)
        text = self.template("template_quit", "Session done. {laps}. {best}").format(
            laps=laps_text[:1].upper() + laps_text[1:], best=best
        )
        return [self.callout(tidy_sentence(text), state)]
