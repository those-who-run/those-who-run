// format.ts against the cases it shares with Python (#294 R6, R7):
// tests/fixtures/format-cases.json, which tests/test_format_cases.py checks against
// results.race_time. A change to either side that changes an output fails one of them.
import { describe, expect, it } from "vitest";

import casesJson from "../../../tests/fixtures/format-cases.json?raw";
import * as format from "./format";

interface Case {
  fn: string;
  args: unknown[];
  out: unknown;
  python?: string;
}

const { cases } = JSON.parse(casesJson) as { cases: Case[] };
const formatters = format as unknown as Record<string, (...args: unknown[]) => unknown>;

describe("the shared format cases", () => {
  it.each(cases.map((c) => [`${c.fn}(${c.args.map((a) => JSON.stringify(a)).join(", ")})`, c] as const))(
    "%s",
    (_, c) => {
      const fn = formatters[c.fn];
      expect(fn, `format.ts has no ${c.fn}`).toBeTypeOf("function");
      expect(fn!(...c.args)).toEqual(c.out);
    },
  );

  it("cover every function in format.ts", () => {
    const covered = new Set(cases.map((c) => c.fn));
    expect(Object.keys(format).filter((name) => !covered.has(name))).toEqual([]);
  });

  it("cover what #294 AC4 asks for", () => {
    const outs = cases.map((c) => JSON.stringify(c.out));
    for (const want of ["49.677", "1:36.595", "1:02:03.456", "\u22120.312", "+0.000", "\u2014", "Fuel off"]) {
      expect(outs).toContain(JSON.stringify(want));
    }
    expect(outs).toContain(JSON.stringify({ position: "P1", of: "/1" }));
    expect(cases).toContainEqual(expect.objectContaining({ fn: "fuelPct", args: [0, { fuelUse: false }] }));
  });
});

describe("never null, NaN or undefined on the page", () => {
  const bad = [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY];
  const text = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

  it.each(Object.keys(format))("%s", (name) => {
    for (const v of bad) {
      const out = text(formatters[name]!(v, v, "UTC"));
      expect(out).not.toMatch(/null|NaN|undefined|Infinity|None/);
      expect(out.length).toBeGreaterThan(0);
    }
  });

  it("shows a missing value as the em dash", () => {
    expect(format.missing()).toBe("\u2014");
    expect(format.lapTime(Number.NaN)).toBe("\u2014");
    expect(format.gap(Number.NaN)).toBe("\u2014");
    expect(format.position(Number.NaN, 16)).toEqual({ position: "\u2014", of: "" });
  });
});

describe("a gap", () => {
  it("uses the true minus sign, never a hyphen", () => {
    expect(format.gap(-312)).toBe("\u22120.312");
    expect(format.gap(-312)).not.toContain("-");
  });
});

describe("sessionDate", () => {
  it("defaults to now in the browser's zone", () => {
    const now = Date.now() / 1000;
    expect(format.sessionDate(now - 60)).toMatch(/^(Today|Yesterday) \d\d:\d\d$/);
  });

  it("counts calendar days across the clocks going back", () => {
    // 2026-10-25 is when Britain leaves summer time: a 25-hour day.
    const sunday = Date.UTC(2026, 9, 25, 23, 30) / 1000; // 23:30 GMT on the 25th
    const saturday = Date.UTC(2026, 9, 24, 22, 30) / 1000; // 23:30 BST on the 24th
    expect(format.sessionDate(saturday, sunday, "Europe/London")).toBe("Yesterday 23:30");
  });
});
