// Lap compare's plain parts (#299 R1, R4, R6, R9): which laps the URL picks, the
// two laps on one x axis, the readout's samples, the remembered channels and the
// cursor store.
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LapRow, Trace } from "@/api/hooks";

import { align, nearestIndex, sampleAt } from "./align";
import { createCursorStore } from "./cursor";
import { defaultLaps, formatZoom, parseZoom, resolvePicks } from "./picks";
import { HIDDEN_CHANNELS_KEY, readHiddenChannels, takeSidewaysHint, writeHiddenChannels } from "./prefs";

function lap(n: number, time_ms: number | null, extra: Partial<LapRow> = {}): LapRow {
  return {
    lap: n,
    time_ms,
    complete: time_ms !== null,
    fuel_start: null,
    fuel_end: null,
    fuel_used: null,
    position: null,
    frames: 100,
    file: `lap-0${n}.parquet`,
    top_speed_kph: null,
    pit: false,
    out_lap: false,
    invalid: time_ms === null,
    best: false,
    fuel_use: true,
    restart: false,
    clean: time_ms !== null,
    ...extra,
  };
}

// The Suzuka pit stop: lap 5 is the best, lap 6 the next fastest after lap 1.
const PIT_STOP = [
  lap(1, 57109),
  lap(2, 60538),
  lap(3, 82544, { pit: true }),
  lap(4, 69892, { out_lap: true }),
  lap(5, 59541, { best: true }),
  lap(6, 60310),
];
const none = { a: null, b: null, bSession: null };

describe("which laps compare shows", () => {
  it("defaults to the card's best lap against the next fastest", () => {
    expect(defaultLaps(PIT_STOP)).toEqual({ a: 5, b: 1, alone: false });
  });

  it("makes B the same as A when there is no other timed lap", () => {
    expect(defaultLaps([lap(7, 150511, { best: true }), lap(8, null)])).toEqual({ a: 7, b: 7, alone: true });
    expect(resolvePicks("s", none, [lap(1, 1000, { best: true })], undefined, []).alone).toBe(true);
  });

  it("takes ?a and ?b when they are laps of the session", () => {
    expect(resolvePicks("s", { a: "2", b: "6", bSession: null }, PIT_STOP, undefined, [])).toMatchObject({
      a: 2,
      b: 6,
      bSession: "s",
      notices: [],
    });
  });

  it("falls back to the defaults for a bad ?a or ?b, and says so", () => {
    const p = resolvePicks("s", { a: "99", b: "x", bSession: null }, PIT_STOP, undefined, []);
    expect(p).toMatchObject({ a: 5, b: 1 });
    expect(p.notices).toEqual([
      "There's no lap 99 in this session, so lap A is the best lap.",
      "There's no lap x in this session, so lap B is the next fastest.",
    ]);
  });

  it("takes lap B from a same-track session, its best lap by default", () => {
    const other = [lap(1, 60358), lap(4, 61186, { best: true })];
    expect(resolvePicks("s", { a: null, b: null, bSession: "t" }, PIT_STOP, other, ["t"])).toMatchObject({
      b: 4,
      bSession: "t",
      notices: [],
    });
    // Its laps still loading: no lap B yet.
    expect(resolvePicks("s", { a: null, b: "1", bSession: "t" }, PIT_STOP, undefined, undefined).b).toBeNull();
  });

  it("refuses a b_session that isn't at this track", () => {
    const p = resolvePicks("s", { a: null, b: null, bSession: "elsewhere" }, PIT_STOP, [], ["t"]);
    expect(p).toMatchObject({ bSession: "s", b: 1 });
    expect(p.notices).toEqual(["That session isn't one at this track, so lap B is from this session."]);
  });

  it("reads and writes ?zoom", () => {
    expect(parseZoom("12.30-45.60")).toEqual([12.3, 45.6]);
    expect(parseZoom("45-12")).toBeNull();
    expect(parseZoom("nonsense")).toBeNull();
    expect(formatZoom([12.3, 45.678])).toBe("12.30-45.68");
  });
});

function trace(t: number[], speed: number[]): Trace {
  return {
    session_id: "s",
    lap: 1,
    t,
    speed_kph: speed,
    throttle_pct: speed.map(() => 0),
    brake_pct: speed.map(() => 0),
    gear: speed.map(() => 3),
    rpm: speed.map(() => 6000),
    x: speed.map(() => 0),
    z: speed.map(() => 0),
  };
}

describe("two laps on one x axis", () => {
  it("merges the xs, each lap null where it has no sample", () => {
    const a = trace([0, 1, 2], [10, 11, 12]);
    const b = trace([0, 1.5, 2], [20, 21, 22]);
    const { xs, series } = align(a, b);
    expect(xs).toEqual([0, 1, 1.5, 2]);
    expect(series.speed).toEqual([
      [10, 11, null, 12],
      [20, null, 21, 22],
    ]);
  });

  it("draws one lap alone when the other is missing", () => {
    const { xs, series } = align(trace([0, 1], [10, 11]), null);
    expect(xs).toEqual([0, 1]);
    expect(series.rpm[1]).toEqual([null, null]);
  });

  it("reads each lap at its own nearest sample, and nothing past its ends", () => {
    expect(nearestIndex([0, 1, 2, 3], 1.4)).toBe(1);
    expect(nearestIndex([0, 1, 2, 3], 1.6)).toBe(2);
    expect(nearestIndex([], 1)).toBeNull();
    const a = trace([0, 1, 2], [10, 11, 12]);
    expect(sampleAt(a, 1.2)).toEqual({ x: 1, index: 1 });
    expect(sampleAt(a, 9)).toBeNull();
    expect(sampleAt(null, 1)).toBeNull();
  });
});

describe("the remembered channels", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips the hidden channels, ignoring anything unknown", () => {
    writeHiddenChannels(["rpm"]);
    expect(readHiddenChannels()).toEqual(["rpm"]);
    localStorage.setItem(HIDDEN_CHANNELS_KEY, JSON.stringify(["gear", "boost"]));
    expect(readHiddenChannels()).toEqual(["gear"]);
  });

  it("carries on when storage is broken or blocked", () => {
    localStorage.setItem(HIDDEN_CHANNELS_KEY, "{not json");
    expect(readHiddenChannels()).toEqual([]);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readHiddenChannels()).toEqual([]);
    expect(() => writeHiddenChannels(["rpm"])).not.toThrow();
  });

  it("gives the sideways hint once", () => {
    expect(takeSidewaysHint()).toBe(true);
    expect(takeSidewaysHint()).toBe(false);
  });
});

describe("the cursor store", () => {
  it("tells its listeners at most once a frame, with the latest x", () => {
    const frames: (() => void)[] = [];
    const store = createCursorStore((cb) => frames.push(cb));
    const heard = vi.fn();
    store.subscribe(heard);
    store.set(1);
    store.set(2);
    store.set(3);
    expect(frames).toHaveLength(1);
    expect(store.get()).toBeNull();
    frames[0]!();
    expect(store.get()).toBe(3);
    expect(heard).toHaveBeenCalledTimes(1);
  });
});
