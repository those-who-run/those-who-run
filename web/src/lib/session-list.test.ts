import { describe, expect, it } from "vitest";

import { KIT_NOW, KIT_TZ, liveSession, SESSIONS } from "@/kit/samples";

import { groupByDay, liveCardSession, parseView, restartNote, sessions, withParams } from "./session-list";

const HOUR = 3600;
type Session = (typeof SESSIONS)["raceFinished"];

function at(id: string, hoursAgo: number, laps = 3): Session {
  return { ...SESSIONS.timed, session_id: id, started_at: KIT_NOW - hoursAgo * HOUR, laps_completed: laps };
}

describe("parseView", () => {
  it("reads the filters and ?all=1", () => {
    const view = parseView(new URLSearchParams("track=Suzuka&car=GR86&kind=lap_race&from=2026-10-17&to=2026-10-18&all=1"));
    expect(view).toEqual({
      filters: { track: "Suzuka", car: "GR86", kind: "lap_race", from: "2026-10-17", to: "2026-10-18" },
      all: true,
    });
  });

  it("drops what it can't use, without an error", () => {
    expect(parseView(new URLSearchParams("track=&from=2026-02-30&to=yesterday&all=yes"))).toEqual({
      filters: {},
      all: false,
    });
    // A range that ends before it starts loses its end.
    expect(parseView(new URLSearchParams("from=2026-10-18&to=2026-10-17")).filters).toEqual({ from: "2026-10-18" });
  });
});

describe("withParams", () => {
  it("sets and removes, keeping the rest", () => {
    const next = withParams(new URLSearchParams("track=Suzuka&all=1"), { track: null, car: "GR86" });
    expect(next.toString()).toBe("all=1&car=GR86");
  });
});

describe("groupByDay", () => {
  const list = [at("a", 1), at("b", 2, 0), at("c", 26), at("d", 27, 0), at("e", 50)];

  it("groups by the viewer's day, newest first, with each day's full count", () => {
    const { days, more } = groupByDay(list, { all: false, limit: 25, now: KIT_NOW, tz: KIT_TZ });
    expect(days.map((d) => [d.label, d.count, d.sessions.map((s) => s.session_id), d.short])).toEqual([
      ["Today", 2, ["a"], 1],
      ["Yesterday", 2, ["c"], 1],
      ["Fri 16 Oct", 1, ["e"], 0],
    ]);
    expect(more).toBe(false);
  });

  it("shows the short ones with all", () => {
    const { days } = groupByDay(list, { all: true, limit: 25, now: KIT_NOW, tz: KIT_TZ });
    expect(days.flatMap((d) => d.sessions.map((s) => s.session_id))).toEqual(["a", "b", "c", "d", "e"]);
    expect(days.every((d) => d.short === 0)).toBe(true);
  });

  it("pages by cards, keeping the heading's count right", () => {
    const many = Array.from({ length: 30 }, (_, i) => at(`s${i}`, i * 0.1));
    const first = groupByDay(many, { all: false, limit: 25, now: KIT_NOW, tz: KIT_TZ });
    expect(first.shown).toBe(25);
    expect(first.more).toBe(true);
    expect(first.days[0]!.count).toBe(30);
    const second = groupByDay(many, { all: false, limit: 50, now: KIT_NOW, tz: KIT_TZ });
    expect(second.shown).toBe(30);
    expect(second.more).toBe(false);
  });

  it("leaves the live session out", () => {
    const { days } = groupByDay(list, { all: true, limit: 25, liveId: "a", now: KIT_NOW, tz: KIT_TZ });
    expect(days[0]!.sessions.map((s) => s.session_id)).toEqual(["b"]);
    expect(days[0]!.count).toBe(1);
  });

  it("keeps a day of short sessions alone, so its line shows", () => {
    const { days } = groupByDay([at("x", 1, 0)], { all: false, limit: 25, now: KIT_NOW, tz: KIT_TZ });
    expect(days).toHaveLength(1);
    expect(days[0]!.sessions).toEqual([]);
    expect(days[0]!.short).toBe(1);
  });
});

describe("liveCardSession", () => {
  it("takes the lap and position from the engineer", () => {
    const s = liveCardSession(liveSession({ lap: 5, laps_total: 12, position: 2, cars: 16 }), SESSIONS.live, "x", KIT_NOW);
    expect(s.session_id).toBe(SESSIONS.live.session_id);
    expect([s.laps_completed, s.total_laps, s.final_position, s.total_cars, s.position_shown]).toEqual([4, 12, 2, 16, true]);
  });

  it("hides a position the engineer hides", () => {
    const s = liveCardSession(liveSession({ position: null, cars: null }), SESSIONS.live, "x", KIT_NOW);
    expect(s.position_shown).toBe(false);
  });

  it("is built from the status alone when nothing else is known", () => {
    const s = liveCardSession(liveSession({ track: { id: null, name: "Suzuka", sure: false } }), undefined, "lap race", KIT_NOW);
    expect(s.track).toEqual({ id: null, name: "Unknown track", sure: false, evidence: null });
    expect(s.kind_label).toBe("lap race");
    expect(s.started_at).toBe(KIT_NOW);
  });
});

describe("words", () => {
  it("counts sessions", () => {
    expect([sessions(1), sessions(3)]).toEqual(["1 session", "3 sessions"]);
  });

  it("notes a restart", () => {
    expect(restartNote(SESSIONS.timed)).toBeNull();
    expect(restartNote({ ...SESSIONS.timed, continued: true, restart_laps: [] })).toBe("Restarted");
    expect(restartNote({ ...SESSIONS.timed, continued: true, restart_laps: [3] })).toBe("Restarted on lap 3");
    expect(restartNote({ ...SESSIONS.timed, continued: true, restart_laps: [2, 4, 5] })).toBe(
      "Restarted on laps 2, 4 and 5",
    );
  });
});
