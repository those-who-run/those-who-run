"""Synthetic race builder. Rules only react to transitions, so a few frames per lap is plenty."""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest

from those_who_run.state import Phase, RaceState, derive_phase


def make_state(**over) -> RaceState:
    base = dict(
        t=0.0,
        packet_id=0,
        phase=Phase.IN_RACE,
        current_lap=1,
        total_laps=5,
        best_lap_ms=0,
        last_lap_ms=0,
        fuel_level=100.0,
        fuel_capacity=100.0,
        speed_kph=150.0,
        engine_rpm=6000.0,
        tire_temp=(60.0, 60.0, 60.0, 60.0),
        water_temp=90.0,
        oil_temp=95.0,
        track_id=7,
        race_start_pos=5,
        total_cars=16,
    )
    base.update(over)
    if "phase" not in over:
        base["phase"] = derive_phase(base["current_lap"], base["total_laps"], False, False)
    if "cars_on_track" not in over:
        base["cars_on_track"] = base["total_laps"] > 0 and base["current_lap"] >= 1
    return RaceState(**base)


class RaceSim:
    """Builds a list of RaceState frames for a race with the given lap times."""

    def __init__(
        self,
        total_laps: int = 5,
        fuel: float = 100.0,
        capacity: float = 100.0,
        burn: float = 5.0,
        track_id: int = 7,
        position: int = 5,
        cars: int = 16,
        tyres: tuple[float, float, float, float] = (60.0, 60.0, 60.0, 60.0),
        is_race: bool | None = None,
    ) -> None:
        self.total_laps = total_laps
        self.fuel = fuel
        self.capacity = capacity
        self.burn = burn
        self.track_id = track_id
        self.position = position
        self.cars = cars
        self.tyres = tyres
        self.is_race = is_race
        self.t = 0.0
        self.pid = 0
        self.lap = 0
        self.best = 0
        self.last = 0
        self.frames: list[RaceState] = []

    def _push(self, **over) -> RaceState:
        self.t += 1.0
        self.pid += 1
        over.setdefault("t", self.t)
        over.setdefault("packet_id", self.pid)
        over.setdefault("total_laps", self.total_laps)
        over.setdefault("fuel_capacity", self.capacity)
        over.setdefault("track_id", self.track_id)
        over.setdefault("race_start_pos", self.position)
        over.setdefault("total_cars", self.cars)
        over.setdefault("tire_temp", self.tyres)
        if self.is_race is not None:
            over.setdefault("cars_on_track", self.is_race)
        s = make_state(**over)
        self.frames.append(s)
        return s

    def menu(self) -> RaceSim:
        self._push(phase=Phase.MENU, current_lap=-1, fuel_level=self.fuel)
        return self

    def at_track(self) -> RaceSim:
        self._push(phase=Phase.AT_TRACK, current_lap=0, fuel_level=self.fuel)
        return self

    def paused(self) -> RaceSim:
        """Pause menu during the lap in progress."""
        self._push(phase=Phase.PAUSED, current_lap=self.lap, fuel_level=self.fuel)
        return self

    def loading(self, current_lap: int = 0) -> RaceSim:
        """Loading screen; GT7 resets the lap counter to 0 when quitting a session."""
        self._push(phase=Phase.LOADING, current_lap=current_lap, fuel_level=self.fuel)
        return self

    def drive(self, seconds: int, **over) -> RaceSim:
        """Hold the lap in progress for ``seconds`` frames, one per second, with
        overrides such as ``tire_temp`` or ``water_temp`` applied to each."""
        for _ in range(seconds):
            kw = dict(
                current_lap=max(self.lap, 1),
                fuel_level=self.fuel,
                best_lap_ms=self.best,
                last_lap_ms=self.last,
            )
            kw.update(over)
            self._push(**kw)
        return self

    def race(
        self,
        lap_times: Sequence[int],
        refuel_after_lap: int | None = None,
        refuel_to: float | None = None,
        pause_in_lap: int | None = None,
        finish: bool = True,
    ) -> RaceSim:
        best = 0  # GT7 clears its best on a restart too (qualifying, 2026-10-14)
        last = 0
        fuel = self.fuel
        lap = 1
        self._push(current_lap=lap, fuel_level=fuel, best_lap_ms=best, last_lap_ms=last)
        for lap_ms in lap_times:
            # mid-lap frame
            self._push(
                current_lap=lap, fuel_level=fuel - self.burn / 2, best_lap_ms=best, last_lap_ms=last
            )
            if pause_in_lap == lap:
                self._push(
                    phase=Phase.PAUSED,
                    current_lap=lap,
                    fuel_level=fuel - self.burn / 2,
                    best_lap_ms=best,
                    last_lap_ms=last,
                )
                self._push(
                    current_lap=lap,
                    fuel_level=fuel - self.burn / 2,
                    best_lap_ms=best,
                    last_lap_ms=last,
                )
            fuel = fuel - self.burn
            if refuel_after_lap == lap:
                fuel = self.capacity if refuel_to is None else refuel_to
            last = lap_ms
            best = lap_ms if best <= 0 or lap_ms < best else best
            lap += 1
            self._push(current_lap=lap, fuel_level=fuel, best_lap_ms=best, last_lap_ms=last)
        self.fuel = fuel
        self.lap = lap
        self.best = best
        self.last = last
        if finish:
            self.menu()
        return self


@pytest.fixture
def sim() -> type[RaceSim]:
    return RaceSim


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Under ``TWR_FAIL_ON_SKIP=1`` (``make check``, and so CI) a skipped test fails
    the run: a missing extra must not quietly turn a test off."""
    if os.environ.get("TWR_FAIL_ON_SKIP") != "1" or exitstatus != pytest.ExitCode.OK:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if skipped:
        if reporter:
            reporter.write_sep("=", f"TWR_FAIL_ON_SKIP: {len(skipped)} skipped", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
