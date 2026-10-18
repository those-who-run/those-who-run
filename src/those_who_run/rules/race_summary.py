"""Sum up the race when the chequered flag falls.

Spoken on the first FINISHED frame: finishing position and best lap.
The position is read straight off the flag frame, which also covers a place
gained in the final seconds that the position rule's settle window would have
swallowed (recording 2026-10-14: "Up to sixth" was lost to the flag). The best
lap is GT7's own from the flag frame; when GT7 has none (time trial) it is the
best posted lap, skipping lap 1 of a lap-count race as GT7 does (lap 1 starts on
the grid, ahead of the line, and is short), and lap 1 itself when it is the only
lap. Each lap counts once however many frames post its time.

Fuel is not spoken (#245): fuel by stint ran "ninety-seven percent, then
ninety-seven percent" at SUGO and told the driver nothing. The results card
keeps the per-stint figures (``store``). A ``{fuel}`` left in a configured
template is filled with nothing, so an older rules file still reads.

Situational pools, used when configured: ``template_position_win`` and
``template_position_podium``.

Timed races never reach FINISHED (GT7 reports no lap total). The engine works
out their finish from what GT7 does at the line instead and calls
``on_finish`` with the crossing frame.

A solo session (time trial, practice, solo laps) has no flag either. Leaving
it, with at least ``quit_min_laps`` laps done, gets ``template_quit``: laps done
and the best lap. ``quit_kinds`` lists the session kinds that get it; a quit
race is a retirement and stays quiet by default.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import Phase, RaceState, lap_time_posted, posted_lap
from those_who_run.verbalise import (
    lap_time_words,
    laps_words,
    number_words,
    ordinal_words,
    tidy_sentence,
)


class RaceSummaryRule(Rule):
    name = "race_summary"
    default_priority = 25  # after the final lap time, which is posted on the same frame

    def reset(self) -> None:
        self.last_lap_counted = 0
        self.best_ms = 0
        self.best_any_ms = 0  # lap 1 included, for a solo run with nothing else
        self.laps_done = 0
        self.announced = False
        self.quit_kinds = set(self.cfg.get("quit_kinds", ["solo_timed", "solo_laps"]))
        self.quit_min_laps = int(self.cfg.get("quit_min_laps", 1))

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if lap_time_posted(prev, state) and self._new_lap(state):
            self.laps_done += 1
            if self.best_any_ms <= 0 or state.last_lap_ms < self.best_any_ms:
                self.best_any_ms = state.last_lap_ms
            if not (_start_lap(prev, state)) and (
                self.best_ms <= 0 or state.last_lap_ms < self.best_ms
            ):
                self.best_ms = state.last_lap_ms
        if state.phase is not Phase.FINISHED:
            return []
        return self.on_finish(state)

    def on_finish(self, state: RaceState) -> list[Callout]:
        """The race is over: the flag frame of a lap race, or the line crossing that
        ended a timed race (see the engine). Spoken once."""
        if self.announced:
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
        best = self._best_words(state)
        text = self.template("template", "Chequered flag. {position} {best}").format(
            position=position, best=best, fuel=""
        )
        return [self.callout(tidy_sentence(text), state)]

    def on_end(self, last: RaceState, state: RaceState) -> list[Callout]:
        kind = self.session.kind if self.session is not None else "unknown"
        # GT7's counter knows laps the engineer joined too late to see.
        laps = max(self.laps_done, last.current_lap - 1)
        if self.announced or kind not in self.quit_kinds or laps < self.quit_min_laps:
            return []
        self.announced = True
        best = self._best_words(last)
        laps_text = laps_words(laps)
        text = self.template("template_quit", "Session done. {laps}. {best}").format(
            laps=laps_text[:1].upper() + laps_text[1:], best=best
        )
        return [self.callout(tidy_sentence(text), state)]

    def _new_lap(self, state: RaceState) -> bool:
        """The posted time is for a lap not counted yet (``lap_time_posted`` can fire
        on more than one frame for a lap: the first post counts, see ``posted_lap``)."""
        lap_no = posted_lap(state)
        if lap_no <= self.last_lap_counted:
            return False
        self.last_lap_counted = lap_no
        return True

    def _best_words(self, state: RaceState) -> str:
        """GT7's best when it has one, else the best counted lap, else any lap (a
        session whose only lap is lap 1). The flag and a quit choose alike."""
        best_ms = state.best_lap_ms if state.best_lap_ms > 0 else self.best_ms or self.best_any_ms
        if best_ms <= 0:
            return ""
        return self.template("template_best", "Best lap {time}.").format(
            time=lap_time_words(best_ms)
        )


def _start_lap(prev: RaceState | None, state: RaceState) -> bool:
    """Lap 1 that GT7 itself leaves out of its best: it posts the time and keeps its
    best blank (a grid ahead of the line, Suzuka East lap and timed races). A lap
    1 GT7 does count (qualifying from the pits, SUGO's rolling start) is a lap."""
    if prev is None or prev.current_lap > 1:
        return False
    return state.has_lap_count or state.best_lap_ms <= 0
