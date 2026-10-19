// The race story's figures (#300), as plain functions, so the chart's shape and
// words are tested apart from uPlot: which laps are points, the lap-time range, the
// points drawn at its edge, the position axis and the screen reader's summary.
// It is small and has no chart in it, so the session route imports it to decide
// whether the chart (a lazy chunk) is drawn at all.
import type { LapRow, Session } from "@/api/hooks";
import { lapTime } from "@/lib/format";

import { bestLap, timed } from "./model";

/** Fewer complete laps than this and there is no chart (R1). */
export const MIN_STORY_LAPS = 3;

/** A lap time's flag in the readout: pit and out laps are drawn hollow (R2). */
export type StoryFlag = "pit" | "out";

export interface StoryPoint {
  lap: number;
  /** The lap's time. */
  ms: number;
  /** Where the point is drawn: the time, or the range's edge when it is outside. */
  drawnMs: number;
  /** Outside the y range: drawn at that edge, with a marker (R7). */
  edge: "above" | "below" | null;
  position: number | null;
  best: boolean;
  /** A pit or out lap: hollow, and left out of the y range. */
  hollow: boolean;
  flags: StoryFlag[];
}

export interface Story {
  points: StoryPoint[];
  /** The lap-time axis, in ms, from the laps that aren't pit or out laps. */
  yRange: [number, number];
  /** The position axis, P1 to the field's size; null when it isn't shown (R3). */
  positions: { cars: number } | null;
  /** What the chart shows, for a screen reader (R5). */
  summary: string;
}

/** Room above and below the laps, so no point sits on the plot's edge: a tenth of
 * the spread, and at least a tenth of a second. */
function padded(lo: number, hi: number): [number, number] {
  const pad = Math.max((hi - lo) * 0.1, 100);
  return [lo - pad, hi + pad];
}

/** The y range from the racing laps: pit and out laps are slow by design, and one
 * would flatten the rest (R7). With none but those, every lap counts. */
export function storyRange(points: Pick<StoryPoint, "ms" | "hollow">[]): [number, number] {
  const racing = points.filter((p) => !p.hollow);
  const ms = (racing.length ? racing : points).map((p) => p.ms);
  return padded(Math.min(...ms), Math.max(...ms));
}

/** "lap 3", "laps 3 and 7", "laps 3, 7 and 9". */
function lapList(laps: number[]): string {
  const words = laps.length > 1 ? `${laps.slice(0, -1).join(", ")} and ${laps[laps.length - 1]}` : String(laps[0]);
  return `lap${laps.length > 1 ? "s" : ""} ${words}`;
}

/** "12 laps, best 1:27.764 on lap 7, P6 to P2". The pit and out laps are named
 * too, since the chart shows them apart. */
export function storySummary(points: StoryPoint[], positionShown: boolean): string {
  const parts = [`${points.length} laps`];
  const best = points.find((p) => p.best);
  if (best) {
    parts.push(`best ${lapTime(best.ms)} on lap ${best.lap}`);
  }
  const pit = points.filter((p) => p.flags.includes("pit")).map((p) => p.lap);
  const out = points.filter((p) => p.flags.includes("out")).map((p) => p.lap);
  if (pit.length) {
    parts.push(`pit on ${lapList(pit)}`);
  }
  if (out.length) {
    parts.push(`out ${lapList(out)}`);
  }
  if (positionShown) {
    const placed = points.filter((p) => p.position != null && p.position >= 1);
    if (placed.length) {
      const first = placed[0]!.position!;
      const last = placed[placed.length - 1]!.position!;
      const steady = placed.every((p) => p.position === first);
      parts.push(steady ? `P${first} throughout` : `P${first} to P${last}`);
    }
  }
  return parts.join(", ");
}

/** The race story for a session's laps, or null when it has fewer than three
 * complete laps (R1). Partial laps are left out (R2). */
export function raceStory(
  session: Pick<Session, "position_shown" | "total_cars">,
  laps: LapRow[],
): Story | null {
  const complete = timed(laps).sort((a, b) => a.lap - b.lap);
  if (complete.length < MIN_STORY_LAPS) {
    return null;
  }
  const best = bestLap(laps);
  const base = complete.map((l) => {
    const flags: StoryFlag[] = [];
    if (l.pit) {
      flags.push("pit");
    }
    if (l.out_lap) {
      flags.push("out");
    }
    return {
      lap: l.lap,
      ms: l.time_ms!,
      position: l.position != null && l.position >= 1 ? l.position : null,
      best: best?.lap === l.lap,
      hollow: flags.length > 0,
      flags,
    };
  });
  const yRange = storyRange(base);
  const points: StoryPoint[] = base.map((p) => {
    const edge = p.ms > yRange[1] ? "above" : p.ms < yRange[0] ? "below" : null;
    return { ...p, edge, drawnMs: edge === "above" ? yRange[1] : edge === "below" ? yRange[0] : p.ms };
  });

  const placed = points.map((p) => p.position).filter((p): p is number => p != null);
  const shown = session.position_shown && placed.length > 0;
  const cars = Math.max(session.total_cars ?? 0, ...placed, 1);
  return {
    points,
    yRange,
    positions: shown ? { cars } : null,
    summary: storySummary(points, shown),
  };
}
