"""Temperature warnings: hot tyres per corner, cold tyres at the start, water and oil.

Every check is an alarm. The value has to stay above its threshold for
``sustain_secs`` (a spin heats one tyre for a moment), the alarm then fires
once and only re-arms when the value has dropped ``hysteresis_c`` below the
threshold, and never within ``cooldown_secs`` of the last warning. Paused
frames are not evaluated, so a gap longer than the sustain window restarts it.

Thresholds are starting points. Recordings so far show tyres from 21 °C on a
cold start to 154 °C while sliding, and water and oil pinned at 85 and 110
whatever happens; GT7 may only move those with engine damage.
"""

from __future__ import annotations

from those_who_run.callouts import Callout
from those_who_run.rules.base import Rule
from those_who_run.state import RaceState
from those_who_run.verbalise import tidy_sentence

CORNERS = ("front left", "front right", "rear left", "rear right")


class _Alarm:
    def __init__(
        self, threshold: float | None, sustain: float, cooldown: float, hysteresis: float
    ) -> None:
        self.threshold = threshold if threshold else None  # None or 0 disables
        self.sustain = sustain
        self.cooldown = cooldown
        self.hysteresis = hysteresis
        self.above_since: float | None = None
        self.last_t: float | None = None
        self.fired_at: float | None = None
        self.armed = True

    def update(self, value: float, t: float) -> bool:
        if self.threshold is None:
            return False
        if self.last_t is not None and t - self.last_t > self.sustain:
            self.above_since = None  # a pause or a telemetry gap
        self.last_t = t
        if value <= self.threshold:
            self.above_since = None
            if value < self.threshold - self.hysteresis:
                self.armed = True
            return False
        if self.above_since is None:
            self.above_since = t
        if t - self.above_since < self.sustain or not self.armed:
            return False
        if self.fired_at is not None and t - self.fired_at < self.cooldown:
            return False
        self.fired_at = t
        self.armed = False
        return True


class TempsRule(Rule):
    name = "temps"
    default_priority = 14

    def reset(self) -> None:
        cfg = self.cfg
        sustain = float(cfg.get("sustain_secs", 5.0))
        cooldown = float(cfg.get("cooldown_secs", 60.0))
        hysteresis = float(cfg.get("hysteresis_c", 10.0))

        def alarm(key: str, default: float) -> _Alarm:
            raw = cfg.get(key, default)
            return _Alarm(float(raw) if raw else None, sustain, cooldown, hysteresis)

        self.tyres = [alarm("tyre_hot_c", 120.0) for _ in CORNERS]
        self.water = alarm("water_hot_c", 110.0)
        self.oil = alarm("oil_hot_c", 130.0)
        raw_cold = cfg.get("tyre_cold_c", 50.0)
        self.tyre_cold: float | None = float(raw_cold) if raw_cold else None
        self.cold_settle = float(cfg.get("cold_settle_secs", 2.0))
        self.started_at: float | None = None
        self.cold_checked = False

    def evaluate(self, prev: RaceState | None, state: RaceState) -> list[Callout]:
        if not state.in_race:
            return []
        out: list[Callout] = []
        if self.started_at is None:
            self.started_at = state.t
        if (
            not self.cold_checked
            and self.tyre_cold is not None
            and state.t - self.started_at >= self.cold_settle
        ):
            self.cold_checked = True
            if min(state.tire_temp) < self.tyre_cold:
                out.append(self.callout(self.template("template_tyres_cold", "Tyres cold."), state))

        hot = [
            CORNERS[i]
            for i, alarm in enumerate(self.tyres)
            if alarm.update(state.tire_temp[i], state.t)
        ]
        if hot:
            text = self.template("template_tyre_hot", "{corners} hot.").format(
                corners=_corners_phrase(hot)
            )
            out.append(self.callout(tidy_sentence(text), state))
        if self.water.update(state.water_temp, state.t):
            out.append(
                self.callout(self.template("template_water", "Water temperature high."), state)
            )
        if self.oil.update(state.oil_temp, state.t):
            out.append(self.callout(self.template("template_oil", "Oil temperature high."), state))
        return out


def _corners_phrase(names: list[str]) -> str:
    if len(names) == len(CORNERS):
        return "All tyres"
    if len(names) == 1:
        text = f"{names[0]} tyre"
    else:
        text = f"{', '.join(names[:-1])} and {names[-1]} tyres"
    return text[:1].upper() + text[1:]
