// The session page's figures (#298), worked out from the API's values as plain
// functions, so the words and sums are tested apart from the markup. Nothing here
// formats a number: format.ts does that in the components.
import type { LapRow, Session } from "@/api/hooks";

/** Which headline the hero shows (R1). */
export type Headline =
  | { kind: "live" }
  | { kind: "finished" }
  | { kind: "ended" }
  | { kind: "timed" }
  | { kind: "best" };

export function headline(s: Session): Headline {
  if (!s.closed) {
    return { kind: "live" };
  }
  if (s.kind === "lap_race") {
    // Retired, paused or stopped: Python words those endings (ADR 0004 point 6).
    return s.finished ? { kind: "finished" } : { kind: "ended" };
  }
  if (s.kind === "timed_field") {
    return { kind: "timed" };
  }
  return { kind: "best" };
}

/** Python's line in sentence case: "Retired on lap 3 of 12, running P15". */
export function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Laps with a time to compare: not partial, not untimed. */
export function timed(laps: LapRow[]): LapRow[] {
  return laps.filter((l) => !l.invalid && l.time_ms != null && l.time_ms > 0);
}

/** The best lap's row: the one the API flags, else the quickest timed lap. */
export function bestLap(laps: LapRow[]): LapRow | null {
  const flagged = laps.find((l) => l.best && !l.invalid && l.time_ms != null);
  if (flagged) {
    return flagged;
  }
  const t = timed(laps);
  return t.length ? t.reduce((a, b) => (b.time_ms! < a.time_ms! ? b : a)) : null;
}

/** The average of the complete, clean laps (not pit, out, partial or restart:
 * `LapRow.clean`), and how many it counts (R2). */
export function cleanAverage(laps: LapRow[]): { ms: number | null; count: number } {
  const clean = timed(laps).filter((l) => l.clean);
  if (!clean.length) {
    return { ms: null, count: 0 };
  }
  return { ms: clean.reduce((n, l) => n + l.time_ms!, 0) / clean.length, count: clean.length };
}

/** Fuel as the page shows it: a share of the tank when its size is known, else
 * GT7's own amount. */
export type FuelScale = "pct" | "units";

export function fuelScale(s: Pick<Session, "fuel_capacity">): FuelScale {
  return s.fuel_capacity != null && s.fuel_capacity > 0 ? "pct" : "units";
}

/** An amount of fuel on the page's scale: per cent of the tank, or as GT7 sent it. */
export function fuelOnScale(v: number | null | undefined, s: Pick<Session, "fuel_capacity">): number | null {
  if (v == null || !Number.isFinite(v)) {
    return null;
  }
  return fuelScale(s) === "pct" ? (100 * v) / s.fuel_capacity! : v;
}

/** Fuel per lap: the mean of the clean laps' use (a refuel or a pit lap would
 * skew it), on the page's scale. */
export function fuelPerLap(laps: LapRow[], s: Pick<Session, "fuel_capacity">): number | null {
  const used = laps.filter((l) => l.clean && !l.invalid && l.fuel_used != null && l.fuel_used >= 0);
  if (!used.length) {
    return null;
  }
  return fuelOnScale(used.reduce((n, l) => n + l.fuel_used!, 0) / used.length, s);
}

/** The flags a lap carries, in the order the Lap cell shows them. */
export function lapFlags(l: LapRow): ("pit" | "out" | "partial" | "restart")[] {
  const flags: ("pit" | "out" | "partial" | "restart")[] = [];
  if (l.pit) {
    flags.push("pit");
  }
  if (l.out_lap) {
    flags.push("out");
  }
  // A restart lap is partial too; its own flag says why.
  if (l.restart) {
    flags.push("restart");
  } else if (l.invalid) {
    flags.push("partial");
  }
  return flags;
}

// Picks (R5): held in the URL as `?pick=2,4`, oldest first, so Back from compare
// comes back to the same picks.

/** The picks in `?pick=`, oldest first: lap numbers, at most two, no repeats. */
export function parsePicks(param: string | null): number[] {
  const out: number[] = [];
  for (const part of (param ?? "").split(",")) {
    const n = Number(part);
    if (part !== "" && Number.isInteger(n) && n >= 0 && !out.includes(n)) {
      out.push(n);
    }
  }
  return out.slice(-2);
}

/** Ticking or unticking a lap: a third pick replaces the oldest. */
export function togglePick(picks: number[], lap: number): number[] {
  if (picks.includes(lap)) {
    return picks.filter((p) => p !== lap);
  }
  return [...picks, lap].slice(-2);
}

/** Two laps for compare's `a` and `b`, in lap order. */
export function comparePair(picks: number[]): [number, number] | null {
  if (picks.length !== 2) {
    return null;
  }
  const [x, y] = [...picks].sort((p, q) => p - q) as [number, number];
  return [x, y];
}

/** With nothing picked: the best lap and the next fastest timed lap. A lap quicker
 * than the best is one the API left out of the best (a race's first lap, from a
 * rolling start), so it isn't the "next" either. */
export function bestAndNext(laps: LapRow[]): [number, number] | null {
  const best = bestLap(laps);
  if (!best) {
    return null;
  }
  const next = timed(laps)
    .filter((l) => l.lap !== best.lap && l.time_ms! >= best.time_ms!)
    .sort((a, b) => a.time_ms! - b.time_ms!)[0];
  return next ? [best.lap, next.lap] : null;
}

/** Lap compare's address (#299). */
export function compareHref(sessionId: string, [a, b]: [number, number]): string {
  return `/sessions/${encodeURIComponent(sessionId)}/compare?a=${a}&b=${b}`;
}

/** The lap being driven while the session is live: the engineer's lap when it is
 * ahead of the store, else the one after the last stored. */
export function lapInProgress(laps: LapRow[], engineerLap: number | null | undefined): number {
  const next = laps.length ? Math.max(...laps.map((l) => l.lap)) + 1 : 1;
  return Math.max(next, engineerLap ?? 0);
}
