// Which laps lap compare shows (#299 R1, R9), from the URL (ADR 0004 point 7: the
// URL is the view's state): `a`, `b`, `b_session` and `zoom`. Pure, so a test can
// read it.
//
// - Lap A is `?a`, or the session's best lap.
// - Lap B is `?b`, or the next fastest; from `?b_session`, that session's best.
// - A lap or session that isn't there falls back to the default, with a notice.
// - With no other timed lap, B is A, and the page asks for another (`alone`).
import type { LapRow } from "@/api/hooks";

import type { XRange } from "@/charts/gestures";

export interface PickParams {
  a: string | null;
  b: string | null;
  bSession: string | null;
}

export interface Picks {
  a: number | null;
  b: number | null;
  /** The session lap B is from: this one unless `b_session` names another. */
  bSession: string;
  /** Why a pick in the URL wasn't used, in sentences. */
  notices: string[];
  /** No other lap to compare with: B is A. */
  alone: boolean;
}

function timed(lap: LapRow): boolean {
  return typeof lap.time_ms === "number" && lap.time_ms > 0;
}

/** Fastest first; laps with no time last, in lap order. */
function byTime(laps: readonly LapRow[]): LapRow[] {
  return [...laps].sort((x, y) => (x.time_ms ?? Infinity) - (y.time_ms ?? Infinity) || x.lap - y.lap);
}

/** The session's best lap (as the card picks it), and the next fastest. */
export function defaultLaps(laps: readonly LapRow[]): { a: number | null; b: number | null; alone: boolean } {
  const fastest = byTime(laps.filter(timed));
  const best = laps.find((l) => l.best) ?? fastest[0] ?? laps[0];
  if (!best) {
    return { a: null, b: null, alone: false };
  }
  const next = fastest.find((l) => l.lap !== best.lap);
  return next ? { a: best.lap, b: next.lap, alone: false } : { a: best.lap, b: best.lap, alone: true };
}

/** Lap B's default from another session: its best lap, or its first. */
export function otherSessionLap(laps: readonly LapRow[]): number | null {
  return (laps.find((l) => l.best) ?? byTime(laps.filter(timed))[0] ?? laps[0])?.lap ?? null;
}

/** A whole lap number from the URL, or null. */
function lapParam(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) {
    return null;
  }
  return Number(raw);
}

/**
 * The laps to show. `bLaps` is lap B's session's laps when that is another session
 * (undefined while they load), and `sameTrack` the ids of this session's
 * same-track sessions (undefined while they load).
 */
export function resolvePicks(
  id: string,
  params: PickParams,
  laps: readonly LapRow[],
  bLaps: readonly LapRow[] | undefined,
  sameTrack: readonly string[] | undefined,
): Picks {
  const notices: string[] = [];
  const has = (rows: readonly LapRow[], n: number | null) => n !== null && rows.some((l) => l.lap === n);
  const defaults = defaultLaps(laps);

  let a = lapParam(params.a);
  if (!has(laps, a)) {
    if (params.a !== null) {
      notices.push(`There's no lap ${params.a} in this session, so lap A is the best lap.`);
    }
    a = defaults.a;
  }

  let bSession = params.bSession ?? id;
  if (bSession !== id && sameTrack !== undefined && !sameTrack.includes(bSession)) {
    notices.push("That session isn't one at this track, so lap B is from this session.");
    bSession = id;
  }

  const rows = bSession === id ? laps : bLaps;
  let b = lapParam(params.b);
  let alone = false;
  if (rows === undefined) {
    b = null; // lap B's session's laps are still loading
  } else if (!has(rows, b)) {
    const other = bSession !== id;
    if (params.b !== null) {
      notices.push(
        other
          ? `There's no lap ${params.b} in that session, so lap B is its best lap.`
          : `There's no lap ${params.b} in this session, so lap B is the next fastest.`,
      );
    }
    b = other ? otherSessionLap(rows) : defaults.b;
    alone = !other && defaults.alone;
  }
  return { a, b, bSession, notices, alone };
}

/** `?zoom=12.30-45.60`: the x range, or null for none (or a bad one). */
export function parseZoom(raw: string | null): XRange | null {
  const m = raw?.match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$/);
  if (!m) {
    return null;
  }
  const lo = Number(m[1]);
  const hi = Number(m[2]);
  return hi > lo ? [lo, hi] : null;
}

/** The x range as `?zoom` writes it. */
export function formatZoom(range: XRange): string {
  return `${range[0].toFixed(2)}-${range[1].toFixed(2)}`;
}
