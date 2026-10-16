"""GT7 car names from the car code in telemetry.

The packet carries ``car_code`` only. ``data/cars.csv`` maps it to a maker and a
model name (from ddm999/gt7info, MIT-0). Cars GT7 added after the table was
taken are not in it; callers say "car <code>" for those.
"""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class Car:
    id: int
    maker: str
    name: str

    @property
    def full_name(self) -> str:
        """Maker and model, e.g. "Honda Civic Si Group A version '87"."""
        if not self.maker or self.name.lower().startswith(self.maker.lower()):
            return self.name
        return f"{self.maker} {self.name}"


def load_cars() -> tuple[Car, ...]:
    text = files("those_who_run.data").joinpath("cars.csv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return tuple(Car(int(r["id"]), r["maker"], r["name"]) for r in csv.DictReader(lines))


@functools.cache
def car_by_id() -> dict[int, Car]:
    return {c.id: c for c in load_cars()}


def car_name(code: int | None) -> str | None:
    """The full name for a car code; "car <code>" when the table lacks it, None for none."""
    if code is None or code <= 0:
        return None
    car = car_by_id().get(code)
    return car.full_name if car else f"car {code}"


def find_cars(text: str) -> list[Car]:
    """Cars whose maker or model contains every word of ``text``, case-insensitively."""
    words = text.lower().split()
    return [c for c in load_cars() if all(w in c.full_name.lower() for w in words)]
