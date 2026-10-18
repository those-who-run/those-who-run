"""The GT7 track table: names, finish lines and lap bounding boxes.

GT7's telemetry carries no track id, so the layout has to be recognised from
where the car goes. The table lives in ``data/tracks.csv`` (adapted from
gt-telem, which adapted it from Bornhall/gt7telemetry, both GPL-3.0) and is
loaded once per process. Coordinates are GT7 world x/z in metres; each track
has its own origin, so boxes of unrelated tracks overlap freely and location
alone never identifies a layout.
"""

from __future__ import annotations

import csv
import functools
import math
from dataclasses import dataclass
from importlib.resources import files

Point = tuple[float, float]
Box = tuple[float, float, float, float]  # minx, minz, maxx, maxz

# Layouts the table cannot tell apart, by id, and the circuit each belongs to where
# the name does not say (``family_name`` reads it from the name otherwise). Each
# shares its finish line and direction with its base layout to 0.1 m, the two boxes
# overlap 0.98 or more, and the table has no lap length for either: a lap fits both
# the same, so the detector names the circuit (#275). Fuji and Fuji Short are a pair
# like these whose names already say it.
#
# Spa (2026-10-18, #275): nothing we have separates the Grand Prix and 24h layouts.
# Whole laps in two outings (20261018-141557, 20261018-142627) were 6.92 to 6.99 km
# and their box filled each row's box 0.993 to 0.999, the two never more than 0.006
# apart, against the 0.05 the detector needs. GT7's telemetry has no layout id, and
# a pit stop is a loading cut-scene, so a pit lane path is never in the frames.
TWINS: dict[int, str] = {
    1269: "Circuit de Spa-Francorchamps",  # Spa 24h Layout
    742: "Autodromo Nazionale Monza",  # Autodromo Nazionale Monza No Chicane
    854: "24 Heures du Mans Racing Circuit",  # 24 Heures du Mans Racing Circuit No Chicane
    1249: "Circuit de Barcelona-Catalunya Grand Prix Layout",  # GP Layout No Chicane
}


@dataclass(frozen=True, slots=True)
class Track:
    id: int
    name: str
    direction: str | None  # PX/NX/PZ/NZ: sign of travel across the line, or None
    line: tuple[Point, Point] | None
    box: Box | None
    length_m: float | None = None  # lap length when known; separates layouts with one box

    @property
    def has_geometry(self) -> bool:
        return self.line is not None and self.box is not None

    @property
    def family(self) -> str:
        """The circuit this layout belongs to: see ``TWINS`` and ``family_name``."""
        return TWINS.get(self.id) or family_name(self.name)

    @property
    def box_area(self) -> float:
        if self.box is None:
            return math.inf
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])


def family_name(name: str) -> str:
    """The circuit a layout belongs to: the name without its layout part.

    "Fuji International Speedway (Short)" and "Tokyo Expressway - East Clockwise"
    give "Fuji International Speedway" and "Tokyo Expressway".
    """
    return name.split(" (")[0].split(" - ")[0].strip()


def _parse(row: dict[str, str]) -> Track:
    geo = [row[k] for k in ("p1x", "p1z", "p2x", "p2z", "minx", "minz", "maxx", "maxz")]
    if all(geo):
        p1x, p1z, p2x, p2z, minx, minz, maxx, maxz = (float(v) for v in geo)
        line: tuple[Point, Point] | None = ((p1x, p1z), (p2x, p2z))
        box: Box | None = (min(minx, maxx), min(minz, maxz), max(minx, maxx), max(minz, maxz))
    else:
        line, box = None, None
    direction = row["direction"].strip() or None
    # The source table calls the z axis "Y"; normalise so the names match RaceState.
    if direction in ("PY", "NY"):
        direction = direction[0] + "Z"
    length = row.get("length_m", "").strip()
    return Track(
        id=int(row["id"]),
        name=row["name"],
        direction=direction,
        line=line,
        box=box,
        length_m=float(length) if length else None,
    )


@functools.cache
def load_tracks() -> tuple[Track, ...]:
    text = files("those_who_run.data").joinpath("tracks.csv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return tuple(_parse(row) for row in csv.DictReader(lines))


@functools.cache
def track_by_id() -> dict[int, Track]:
    return {t.id: t for t in load_tracks()}


def track_name(track_id: int | None) -> str | None:
    if track_id is None:
        return None
    t = track_by_id().get(track_id)
    return t.name if t else f"track {track_id}"
