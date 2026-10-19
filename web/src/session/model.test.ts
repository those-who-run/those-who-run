// The session page's sums and picks (#298 R1, R2, R5), apart from the markup.
import { describe, expect, it } from "vitest";

import { LAPS, SESSIONS } from "@/kit/samples";

import {
  bestAndNext,
  bestLap,
  cleanAverage,
  compareHref,
  comparePair,
  fuelOnScale,
  fuelPerLap,
  fuelScale,
  headline,
  lapFlags,
  lapInProgress,
  parsePicks,
  togglePick,
} from "./model";

describe("headline", () => {
  it.each([
    ["raceFinished", "finished"],
    ["retired", "ended"],
    ["timed", "timed"],
    ["timeTrial", "best"],
  ] as const)("%s shows %s", (name, kind) => {
    expect(headline(SESSIONS[name]).kind).toBe(kind);
  });

  it("an open session is live", () => {
    expect(headline({ ...SESSIONS.raceFinished, closed: false }).kind).toBe("live");
  });
});

describe("the laps' figures", () => {
  it("averages the clean laps only", () => {
    // Laps 1, 2 and 4: not the pit (3), out (5), restart (6) or partial (7) lap.
    expect(cleanAverage(LAPS)).toEqual({ ms: (101_233 + 98_630 + 97_764) / 3, count: 3 });
    expect(cleanAverage([])).toEqual({ ms: null, count: 0 });
  });

  it("finds the best lap by its flag", () => {
    expect(bestLap(LAPS)?.lap).toBe(4);
    expect(bestLap(LAPS.map((l) => ({ ...l, best: false })))?.lap).toBe(4);
  });

  it("flags each lap as the Lap cell shows it", () => {
    expect(LAPS.map(lapFlags)).toEqual([[], [], ["pit"], [], ["out"], ["restart"], ["partial"]]);
  });

  it("puts fuel on the tank's scale when it is known, else GT7's", () => {
    expect(fuelScale({ fuel_capacity: 100 })).toBe("pct");
    expect(fuelScale({ fuel_capacity: null })).toBe("units");
    expect(fuelOnScale(25, { fuel_capacity: 50 })).toBe(50);
    expect(fuelOnScale(25, { fuel_capacity: null })).toBe(25);
    expect(fuelOnScale(null, { fuel_capacity: 50 })).toBeNull();
    // The clean laps' mean: 3.3, 3.2 and 3.1.
    expect(fuelPerLap(LAPS, { fuel_capacity: 100 })).toBeCloseTo(3.2);
  });

  it("knows the lap being driven", () => {
    expect(lapInProgress(LAPS, null)).toBe(8);
    expect(lapInProgress(LAPS, 9)).toBe(9);
    expect(lapInProgress([], null)).toBe(1);
  });
});

describe("picks", () => {
  it("reads ?pick= oldest first, two at most", () => {
    expect(parsePicks("2,4")).toEqual([2, 4]);
    expect(parsePicks("2,4,5")).toEqual([4, 5]);
    expect(parsePicks("x,2,2,")).toEqual([2]);
    expect(parsePicks(null)).toEqual([]);
  });

  it("a third pick replaces the oldest; a second tick unpicks", () => {
    expect(togglePick([2, 4], 5)).toEqual([4, 5]);
    expect(togglePick([2, 4], 2)).toEqual([4]);
    expect(togglePick([], 3)).toEqual([3]);
  });

  it("compares in lap order", () => {
    expect(comparePair([4, 2])).toEqual([2, 4]);
    expect(comparePair([4])).toBeNull();
    expect(compareHref("20261018-191204", [2, 4])).toBe("/sessions/20261018-191204/compare?a=2&b=4");
  });

  it("offers the best lap and the next fastest", () => {
    expect(bestAndNext(LAPS)).toEqual([4, 6]);
    expect(bestAndNext(LAPS.slice(6))).toBeNull();
  });
});
