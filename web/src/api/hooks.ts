// TanStack Query hooks over the generated client: how every component reads data.
// A page that needs a new route adds a hook here, not a fetch of its own.
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { ApiError, client, unwrap, type EngineStatus } from "./client";

export { ApiError } from "./client";
export type { EngineStatus, Health, LapRow, Session, Trace } from "./client";

export const queryKeys = {
  sessions: ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  laps: (id: string) => ["sessions", id, "laps"] as const,
  engineStatus: ["engine", "status"] as const,
  health: ["health"] as const,
  sameTrack: (id: string) => ["sessions", id, "same-track"] as const,
  trace: (id: string, lap: number, points: number) => ["sessions", id, "laps", lap, "trace", points] as const,
};

/** How often the list and the live session are asked again while a session is
 * live (ADR 0004 point 10). Each ask is answered 304 until the index changes. */
export const LIVE_POLL_MS = 5_000;

/** What the session list is filtered by (#297 R5): the page's URL holds these. */
export interface SessionFilters {
  track?: string;
  car?: string;
  kind?: string;
  /** Days, `YYYY-MM-DD`, in the viewer's time zone. */
  from?: string;
  to?: string;
}

/** The browser's time zone, which the list's days are in: the pit wall runs in
 * UTC. Sent by the hook, never put in the page's URL. */
function viewerZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** The sessions that match `filters`, newest first, with the filters' options and
 * counts (`GET /api/v1/sessions`, #318). Asked again every 5 s while `live`, and
 * otherwise only when the tab regains focus; a new filter keeps the old list on
 * screen until its answer is in. */
export function useSessionList(filters: SessionFilters, { live = false }: { live?: boolean } = {}) {
  const query = { ...filters, tz: viewerZone() };
  return useQuery({
    queryKey: [...queryKeys.sessions, "list", query] as const,
    queryFn: async ({ signal }) => unwrap(await client.GET("/api/v1/sessions", { params: { query }, signal })),
    placeholderData: keepPreviousData,
    refetchInterval: live ? LIVE_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

/** Polling for a session's page: every 5 s while it is the engineer's live one and
 * the tab is visible, otherwise not at all (focus still refetches). The pit wall
 * answers 304 to the browser's If-None-Match until the engineer writes, so most
 * asks cost a header. An unknown session is not asked about twice. */
function sessionQuery(live: boolean) {
  return {
    refetchInterval: live ? LIVE_POLL_MS : (false as const),
    refetchIntervalInBackground: false,
    retry: (failures: number, error: Error) => !(error instanceof ApiError && error.status === 404) && failures < 1,
  };
}

/** One session (`GET /api/v1/sessions/{id}`), polled while `live`. */
export function useSession(id: string, { live = false }: { live?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/v1/sessions/{id}", { params: { path: { id } }, signal })),
    ...sessionQuery(live),
  });
}

/** One session while it is live, for the list's pinned card when the list itself
 * doesn't have it (filtered out). Nothing is asked while `id` is null. The same
 * query as useSession's (key, fetch and options), so the list and the session
 * page share one cache entry and agree on how it is polled. */
export function useLiveSession(id: string | null) {
  return useQuery({
    queryKey: queryKeys.session(id ?? ""),
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/v1/sessions/{id}", { params: { path: { id: id ?? "" } }, signal })),
    enabled: id !== null,
    ...sessionQuery(true),
  });
}

/** A session's lap table (`GET /api/v1/sessions/{id}/laps`), polled while `live`. */
export function useLaps(id: string, { live = false }: { live?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.laps(id),
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/v1/sessions/{id}/laps", { params: { path: { id } }, signal })),
    ...sessionQuery(live),
  });
}

/** How often the live chip asks after the engineer while the tab is visible (#296 R2). */
export const ENGINE_POLL_MS = 5_000;
/** How long one ask may take before the engineer counts as offline. The pit wall's
 * proxy answers a 502 within 2 s when the engineer is down (#236 R5), so this only
 * catches a pit wall that is itself slow to answer. */
export const ENGINE_TIMEOUT_MS = 3_000;

/** What the shell knows about the engineer: still asking, not answering (a 502, a
 * timeout, the pit wall out of reach), or its status. */
export type EngineView = { state: "checking" } | { state: "offline" } | { state: "online"; status: EngineStatus };

/** `signal`, also aborted after `ms`. */
function withTimeout(signal: AbortSignal, ms: number): AbortSignal {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  if (signal.aborted) {
    abort();
  } else {
    signal.addEventListener("abort", abort, { once: true });
  }
  const timer = setTimeout(() => controller.abort(new DOMException("timed out", "TimeoutError")), ms);
  controller.signal.addEventListener("abort", () => clearTimeout(timer), { once: true });
  return controller.signal;
}

/** The engineer, right now (`GET /api/engine/status`: #292 through the proxy).
 * Asked every 5 s while the tab is visible, not at all while it is hidden, and
 * again as soon as it is shown. Any failure is "offline", never an error: an
 * engineer that is down never blocks a page (ADR 0004 point 9). */
export function useEngineStatus(): EngineView {
  const query = useQuery({
    queryKey: queryKeys.engineStatus,
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/engine/status", { signal: withTimeout(signal, ENGINE_TIMEOUT_MS) })),
    refetchInterval: ENGINE_POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 0,
    retry: false,
  });
  // The latest answer wins: a failed ask after a good one is offline, though the
  // query keeps the old data.
  if (query.status === "error") {
    return { state: "offline" };
  }
  if (query.status === "pending") {
    return { state: "checking" };
  }
  return { state: "online", status: query.data };
}

/** The pit wall's own health and version (`GET /healthz`). Unhealthy (a 503) has
 * the same body, version and all. */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await client.GET("/healthz", { signal });
      return unwrap({ data: data ?? error, response });
    },
    staleTime: 60_000,
  });
}

/** Other sessions at this one's track, by a sure track id, newest first
 * (`GET /api/v1/sessions/{id}/same-track`, #236 R1b). */
export function useSameTrack(id: string) {
  return useQuery({
    queryKey: queryKeys.sameTrack(id),
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/v1/sessions/{id}/same-track", { params: { path: { id } }, signal })),
  });
}

/** The most points a trace is asked for: about one per device pixel of a phone's chart. */
export const TRACE_MAX_POINTS = 1_500;

/** One lap's channels against time, thinned to `points` (at most TRACE_MAX_POINTS)
 * (`GET /api/v1/sessions/{id}/laps/{lap}/trace`, #236). A lap file that is missing or
 * still being written is a 404, which is not worth retrying. `lap` null asks nothing. */
export function useTrace(id: string, lap: number | null, points: number) {
  const n = Math.max(1, Math.min(TRACE_MAX_POINTS, Math.round(points)));
  return useQuery({
    queryKey: queryKeys.trace(id, lap ?? -1, n),
    queryFn: async ({ signal }) =>
      unwrap(
        await client.GET("/api/v1/sessions/{id}/laps/{lap}/trace", {
          params: { path: { id, lap: lap ?? 0 }, query: { points: n } },
          signal,
        }),
      ),
    enabled: lap !== null && id !== "",
    retry: (count, error) => !isNotFound(error) && count < 1,
    // A closed lap's trace never changes; the ETag makes a repeat a 304 anyway.
    staleTime: 5 * 60_000,
  });
}

/** The API answered 404: no such session or lap, or the lap's file is not there. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}
