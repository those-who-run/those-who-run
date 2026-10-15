"""Say when the telemetry stops mid-session, and when it is back.

Not a frame rule: frames are exactly what is missing. The live watchdog calls
``observe`` once a second with whether packets are arriving and the last state
the engine saw. "Lost telemetry." is spoken once when packets stop while that
last state was a race or a pause (silence in a menu is normal), "Telemetry
back." when they resume after such a loss.
"""

from __future__ import annotations

from typing import Any

from those_who_run.callouts import Callout
from those_who_run.phrasing import Phrasebook
from those_who_run.state import Phase, RaceState

DEFAULT_PHASES = (Phase.IN_RACE.value, Phase.PAUSED.value)


class TelemetryVoice:
    name = "telemetry"

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg: dict[str, Any] = dict(cfg or {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.priority = int(self.cfg.get("priority", 5))
        self.phases = {str(p) for p in self.cfg.get("phases", DEFAULT_PHASES)}
        self.was: bool | None = None
        self.lost_announced = False
        self.phrases = Phrasebook(self.cfg)

    def observe(self, connected: bool, last_state: RaceState | None, now: float) -> list[Callout]:
        was, self.was = self.was, connected
        if not self.enabled or was is None or connected == was:
            return []
        if not connected:
            if last_state is None or last_state.phase.value not in self.phases:
                return []
            self.lost_announced = True
            return [self._callout(self.phrases.pick("template_lost", "Lost telemetry."), now)]
        if not self.lost_announced:
            return []
        self.lost_announced = False
        return [self._callout(self.phrases.pick("template_back", "Telemetry back."), now)]

    def _callout(self, text: str, now: float) -> Callout:
        return Callout(text=str(text), priority=self.priority, rule=self.name, created_at=now)
