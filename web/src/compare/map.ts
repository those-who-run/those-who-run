// The track map's geometry and colours (#350), as plain functions a test can read:
// the lap's extent, the box that fits it at one scale on both axes, where a point
// lands in it, where the line breaks, what each step is drawn in, and the summary a
// screen reader hears. track-map.tsx draws with these.
import type { Trace } from "@/api/hooks";
import { pedalPct } from "@/lib/format";

/** A step in position longer than this may be a jump (#349 R2): the pit cut-scene
 * moves the car 120 to 160 m in one frame. */
export const JUMP_METRES = 20;
/** ...and is one when the car's speed can't cover it in the step's time, with this
 * much slack. The trace counts a gap longer than 0.1 s as 0.1 s, so a recording
 * thinned to 2 Hz (the fixtures) looks five times faster than it was; at 60 Hz the
 * slack changes nothing. */
const JUMP_SLACK = 6;
/** A pedal counts as pressed over this (R2). */
export const PEDAL_ON_PCT = 5;
/** Throttle at or over this counts as full in the summary: GT7 sends 0 to 255, and
 * a foot flat on the floor reads 255, or a step under it. */
const FULL_THROTTLE_PCT = 98;

export type MapMode = "pedals" | "speed";
export const MAP_MODES: readonly MapMode[] = ["pedals", "speed"];

export type Pedal = "brake" | "throttle" | "coast";

/** What the driver was doing: the brake wins when both are pressed (R2). */
export function pedalAt(throttle: number | undefined, brake: number | undefined): Pedal {
  if ((brake ?? 0) > PEDAL_ON_PCT) {
    return "brake";
  }
  if ((throttle ?? 0) > PEDAL_ON_PCT) {
    return "throttle";
  }
  return "coast";
}

export interface Extent {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
}

/** The lap's x and z extent, or null with no points. */
export function extentOf(trace: Pick<Trace, "x" | "z">): Extent | null {
  const n = Math.min(trace.x.length, trace.z.length);
  if (n === 0) {
    return null;
  }
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = trace.x[i]!;
    const z = trace.z[i]!;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minZ = Math.min(minZ, z);
    maxZ = Math.max(maxZ, z);
  }
  return { minX, maxX, minZ, maxZ };
}

/** Both laps' extent together, so lap B is drawn at the same scale. */
export function unionExtent(...extents: (Extent | null)[]): Extent | null {
  const known = extents.filter((e): e is Extent => e !== null);
  if (known.length === 0) {
    return null;
  }
  return {
    minX: Math.min(...known.map((e) => e.minX)),
    maxX: Math.max(...known.map((e) => e.maxX)),
    minZ: Math.min(...known.map((e) => e.minZ)),
    maxZ: Math.max(...known.map((e) => e.maxZ)),
  };
}

export interface Box {
  width: number;
  height: number;
}

/** The box a lap fits at one scale (R1): as wide as `maxWidth` unless that makes
 * it taller than `maxHeight`, with `pad` CSS pixels round the line. The inside of
 * the box (less the padding) has the lap's aspect. */
export function fitBox(extent: Extent, maxWidth: number, maxHeight: number, pad: number): Box {
  const w = Math.max(1, extent.maxX - extent.minX);
  const h = Math.max(1, extent.maxZ - extent.minZ);
  const inner = Math.max(1, maxWidth - 2 * pad);
  const scale = Math.min(inner / w, Math.max(1, maxHeight - 2 * pad) / h);
  return {
    width: Math.round(w * scale + 2 * pad),
    height: Math.round(h * scale + 2 * pad),
  };
}

export interface Projection {
  /** CSS pixels per metre, the same across and down. */
  scale: number;
  /** A point in metres to CSS pixels in the box: x across, z down. */
  toPx: (x: number, z: number) => [number, number];
}

/** The lap fitted to `box` with `pad` round it, at one scale, centred. */
export function project(extent: Extent, box: Box, pad: number): Projection {
  const w = Math.max(1, extent.maxX - extent.minX);
  const h = Math.max(1, extent.maxZ - extent.minZ);
  const scale = Math.min(Math.max(1, box.width - 2 * pad) / w, Math.max(1, box.height - 2 * pad) / h);
  const left = (box.width - w * scale) / 2;
  const top = (box.height - h * scale) / 2;
  return {
    scale,
    toPx: (x, z) => [left + (x - extent.minX) * scale, top + (z - extent.minZ) * scale],
  };
}

/** The step from point `i - 1` to `i` is a jump (R5): over 20 m, and further than
 * the car's speed carries it in the step's time. */
export function isJump(trace: Pick<Trace, "x" | "z" | "t" | "speed_kph">, i: number): boolean {
  if (i <= 0 || i >= trace.x.length) {
    return false;
  }
  const step = Math.hypot(trace.x[i]! - trace.x[i - 1]!, trace.z[i]! - trace.z[i - 1]!);
  if (step <= JUMP_METRES) {
    return false;
  }
  const mps = Math.max(trace.speed_kph[i] ?? 0, trace.speed_kph[i - 1] ?? 0) / 3.6;
  const dt = Math.max(0, (trace.t[i] ?? 0) - (trace.t[i - 1] ?? 0));
  return step > JUMP_SLACK * mps * dt;
}

/** A run of points drawn as one line: indexes `start` to `end`, inclusive. */
export interface Segment {
  start: number;
  end: number;
}

export interface Line {
  segments: Segment[];
  /** One unbroken lap whose end meets its start: the line closes. */
  closed: boolean;
}

/** The lap's line, broken at each jump (R5, AC4). */
export function lineOf(trace: Pick<Trace, "x" | "z" | "t" | "speed_kph">): Line {
  const n = Math.min(trace.x.length, trace.z.length);
  if (n === 0) {
    return { segments: [], closed: false };
  }
  const segments: Segment[] = [];
  let start = 0;
  let longest = 0;
  for (let i = 1; i < n; i++) {
    if (isJump(trace, i)) {
      segments.push({ start, end: i - 1 });
      start = i;
    } else {
      longest = Math.max(longest, Math.hypot(trace.x[i]! - trace.x[i - 1]!, trace.z[i]! - trace.z[i - 1]!));
    }
  }
  segments.push({ start, end: n - 1 });
  // The lap's last point is a frame short of the line it started on.
  const gap = Math.hypot(trace.x[n - 1]! - trace.x[0]!, trace.z[n - 1]! - trace.z[0]!);
  const closed = segments.length === 1 && n > 2 && gap <= Math.max(JUMP_METRES, longest);
  return { segments, closed };
}

/** The point of `trace` nearest (`px`, `py`) in the box, or null with none. */
export function nearestPoint(trace: Pick<Trace, "x" | "z">, proj: Projection, px: number, py: number): number | null {
  let best: number | null = null;
  let bestD = Infinity;
  const n = Math.min(trace.x.length, trace.z.length);
  for (let i = 0; i < n; i++) {
    const [x, y] = proj.toPx(trace.x[i]!, trace.z[i]!);
    const d = (x - px) ** 2 + (y - py) ** 2;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

export interface MapColours {
  brake: string;
  throttle: string;
  coast: string;
  /** Slow, middle and fast, as #rrggbb. */
  speed: readonly [string, string, string];
}

export interface Stroke {
  colour: string;
  /** CSS pixels. */
  width: number;
}

/** Brake, throttle and coasting differ in width as well as colour (R2, ADR 0004
 * point 3). */
export const PEDAL_WIDTH: Record<Pedal, number> = {
  brake: 5,
  throttle: 3,
  coast: 1.5,
};
export const SPEED_WIDTH = 3;

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as [number, number, number];
}

/** The speed scale's colour at `f` (0 slow, 1 fast), between its three stops. */
export function speedColour(stops: MapColours["speed"], f: number): string {
  const v = Math.min(1, Math.max(0, Number.isFinite(f) ? f : 0)) * 2;
  const [a, b] = v <= 1 ? [stops[0], stops[1]] : [stops[1], stops[2]];
  const k = v <= 1 ? v : v - 1;
  const [ra, ga, ba] = hexToRgb(a);
  const [rb, gb, bb] = hexToRgb(b);
  const mix = (p: number, q: number) =>
    Math.round(p + (q - p) * k)
      .toString(16)
      .padStart(2, "0");
  return `#${mix(ra, rb)}${mix(ga, gb)}${mix(ba, bb)}`;
}

/** The lap's slowest and fastest speed, for the speed scale and its legend. */
export function speedRange(trace: Pick<Trace, "speed_kph">): [number, number] | null {
  if (trace.speed_kph.length === 0) {
    return null;
  }
  return [Math.min(...trace.speed_kph), Math.max(...trace.speed_kph)];
}

/** How the step ending at point `i` is drawn: by the pedals at its start, or by its
 * speed on the lap's own scale. */
export function strokeAt(
  trace: Pick<Trace, "throttle_pct" | "brake_pct" | "speed_kph">,
  i: number,
  mode: MapMode,
  colours: MapColours,
  range: [number, number] | null,
): Stroke {
  if (mode === "pedals") {
    const p = pedalAt(trace.throttle_pct[i], trace.brake_pct[i]);
    return { colour: colours[p], width: PEDAL_WIDTH[p] };
  }
  const [lo, hi] = range ?? [0, 1];
  const v = trace.speed_kph[i] ?? lo;
  return {
    colour: speedColour(colours.speed, hi > lo ? (v - lo) / (hi - lo) : 0),
    width: SPEED_WIDTH,
  };
}

/** The shares of the lap's time on the brake and at full throttle, 0 to 100. */
export function pedalShares(trace: Pick<Trace, "t" | "throttle_pct" | "brake_pct">): { brake: number; full: number } {
  let total = 0;
  let brake = 0;
  let full = 0;
  for (let i = 0; i + 1 < trace.t.length; i++) {
    const dt = trace.t[i + 1]! - trace.t[i]!;
    total += dt;
    if (pedalAt(trace.throttle_pct[i], trace.brake_pct[i]) === "brake") {
      brake += dt;
    } else if ((trace.throttle_pct[i] ?? 0) >= FULL_THROTTLE_PCT) {
      full += dt;
    }
  }
  return total > 0 ? { brake: (100 * brake) / total, full: (100 * full) / total } : { brake: 0, full: 0 };
}

/** The map's text (R8): "Lap 4 at Suzuka Circuit: on the brake for 18% of the lap,
 * full throttle for 61%". */
export function mapSummary(
  trace: Pick<Trace, "t" | "throttle_pct" | "brake_pct">,
  lap: number,
  track: string | null,
): string {
  const { brake, full } = pedalShares(trace);
  const where = track ? `Lap ${lap} at ${track}` : `Lap ${lap}`;
  return `${where}: on the brake for ${pedalPct(brake)} of the lap, full throttle for ${pedalPct(full)}`;
}
