"""Fuel used stint by stint, from the fuel level frame by frame.

Every drop is added to the current stint, so a refuel never cancels what was
burnt before it. A stint ends where the pit detector (``pitstop``) says a stop
ended, not where the level goes up: the level also jumps on a restart that is
not seen as one (the qualifying recording of 2026-10-14 refills 75 -> 100 on the
restart frame, #157), settles up a fraction at the start, and creeps up in an
electric car (Xiaomi VGT, 2026-10-16). None of those is a pit stop. A withdrawn
stop (a reset to track, ``Teleport``) never ends a stint, as it is never done.

Stints that burnt less than ``min_fuel`` are left out of the figures (a stop
straight after another, a stint cut short by the flag), so the results card never
reads "zero percent, then seventy-four percent". The total keeps every drop.

The session store keeps one of these, fed every frame and the pit status, for
the results card's fuel-per-stint line. The spoken race summary leaves fuel out
(#245).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from those_who_run.pitstop import PitStatus

MIN_STINT_FUEL = 1.0  # fuel units: a stint below this is not a figure worth giving


@dataclass
class FuelStints:
    min_fuel: float = MIN_STINT_FUEL
    stints: list[float] = field(default_factory=lambda: [0.0])  # fuel used in each
    last: float | None = None
    base: int = 0  # stints done before an engineer restart (#273): the pit detector restarts

    def observe(self, level: float) -> float:
        """Take one frame's fuel level; returns the drop since the last frame (0 when
        it did not fall)."""
        last, self.last = self.last, level
        if last is None or level >= last:
            return 0.0
        self.stints[-1] += last - level
        return last - level

    def on_pit(self, status: PitStatus) -> None:
        """The pit detector's view: each stop it has seen done starts the next stint."""
        while len(self.stints) < self.base + status.stint:
            self.stints.append(0.0)

    @property
    def total(self) -> float:
        return sum(self.stints)

    def used(self) -> list[float]:
        """Fuel used in each stint, leaving out stints under ``min_fuel``."""
        return [x for x in self.stints if x >= self.min_fuel]
