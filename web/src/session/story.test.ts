// The race story's shape (#300 R1 to R3, R5, R7), apart from uPlot: which laps are
// points, the y range, the hollow and edge marks, the position axis and the words.
import { describe, expect, it } from "vitest";

import type { LapRow } from "@/api/hooks";
import { LAPS, SESSIONS } from "@/kit/samples";

import { raceStory, storyRange, storySummary } from "./story";

const race = SESSIONS.raceFinished;

/** A lap row with what the story reads; the rest as a clean lap. */
function lap(n: number, time_ms: number | null, over: Partial<LapRow> = {}): LapRow {
  return { ...LAPS[0]!, lap: n, time_ms, position: null, best: false, pit: false, out_lap: false, ...over };
}

/** Session 20261018-140428 (Suzuka, P1 of 16), as the issue gives it. */
const SUZUKA = [
  lap(1, 152_095, { position: 6 }),
  lap(2, 147_764, { position: 3, best: true }),
  lap(3, 148_630, { position: 1 }),
  lap(4, 148_337, { position: 1 }),
];

describe("which sessions have a story (R1)", () => {
  it("needs three complete laps", () => {
    expect(raceStory(race, SUZUKA.slice(0, 2))).toBeNull();
    expect(raceStory(race, SUZUKA.slice(0, 3))?.points).toHaveLength(3);
  });

  it("doesn't count a partial lap towards the three", () => {
    const partial = lap(3, null, { invalid: true, clean: false });
    expect(raceStory(race, [...SUZUKA.slice(0, 2), partial])).toBeNull();
  });

  it("has nothing for no laps", () => {
    expect(raceStory(race, [])).toBeNull();
  });
});

describe("the points (R2)", () => {
  const story = raceStory(race, LAPS)!;

  it("are the complete laps, in lap order, without the partial one", () => {
    expect(story.points.map((p) => p.lap)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(raceStory(race, [...LAPS].reverse())!.points.map((p) => p.lap)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("mark the best lap only", () => {
    expect(story.points.filter((p) => p.best).map((p) => p.lap)).toEqual([4]);
  });

  it("make pit and out laps hollow, with their flags for the readout", () => {
    expect(story.points.filter((p) => p.hollow).map((p) => [p.lap, p.flags])).toEqual([
      [3, ["pit"]],
      [5, ["out"]],
    ]);
  });

  it("carry each lap's position, and none for an unknown one", () => {
    expect(story.points.map((p) => p.position)).toEqual([5, 4, 3, 1, 2, 1]);
    const unknown = raceStory(race, [lap(1, 90_000, { position: 0 }), lap(2, 90_100), lap(3, 90_200)])!;
    expect(unknown.points.map((p) => p.position)).toEqual([null, null, null]);
  });
});

describe("the y range (R7)", () => {
  it("is set by the racing laps, with room either side", () => {
    // Laps 1, 2, 4 and 6: the pit (3) and out (5) laps don't count.
    const [lo, hi] = raceStory(race, LAPS)!.yRange;
    const pad = (101_233 - 97_764) * 0.1;
    expect(lo).toBeCloseTo(97_764 - pad);
    expect(hi).toBeCloseTo(101_233 + pad);
  });

  it("draws a slow stop lap at the top edge, with a marker", () => {
    const story = raceStory(race, LAPS)!;
    const out = story.points.find((p) => p.lap === 5)!;
    expect(out.edge).toBe("above");
    expect(out.ms).toBe(104_870);
    expect(out.drawnMs).toBe(story.yRange[1]);
    // The pit lap is inside the range: drawn where it is, hollow.
    const pit = story.points.find((p) => p.lap === 3)!;
    expect(pit.edge).toBeNull();
    expect(pit.drawnMs).toBe(99_412);
    expect(story.points.filter((p) => !p.hollow).every((p) => p.edge === null && p.drawnMs === p.ms)).toBe(true);
  });

  it("draws a quick one at the bottom edge", () => {
    const laps = [lap(1, 60_000), lap(2, 60_500), lap(3, 50_000, { out_lap: true }), lap(4, 60_200)];
    const story = raceStory(race, laps)!;
    expect(story.points[2]!.edge).toBe("below");
    expect(story.points[2]!.drawnMs).toBe(story.yRange[0]);
  });

  it("keeps a tenth of a second either side of laps all alike", () => {
    expect(storyRange([{ ms: 60_000, hollow: false }])).toEqual([59_900, 60_100]);
  });

  it("counts every lap when all are pit or out laps", () => {
    const range = storyRange([
      { ms: 70_000, hollow: true },
      { ms: 80_000, hollow: true },
    ]);
    expect(range[0]).toBeLessThan(70_000);
    expect(range[1]).toBeGreaterThan(80_000);
  });
});

describe("the position axis (R3)", () => {
  it("runs from P1 to the field's size", () => {
    expect(raceStory(race, SUZUKA)!.positions).toEqual({ cars: 16 });
  });

  it("is as deep as the deepest position when the field's size is unknown", () => {
    expect(raceStory({ position_shown: true, total_cars: null }, SUZUKA)!.positions).toEqual({ cars: 6 });
  });

  it("isn't there when the position isn't shown", () => {
    expect(raceStory({ ...race, position_shown: false }, SUZUKA)!.positions).toBeNull();
  });

  it("isn't there when no lap has a position", () => {
    const laps = SUZUKA.map((l) => ({ ...l, position: null }));
    expect(raceStory(race, laps)!.positions).toBeNull();
  });
});

describe("the summary (R5)", () => {
  it("names the laps, the best and the positions", () => {
    expect(raceStory(race, SUZUKA)!.summary).toBe("4 laps, best 2:27.764 on lap 2, P6 to P1");
  });

  it("matches the issue's example", () => {
    const laps = Array.from({ length: 12 }, (_, i) =>
      lap(i + 1, i === 6 ? 87_764 : 88_500 + i, { position: i < 6 ? 6 : 2, best: i === 6 }),
    );
    expect(raceStory(race, laps)!.summary).toBe("12 laps, best 1:27.764 on lap 7, P6 to P2");
  });

  it("names the pit and out laps", () => {
    expect(raceStory(race, LAPS)!.summary).toBe(
      "6 laps, best 1:37.764 on lap 4, pit on lap 3, out lap 5, P5 to P1",
    );
  });

  it("says a position held all race once", () => {
    const laps = SUZUKA.map((l) => ({ ...l, position: 1 }));
    expect(raceStory(race, laps)!.summary).toBe("4 laps, best 2:27.764 on lap 2, P1 throughout");
  });

  it("leaves the positions out when they aren't shown", () => {
    expect(raceStory({ ...race, position_shown: false }, SUZUKA)!.summary).toBe("4 laps, best 2:27.764 on lap 2");
  });

  it("lists more than one stop", () => {
    const points = raceStory(race, [
      lap(1, 60_000),
      lap(2, 70_000, { pit: true }),
      lap(3, 65_000, { out_lap: true }),
      lap(4, 60_100, { best: true }),
      lap(5, 70_100, { pit: true }),
      lap(6, 65_100, { out_lap: true }),
      lap(7, 70_200, { pit: true }),
    ])!.points;
    expect(storySummary(points, false)).toBe(
      "7 laps, best 1:00.100 on lap 4, pit on laps 2, 5 and 7, out laps 3 and 6",
    );
  });
});
