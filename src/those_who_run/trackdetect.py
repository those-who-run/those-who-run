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
   a box with their forward twin and differ only here. Two witnesses: GT7's
   own lap counter (when it increments the car is on the line, whatever the
   table says) and the car's path cutting the table's segment, widened to
   span the track because the recorded segments are only a car's width.
   The lap counter outranks the path. Lines of unrelated layouts lie all
   over a circuit, so a path crossing counts only while racing and only
   until the lap counter has shown where this circuit's line is: at Fuji the
   pit exit runs through Tokyo East's line, and a lap of Tokyo East cuts
   Suzuka's (2026-10-15).

Joined part way (``join``: the engineer started mid-lap, #265), facts 1 and 3
are not what they seem: the first position is wherever the car was, not near a
line, and the path to the next tick is part of a lap. Lines of other layouts lie
all over a circuit, so a path crossing counts for nothing, and the first lap
boundary only says where the line is: the box and the distance before it are not
a whole lap, so no layout is judged on them. At Suzuka (2026-10-18) the start
mid-lap was near Lago Maggiore's line and the path crossed it; the detector said
"probable Lago Maggiore - East Reverse" 28 s in.

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
LAP_PHASES = frozenset({Phase.IN_RACE, Phase.FINISHED})  # lap counter is meaningful
MAX_REPORTED_CANDIDATES = 8  # an unanchored pool can be most of the table


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
    # Set when the layout is ambiguous but every crossed candidate is the same
    # circuit (Fuji and Fuji Short share a line and a box in the table).
    family: str | None = None

    @property
    def candidate_ids(self) -> tuple[int, ...]:
        return tuple(c.track.id for c in self.candidates)

    @property
    def decision(self) -> tuple[int | None, str]:
        """What callers act on: the track and how sure we are. Candidate lists, fit
        values and wording shift every frame while the pool narrows; those are
        visible on ``match`` but do not count as a change."""
        return (self.track_id, self.confidence)


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
        line_radius_m: float = 150.0,
        line_half_width_m: float = 50.0,
        tick_radius_m: float = 30.0,
        min_fit: float = 0.5,
        length_tolerance: float = 0.08,
    ) -> None:
        self.tracks = tuple(t for t in (tracks or load_tracks()) if t.has_geometry)
        self.box_tolerance = box_tolerance_m
        self.start_radius = start_radius_m
        self.teleport = teleport_m
        self.min_distance = min_distance_m
        self.dominance = dominance
        self.line_radius = line_radius_m
        self.line_slack = line_half_width_m
        self.tick_radius = tick_radius_m
        self.min_fit = min_fit
        self.length_tolerance = length_tolerance
        # Table lines are two frames of one car's crossing, 7 to 68 m long, and
        # can sit a track-width away from where the next driver crosses.
        self._lines: dict[int, tuple[Point, Point]] = {
            t.id: widen_segment(t.line[0], t.line[1], line_half_width_m)  # type: ignore[index]
            for t in self.tracks
        }
        self.reset()

    def reset(self) -> None:
        """Forget everything: call on a race restart (the car is teleported to the grid)."""
        self._pending_reset = False
        self._anchors: list[Point] = []  # places the car is known to be on the circuit
        self._prev: Point | None = None
        self._velocity: Point | None = None
        self._box: Box | None = None
        self._distance = 0.0
        self._last_lap: int | None = None
        self._lap_distance = 0.0  # metres since the last lap boundary
        self._lap_complete = False  # a full lap has been driven: the box is the lap's box
        self._lap_length: float | None = None  # length of the last completed lap
        self._crossed: set[int] = set()
        self._line_known = False  # the lap counter has put the car on a layout's line
        self._alive: set[int] = {t.id for t in self.tracks}
        self._match: TrackMatch = NO_MATCH
        self._joined = False  # see join
        self._partial = False  # the lap in progress is the one joined part way

    def join(self) -> None:
        """The frames start part way through a lap (see the top): call before the
        first one."""
        self.reset()
        self._joined = self._partial = True

    @property
    def match(self) -> TrackMatch:
        return self._match

    def is_alive(self, track_id: int | None) -> bool:
        """Whether the layout still fits everything seen since the last reset."""
        return track_id in self._alive

    @property
    def distance_m(self) -> float:
        """Metres driven since reset, teleports excluded."""
        return self._distance

    @property
    def lap_length_m(self) -> float | None:
        """Length of the last completed lap, once the lap counter has closed one."""
        return self._lap_length

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
        # The chequered flag is a lap boundary too: a lap-count race reports
        # total_laps + 1 with the FINISHED phase on the frame that closes the last lap.
        lap = state.current_lap if state.phase in LAP_PHASES else None
        return self.observe_point(
            state.pos_x, state.pos_z, lap=lap, velocity=(state.vel_x, state.vel_z)
        )

    def observe_point(
        self,
        x: float,
        z: float,
        lap: int | None = None,
        velocity: Point | None = None,
    ) -> TrackMatch | None:
        """Feed one position; ``lap`` is GT7's lap counter while racing, else None.

        ``velocity`` is the car's world-frame (x, z) velocity on this frame. When
        it is given and not zero, it sets the direction of travel used against
        the table's line directions; otherwise the step from the previous
        position does. One position step is a poor witness: a frozen frame has
        none, and on a straight running mostly along z one frame of drift can
        flip its x sign.

        Anchors (positions known to be on the circuit, used to find layouts
        whose finish line is close by): the first frame, the first racing
        frame, and every point where the lap counter incremented. The first
        frame alone is not enough: GT7's pre-session screens report positions
        that are not the car's.
        """
        p = (x, z)
        self._velocity = velocity
        if not self._anchors and not self._joined:
            self._anchors.append(p)
        if self._box is None:
            self._box = (x, z, x, z)
        else:
            self._box = (
                min(self._box[0], x),
                min(self._box[1], z),
                max(self._box[2], x),
                max(self._box[3], z),
            )
        moved = False
        if self._prev is not None:
            step = math.hypot(x - self._prev[0], z - self._prev[1])
            if step < self.teleport:
                moved = True
                self._distance += step
                self._lap_distance += step
                if lap is not None and not self._line_known and not self._joined:
                    self._note_crossings(self._prev, p)
            # else: reset to pits, restart, or a replayed results screen; the
            # segment is not a path the car drove.
        if lap is not None:
            if self._joined and self._last_lap is None:
                pass  # mid-lap: neither an anchor nor the start of a lap
            elif (self._last_lap is None or self._last_lap < 1) and lap >= 1:
                self._anchors.append(p)
                if moved:
                    assert self._prev is not None
                    self._first_lap(self._prev, p)
            elif self._last_lap is not None and lap > self._last_lap >= 1 and moved:
                assert self._prev is not None
                self._lap_boundary(self._prev, p)
            self._last_lap = lap
        self._prev = p
        self._eliminate()
        new = self._decide()
        changed = new.decision != self._match.decision
        self._match = new
        return new if changed else None

    # evidence

    def _direction(self, a: Point, b: Point) -> str | None:
        """Which way the car is going between a and b: its velocity, else the step."""
        if self._velocity is not None:
            vx, vz = self._velocity
            if vx or vz:
                return travel_direction((0.0, 0.0), (vx, vz))
        return travel_direction(a, b)

    def _note_crossings(self, a: Point, b: Point) -> None:
        direction = self._direction(a, b)
        for t in self.tracks:
            if t.id in self._crossed or t.id not in self._alive:
                continue
            c, d = self._lines[t.id]
            if direction == t.direction and segment_crosses(a, b, c, d):
                self._crossed.add(t.id)

    def _first_lap(self, a: Point, b: Point) -> None:
        """The lap counter started lap 1 between a and b.

        A flying or rolling start ticks on the finish line, which settles which
        lines were real: layouts whose line is under the car are crossed, and
        crossings of any other line were somewhere else on the circuit. A
        standing start ticks on the grid, away from every line, and settles
        nothing. Either way lap 1 starts here: driving to the line from the pit
        or the formation lap is not part of it.
        """
        direction = self._direction(a, b)
        on_line = {
            t.id
            for t in self.tracks
            if t.id in self._alive
            and t.direction == direction
            and distance_to_segment(b, *t.line) <= self.tick_radius  # type: ignore[misc]
        }
        if on_line:
            self._crossed = on_line
            self._line_known = True
        self._lap_distance = 0.0

    def _lap_boundary(self, a: Point, b: Point) -> None:
        """GT7 incremented the lap counter between a and b: the car is on the finish line.

        Every live layout whose line is within ``line_radius`` and faces the
        way the car is going has been crossed; every other live layout cannot
        be this circuit and is dropped. This is what makes a short or
        misplaced table segment survivable.

        The lap just closed is a whole lap of this circuit, so the driven box
        is now the lap's box and the distance since the previous boundary is
        its length. A layout whose box the lap fills poorly is a neighbour in
        coordinate space, not the circuit: a new track's line often lands near
        a known one's, because most layouts sit near their own origin. A known
        lap length that is off rules a layout out the same way.

        Lines can be up to ``line_radius`` off, but a line much further away
        than the nearest one is another circuit's: Tokyo East's sits 118 m from
        Fuji's, beside the pit lane.

        When no live layout faces the way the car is going, it depends on how
        sure that direction is. With none at all (a frozen frame: no step, no
        velocity) or with the velocity and the step disagreeing (one frame of
        drift on a straight along z), the reading is suspect, so the boundary
        settles nothing and eliminates nothing. A direction both agree on is a
        fact: the car is driving a layout the table lacks, such as the reverse
        of a listed one, and every live layout goes.
        """
        direction = self._direction(a, b)
        self._anchors.append(b)
        assert self._box is not None
        dist = {
            t.id: distance_to_segment(b, *t.line)  # type: ignore[misc]
            for t in self.tracks
            if t.id in self._alive and t.direction == direction
        }
        step = travel_direction(a, b)
        whole, self._partial = not self._partial, False
        if not dist and (direction is None or (step is not None and step != direction)):
            if whole:
                self._lap_length = self._lap_distance  # still a whole lap, just no direction
            self._lap_distance = 0.0
            return
        reach = min(self.line_radius, min(dist.values(), default=0.0) + self.line_slack)
        for t in self.tracks:
            if t.id not in self._alive:
                continue
            assert t.line is not None and t.box is not None
            if dist.get(t.id, math.inf) > reach:
                self._alive.discard(t.id)
                continue
            self._crossed.add(t.id)
            if not whole:
                continue  # joined part way: the line is all this lap says
            if box_iou(self._box, t.box) < self.min_fit or (
                t.length_m
                and abs(self._lap_distance - t.length_m) > self.length_tolerance * t.length_m
            ):
                self._alive.discard(t.id)
        self._line_known = True
        if whole:
            self._lap_complete = True
            self._lap_length = self._lap_distance
        self._lap_distance = 0.0

    def _eliminate(self) -> None:
        assert self._box is not None
        box, tol = self._box, self.box_tolerance
        for t in self.tracks:
            if t.id in self._alive and not box_contains(t.box, box, tol):  # type: ignore[arg-type]
                self._alive.discard(t.id)

    def _decide(self) -> TrackMatch:
        assert self._box is not None
        alive = [t for t in self.tracks if t.id in self._alive]
        if not alive:
            return TrackMatch(None, None, "none", (), "no layout fits the lap counter and path")
        near = [
            t
            for t in alive
            if self._anchors
            and min(distance_to_segment(an, *t.line) for an in self._anchors)  # type: ignore[misc]
            <= self.start_radius
        ]
        crossed_any = [t for t in alive if t.id in self._crossed]
        # Anchor the candidate pool on something physical: a finish line close
        # to where the car has been, or a line actually crossed. Without
        # either, dozens of unrelated layouts contain the path.
        if near:
            pool = near
        elif crossed_any:
            pool = crossed_any
        else:
            top = tuple(
                sorted(
                    (Candidate(t, False, box_iou(self._box, t.box)) for t in alive),  # type: ignore[arg-type]
                    key=lambda c: c.rank,
                    reverse=True,
                )
            )[:MAX_REPORTED_CANDIDATES]
            why = (
                f"no finish line within {self.start_radius:.0f} m of where the car has been"
                f" and none crossed yet; {len(alive)} layouts contain the path"
            )
            return TrackMatch(None, None, "ambiguous", top, why)
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
            if (unique or dominant) and self._lap_complete:
                conf: Confidence = "confirmed"
                why = f"finish line crossed, a full lap fits the layout ({best.fit:.2f})"
                if dominant:
                    why += f"; next best {crossed[1].track.name} fits {crossed[1].fit:.2f}"
            elif unique or dominant:
                conf = "probable"
                why = "finish line crossed in the right direction, no full lap yet"
            else:
                conf = "ambiguous"
                names = ", ".join(c.track.name for c in crossed[1:])
                why = f"finish line shared with {names}; bounds do not separate them"
                families = {family_name(c.track.name) for c in crossed}
                if len(families) == 1:
                    family = families.pop()
                    why += f"; all {family}"
                    return TrackMatch(
                        best.track.id, best.track.name, conf, tuple(cands), why, family
                    )
            return TrackMatch(best.track.id, best.track.name, conf, tuple(cands), why)
        if len(cands) == 1 and self._distance >= self.min_distance:
            km = self._distance / 1000
            why = f"only layout containing the path after {km:.1f} km, line not yet crossed"
            return TrackMatch(best.track.id, best.track.name, "probable", tuple(cands), why)
        # Several layouts and no crossing: naming one would be a guess.
        why = f"{len(cands)} layouts near the start still fit, line not yet crossed"
        return TrackMatch(None, None, "ambiguous", tuple(cands[:MAX_REPORTED_CANDIDATES]), why)


def family_name(name: str) -> str:
    """The circuit a layout belongs to: the name without its layout part.

    "Fuji International Speedway (Short)" and "Tokyo Expressway - East Clockwise"
    give "Fuji International Speedway" and "Tokyo Expressway".
    """
    return name.split(" (")[0].split(" - ")[0].strip()


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


def widen_segment(a: Point, b: Point, half_width: float) -> tuple[Point, Point]:
    """The segment a-b extended along its own direction to 2*half_width long, same midpoint."""
    mx, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dz)
    if length == 0:
        return a, b
    ux, uz = dx / length, dz / length
    return (mx - ux * half_width, mz - uz * half_width), (
        mx + ux * half_width,
        mz + uz * half_width,
    )


def distance_to_segment(p: Point, a: Point, b: Point) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    ab2 = ab[0] ** 2 + ab[1] ** 2
    if ab2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ab2))
    q = (a[0] + t * ab[0], a[1] + t * ab[1])
    return math.hypot(p[0] - q[0], p[1] - q[1])
