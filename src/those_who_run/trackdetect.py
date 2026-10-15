"""Recognise the track layout from where the car drives.

GT7 sends no track id. gt-telem guesses one by matching a lap's bounding box
against its table at 95% overlap, after lap 1, only when "cars on track" is
set; that missed the Nürburgring 24h layout outright (2026-10-14) because the
table's box is ~580 m taller than the real lap, and it never runs in practice.

This detector keeps a set of candidate layouts and narrows it with three
independent physical facts, each cheap to check on every frame:

1. **Starts near the line.** A grid or a pit lane sits within a few hundred
   metres of the layout's finish line. This is what separates the real
   layout from unrelated tracks whose (huge) boxes happen to contain the
   same coordinates, such as Special Stage Route X.
2. **Path stays inside the box.** Every layout is dropped as soon as the car
   leaves its bounding box (with a tolerance for table error). Family members
   that share a finish line (GP vs 24h, Indy vs full) fall out as the car
   drives beyond the shorter layout.
3. **Finish line crossed, in the right direction.** The decisive fact, but it
   only arrives at the end of the first lap. Reverse layouts share a line and
   a box with their forward twin and differ only here.

Ranking: layouts whose line has been crossed outrank the rest; among those,
higher overlap between the driven box and the layout's box wins. Confidence
is reported honestly: some pairs (Fuji vs Fuji Short, Monza vs No Chicane)
have identical geometry in the table and stay ``ambiguous`` forever.

The detector is pure: feed it frames, read ``match``. It is used live by the
engine, by ``replay`` and by ``tracks backfill`` over stored Parquet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from those_who_run.state import Phase, RaceState
from those_who_run.tracks import Box, Point, Track, load_tracks

Confidence = Literal["none", "ambiguous", "probable", "confirmed"]
CONFIDENCE_RANK: dict[str, int] = {"none": 0, "ambiguous": 1, "probable": 2, "confirmed": 3}

POSITION_PHASES = frozenset({Phase.AT_TRACK, Phase.IN_RACE, Phase.FINISHED})


@dataclass(frozen=True, slots=True)
class Candidate:
    track: Track
    line_crossed: bool
    fit: float  # IoU of the driven box and the layout's box, 0..1

    @property
    def rank(self) -> tuple[int, float, float]:
        # Crossed first, then best fit, then the tighter layout.
        return (1 if self.line_crossed else 0, self.fit, -self.track.box_area)


@dataclass(frozen=True, slots=True)
class TrackMatch:
    track_id: int | None
    name: str | None
    confidence: Confidence
    candidates: tuple[Candidate, ...]  # best first
    evidence: str

    @property
    def candidate_ids(self) -> tuple[int, ...]:
        return tuple(c.track.id for c in self.candidates)

    @property
    def decision(self) -> tuple[int | None, str, tuple[int, ...]]:
        """What callers act on. Fit values and wording change every frame; this does not."""
        return (self.track_id, self.confidence, self.candidate_ids)


NO_MATCH = TrackMatch(None, None, "none", (), "no position data yet")


class TrackDetector:
    def __init__(
        self,
        tracks: tuple[Track, ...] | None = None,
        box_tolerance_m: float = 50.0,
        start_radius_m: float = 1000.0,
        teleport_m: float = 100.0,
        min_distance_m: float = 500.0,
        dominance: float = 0.05,
    ) -> None:
        self.tracks = tuple(t for t in (tracks or load_tracks()) if t.has_geometry)
        self.box_tolerance = box_tolerance_m
        self.start_radius = start_radius_m
        self.teleport = teleport_m
        self.min_distance = min_distance_m
        self.dominance = dominance
        self.reset()

    def reset(self) -> None:
        """Forget everything: call on a race restart (the car is teleported to the grid)."""
        self._pending_reset = False
        self._start: Point | None = None
        self._prev: Point | None = None
        self._box: Box | None = None
        self._distance = 0.0
        self._crossed: set[int] = set()
        self._alive: set[int] = {t.id for t in self.tracks}
        self._match: TrackMatch = NO_MATCH

    @property
    def match(self) -> TrackMatch:
        return self._match

    @property
    def distance_m(self) -> float:
        """Metres driven since reset, teleports excluded."""
        return self._distance

    # feeding

    def observe(self, state: RaceState) -> TrackMatch | None:
        """Feed one frame. Returns the new match when the decision changed, else None.

        Evidence accumulates from the first frame at a track, through the
        pre-race phase (a rolling start drives most of a kilometre before lap
        1 begins) and across pauses. Coming back from a menu or a loading
        screen means a new venue, so the next positioned frame starts over.
        """
        if state.phase in (Phase.MENU, Phase.LOADING):
            self._pending_reset = True
            return None
        if state.phase not in POSITION_PHASES:
            return None  # paused: the car is where it was
        if self._pending_reset:
            self.reset()
        return self.observe_point(state.pos_x, state.pos_z)

    def observe_point(self, x: float, z: float) -> TrackMatch | None:
        p = (x, z)
        if self._start is None:
            self._start = p
        if self._box is None:
            self._box = (x, z, x, z)
        else:
            self._box = (
                min(self._box[0], x),
                min(self._box[1], z),
                max(self._box[2], x),
                max(self._box[3], z),
            )
        if self._prev is not None:
            step = math.hypot(x - self._prev[0], z - self._prev[1])
            if step < self.teleport:
                self._distance += step
                self._note_crossings(self._prev, p)
            # else: reset to pits, restart, or a replayed results screen; the
            # segment is not a path the car drove.
        self._prev = p
        self._eliminate()
        new = self._decide()
        changed = new.decision != self._match.decision
        self._match = new
        return new if changed else None

    # evidence

    def _note_crossings(self, a: Point, b: Point) -> None:
        for t in self.tracks:
            if t.id in self._crossed or t.id not in self._alive:
                continue
            assert t.line is not None
            if (
                segment_crosses(a, b, t.line[0], t.line[1])
                and travel_direction(a, b) == t.direction
            ):
                self._crossed.add(t.id)

    def _eliminate(self) -> None:
        assert self._box is not None
        box, tol = self._box, self.box_tolerance
        for t in self.tracks:
            if t.id in self._alive and not box_contains(t.box, box, tol):  # type: ignore[arg-type]
                self._alive.discard(t.id)

    def _decide(self) -> TrackMatch:
        assert self._box is not None and self._start is not None
        alive = [t for t in self.tracks if t.id in self._alive]
        if not alive:
            return TrackMatch(None, None, "none", (), "car left every layout's bounds")
        near = [t for t in alive if distance_to_segment(self._start, *t.line) <= self.start_radius]  # type: ignore[misc]
        pool = near or alive
        cands = sorted(
            (
                Candidate(t, t.id in self._crossed, box_iou(self._box, t.box))  # type: ignore[arg-type]
                for t in pool
            ),
            key=lambda c: c.rank,
            reverse=True,
        )
        best = cands[0]
        crossed = [c for c in cands if c.line_crossed]
        if crossed:
            unique = len(crossed) == 1
            dominant = len(crossed) > 1 and crossed[0].fit - crossed[1].fit >= self.dominance
            if unique or dominant:
                conf: Confidence = "confirmed"
                why = "finish line crossed in the right direction"
                if best.fit >= 0.1:
                    why += f", layout bounds fit {best.fit:.2f}"
                if dominant:
                    why += f"; next best {crossed[1].track.name} fits {crossed[1].fit:.2f}"
            else:
                conf = "ambiguous"
                names = ", ".join(c.track.name for c in crossed[1:])
                why = f"finish line shared with {names}; bounds do not separate them"
        elif len(cands) == 1 and self._distance >= self.min_distance:
            conf = "probable"
            km = self._distance / 1000
            why = f"only layout containing the path after {km:.1f} km, line not yet crossed"
        else:
            conf = "ambiguous"
            why = f"{len(cands)} layouts still fit, line not yet crossed"
        return TrackMatch(best.track.id, best.track.name, conf, tuple(cands), why)


# geometry


def box_contains(outer: Box, inner: Box, tolerance: float) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def box_iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iz = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iz
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def segment_crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
    """True when segment a-b intersects segment c-d (touching counts)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if den == 0:
        return False  # parallel or collinear: the next frame will tell
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


def travel_direction(a: Point, b: Point) -> str | None:
    """Direction code for a move from a to b, as the table encodes it.

    The source table (gt7telemetry) keys each line on the sign of the car's
    x movement when it crossed, falling back to z only when x did not change
    at all. It is not the dominant axis: a finish straight running mostly
    along z with a slight westward drift is "NX". Match that exactly.
    """
    dx, dz = b[0] - a[0], b[1] - a[1]
    if dx > 0:
        return "PX"
    if dx < 0:
        return "NX"
    if dz > 0:
        return "PZ"
    if dz < 0:
        return "NZ"
    return None


def distance_to_segment(p: Point, a: Point, b: Point) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    ab2 = ab[0] ** 2 + ab[1] ** 2
    if ab2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ab2))
    q = (a[0] + t * ab[0], a[1] + t * ab[1])
    return math.hypot(p[0] - q[0], p[1] - q[1])
