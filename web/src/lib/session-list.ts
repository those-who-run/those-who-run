// The session list's logic (#297), apart from its markup so it is tested as plain
// values: the URL's filters, the days, paging, and the live card's session.
import type { EngineStatus, SessionFilters } from "@/api/hooks";
import type { components } from "@/api/schema";
import { isoDay, sessionDay } from "@/lib/format";

type Session = components["schemas"]["Session"];
type LiveSession = NonNullable<EngineStatus["session"]>;

/** Cards per page: "Show more" adds as many again (R6). */
export const PAGE_SIZE = 25;

/** The URL parameters the list reads (R5, R4). */
export const FILTER_KEYS = ["track", "car", "kind", "from", "to"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export const SHOW_SHORT = "all";

export interface ListView {
  filters: SessionFilters;
  /** Sessions with no full lap are shown (`?all=1`). */
  all: boolean;
}

/** A real calendar day, `YYYY-MM-DD`. */
export function isDay(text: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return false;
  }
  const [y, m, d] = text.split("-").map(Number) as [number, number, number];
  const at = new Date(Date.UTC(y, m - 1, d));
  return at.getUTCFullYear() === y && at.getUTCMonth() === m - 1 && at.getUTCDate() === d;
}

/** The list's view from the page's URL. Anything it can't use is dropped, never an
 * error: an empty value, a date that isn't one, a range that ends before it starts
 * (its end is dropped). */
export function parseView(params: URLSearchParams): ListView {
  const filters: SessionFilters = {};
  for (const key of ["track", "car", "kind"] as const) {
    const value = params.get(key)?.trim();
    if (value) {
      filters[key] = value;
    }
  }
  for (const key of ["from", "to"] as const) {
    const value = params.get(key)?.trim() ?? "";
    if (isDay(value)) {
      filters[key] = value;
    }
  }
  if (filters.from && filters.to && filters.to < filters.from) {
    delete filters.to;
  }
  return { filters, all: params.get(SHOW_SHORT) === "1" };
}

/** `params` with `changes` made: a value sets its parameter, null removes it. Any
 * other parameter is kept. */
export function withParams(params: URLSearchParams, changes: Partial<Record<FilterKey | "all", string | null>>) {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(changes)) {
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
  }
  return next;
}

/** A session with no full lap: tucked away unless asked for (R4). */
export function isShort(s: Session): boolean {
  return s.laps_completed < 1;
}

export interface Day {
  /** `YYYY-MM-DD` in the viewer's zone. */
  key: string;
  /** "Today", "Yesterday", "Sat 17 Oct". */
  label: string;
  /** Every session that day, short ones included: the heading's count. */
  count: number;
  /** The cards shown on this page. */
  sessions: Session[];
  /** Sessions with no full lap left out (0 when they are shown). */
  short: number;
}

/** The sessions, newest first, grouped under their days in `tz`, with the first
 * `limit` cards shown. The live session is left out: it is pinned above (R3). A day
 * keeps its full count however many of its cards are on the page (R6), and a day of
 * short sessions alone still shows, so its "no full lap" line can. `more` is
 * whether cards are left for "Show more". */
export function groupByDay(
  sessions: Session[],
  {
    all,
    limit,
    liveId = null,
    now,
    tz,
  }: { all: boolean; limit: number; liveId?: string | null; now?: number; tz?: string },
): { days: Day[]; shown: number; more: boolean } {
  const listed = sessions.filter((s) => s.session_id !== liveId);
  const card = (s: Session) => all || !isShort(s);
  const days: Day[] = [];
  let shown = 0;
  let more = false;
  for (const [i, s] of listed.entries()) {
    const key = isoDay(s.started_at, tz);
    let day = days.at(-1);
    if (!day || day.key !== key) {
      if (shown >= limit && listed.slice(i).some(card)) {
        // The page is full and cards are left: the next day starts the next page.
        more = true;
        break;
      }
      day = { key, label: sessionDay(s.started_at, now, tz), count: 0, sessions: [], short: 0 };
      days.push(day);
    }
    day.count += 1;
    if (!all && isShort(s)) {
      day.short += 1;
    } else if (shown < limit) {
      day.sessions.push(s);
      shown += 1;
    } else {
      more = true;
    }
  }
  return { days, shown, more };
}

/** The live card's session: the list's (or the session route's) values with the
 * engineer's lap and position, which are newer. With neither, it is built from the
 * engineer's status alone, as far as that goes. */
export function liveCardSession(
  live: LiveSession,
  known: Session | undefined,
  kindLabel: string | undefined,
  now: number,
): Session {
  const base: Session = known ?? {
    session_id: live.id,
    title: "",
    result: "",
    started_at: now,
    ended_at: null,
    closed: false,
    kind: live.kind,
    kind_label: kindLabel ?? "session",
    track: {
      id: live.track?.id ?? null,
      name: (live.track?.sure && live.track.name) || "Unknown track",
      sure: !!(live.track?.sure && live.track.name),
      evidence: null,
    },
    car: live.car,
    car_code: null,
    finished: false,
    final_position: null,
    total_cars: null,
    position_shown: false,
    total_time_ms: null,
    best_lap_ms: null,
    best_lap_no: null,
    laps_completed: 0,
    total_laps: 0,
    fuel_use: null,
    fuel_used: null,
    fuel_capacity: null,
    fuel_by_stint: [],
    pit_stops: 0,
    driving_ms: null,
    paused_ms: null,
    joined_on_lap: null,
    continued: false,
    restart_laps: [],
  };
  return {
    ...base,
    // The card shows the lap being driven: one more than those completed. GT7 says
    // lap 0 on the grid.
    laps_completed: live.lap ? Math.max(live.lap - 1, 0) : base.laps_completed,
    total_laps: live.laps_total ?? base.total_laps,
    final_position: live.position,
    total_cars: live.cars,
    position_shown: live.position != null,
  };
}

/** "1 session", "3 sessions". */
export function sessions(n: number): string {
  return `${n} ${n === 1 ? "session" : "sessions"}`;
}

/** "Restarted on lap 3", "Restarted on laps 2 and 5", or "Restarted". */
export function restartNote(s: Session): string | null {
  if (!s.continued) {
    return null;
  }
  const laps = s.restart_laps;
  if (laps.length === 0) {
    return "Restarted";
  }
  if (laps.length === 1) {
    return `Restarted on lap ${laps[0]}`;
  }
  return `Restarted on laps ${laps.slice(0, -1).join(", ")} and ${laps.at(-1)}`;
}
