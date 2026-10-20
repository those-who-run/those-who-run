// The track map's geometry and colours (#350 AC1, AC2, AC4), on real laps from the
// trace route: tests/fixtures/map-traces.json, which tests/test_trace_position.py
// writes and keeps current.
import { describe, expect, it } from "vitest";

import type { Trace } from "@/api/hooks";

import casesJson from "../../../tests/fixtures/map-traces.json?raw";
import {
  extentOf,
  fitBox,
  isJump,
  lineOf,
  mapSummary,
  nearestPoint,
  pedalAt,
  pedalShares,
  project,
  speedColour,
  strokeAt,
  PEDAL_WIDTH,
  type MapColours,
} from "./map";

const cases = JSON.parse(casesJson) as Record<"race_lap_1" | "pit_lap_6" | "pit_lap_6_60hz_400", Trace>;
const race = cases.race_lap_1;
const pit = cases.pit_lap_6;
const pit60 = cases.pit_lap_6_60hz_400;

const COLOURS: MapColours = {
  brake: "#f97316",
  throttle: "#22d3ee",
  coast: "#737373",
  speed: ["#3b82f6", "#2dd4bf", "#fde047"],
};

const PAD = 12;

describe("the lap in plan (AC1)", () => {
  const extent = extentOf(race)!;
  const aspect = (extent.maxX - extent.minX) / (extent.maxZ - extent.minZ);

  it("draws a clean lap as one closed line", () => {
    expect(race.x).toHaveLength(race.t.length);
    const line = lineOf(race);
    expect(line.segments).toEqual([{ start: 0, end: race.x.length - 1 }]);
    expect(line.closed).toBe(true);
  });

  it.each([
    [358, 337],
    [384, 360],
    [772, 472],
    [200, 800],
  ])("fits a %d × %d box with the lap's own aspect and one scale", (maxW, maxH) => {
    const box = fitBox(extent, maxW, maxH, PAD);
    expect(box.width).toBeLessThanOrEqual(maxW);
    expect(box.height).toBeLessThanOrEqual(maxH);
    // The inside of the box has the lap's x/z aspect, to the pixel.
    expect((box.width - 2 * PAD) / (box.height - 2 * PAD)).toBeCloseTo(aspect, 1);
    // One side of the box is as large as it may be.
    expect(
      box.width === maxW || box.height === maxH || Math.abs(box.width - maxW) <= 1 || Math.abs(box.height - maxH) <= 1,
    ).toBe(true);

    const proj = project(extent, box, PAD);
    const px = race.x.map((x, i) => proj.toPx(x, race.z[i]!));
    const xs = px.map((p) => p[0]);
    const ys = px.map((p) => p[1]);
    // Every point inside the padding, and the line touching it on both axes.
    expect(Math.min(...xs)).toBeCloseTo(PAD, 0);
    expect(Math.max(...xs)).toBeCloseTo(box.width - PAD, 0);
    expect(Math.min(...ys)).toBeCloseTo(PAD, 0);
    expect(Math.max(...ys)).toBeCloseTo(box.height - PAD, 0);
    // Equal scales: a metre across is as long as a metre down.
    const [x0, y0] = proj.toPx(extent.minX, extent.minZ);
    const [x1] = proj.toPx(extent.minX + 100, extent.minZ);
    const [, y1] = proj.toPx(extent.minX, extent.minZ + 100);
    expect(x1 - x0).toBeCloseTo(y1 - y0, 6);
  });

  it("puts x across and z down", () => {
    const proj = project(extent, fitBox(extent, 400, 400, PAD), PAD);
    const [ax, ay] = proj.toPx(0, 0);
    const [bx, by] = proj.toPx(10, 20);
    expect(bx - ax).toBeCloseTo(10 * proj.scale, 6);
    expect(by - ay).toBeCloseTo(20 * proj.scale, 6);
  });

  it("finds the point nearest a tap", () => {
    const box = fitBox(extent, 358, 337, PAD);
    const proj = project(extent, box, PAD);
    for (const i of [0, 50, 120, race.x.length - 1]) {
      const [px, py] = proj.toPx(race.x[i]!, race.z[i]!);
      const got = nearestPoint(race, proj, px + 1, py - 1)!;
      expect(Math.hypot(race.x[got]! - race.x[i]!, race.z[got]! - race.z[i]!)).toBeLessThan(5);
    }
  });
});

describe("the pit lap (AC4)", () => {
  for (const [name, lap] of [
    ["at 2 Hz", pit],
    ["at 60 Hz, thinned to 400 points", pit60],
  ] as const) {
    it(`breaks at the 120.8 m cut-scene and nowhere else, ${name}`, () => {
      const line = lineOf(lap);
      expect(line.segments).toHaveLength(2);
      expect(line.closed).toBe(false);
      const [first, second] = line.segments;
      expect(second!.start).toBe(first!.end + 1);
      const i = second!.start;
      expect(Math.hypot(lap.x[i]! - lap.x[i - 1]!, lap.z[i]! - lap.z[i - 1]!)).toBeCloseTo(120.8, 0);
      // Every step drawn is one the car drove.
      for (const s of line.segments) {
        for (let k = s.start + 1; k <= s.end; k++) {
          expect(isJump(lap, k), `step ${k}`).toBe(false);
        }
      }
    });
  }

  it("a thinned clean lap's long steps are not jumps", () => {
    // At 400 points a stretch can be half a second of a straight: 40 m or more.
    const steps = pit60.x.slice(1).map((x, k) => Math.hypot(x - pit60.x[k]!, pit60.z[k + 1]! - pit60.z[k]!));
    expect(steps.filter((s) => s > 20).length).toBeGreaterThan(10);
  });
});

describe("the colours (AC2)", () => {
  const point = (throttle: number, brake: number, speed = 200) => ({
    throttle_pct: [throttle],
    brake_pct: [brake],
    speed_kph: [speed],
  });

  it("draws brake 80% in the brake colour, throttle 100% in the throttle colour", () => {
    expect(strokeAt(point(0, 80), 0, "pedals", COLOURS, null)).toEqual({ colour: "#f97316", width: PEDAL_WIDTH.brake });
    expect(strokeAt(point(100, 0), 0, "pedals", COLOURS, null)).toEqual({
      colour: "#22d3ee",
      width: PEDAL_WIDTH.throttle,
    });
    expect(strokeAt(point(3, 2), 0, "pedals", COLOURS, null)).toEqual({ colour: "#737373", width: PEDAL_WIDTH.coast });
  });

  it("lets the brake win when both are pressed, and differs in width, not colour alone", () => {
    expect(pedalAt(100, 30)).toBe("brake");
    expect(pedalAt(6, 5)).toBe("throttle");
    expect(pedalAt(5, 5)).toBe("coast");
    expect(new Set(Object.values(PEDAL_WIDTH)).size).toBe(3);
    expect(PEDAL_WIDTH.brake).toBeGreaterThan(PEDAL_WIDTH.throttle);
    expect(PEDAL_WIDTH.throttle).toBeGreaterThan(PEDAL_WIDTH.coast);
  });

  it("runs the speed scale from slow to fast on the lap's own range", () => {
    expect(speedColour(COLOURS.speed, 0)).toBe("#3b82f6");
    expect(speedColour(COLOURS.speed, 0.5)).toBe("#2dd4bf");
    expect(speedColour(COLOURS.speed, 1)).toBe("#fde047");
    expect(speedColour(COLOURS.speed, 2)).toBe("#fde047");
    expect(strokeAt(point(0, 0, 100), 0, "speed", COLOURS, [100, 300]).colour).toBe("#3b82f6");
    expect(strokeAt(point(0, 0, 300), 0, "speed", COLOURS, [100, 300]).colour).toBe("#fde047");
  });
});

describe("the summary (R8)", () => {
  it("says the lap, the track and the time on each pedal", () => {
    const lap = { t: [0, 1, 2, 3, 4], throttle_pct: [100, 100, 0, 0, 100], brake_pct: [0, 0, 90, 0, 0] };
    expect(pedalShares(lap)).toEqual({ brake: 25, full: 50 });
    expect(mapSummary(lap, 4, "Suzuka Circuit")).toBe(
      "Lap 4 at Suzuka Circuit: on the brake for 25% of the lap, full throttle for 50%",
    );
    expect(mapSummary(lap, 4, null)).toBe("Lap 4: on the brake for 25% of the lap, full throttle for 50%");
  });

  it("reads a real lap", () => {
    const { brake, full } = pedalShares(race);
    expect(brake).toBeGreaterThan(5);
    expect(full).toBeGreaterThan(30);
    expect(brake + full).toBeLessThan(100);
  });
});
