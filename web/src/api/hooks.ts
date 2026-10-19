// TanStack Query hooks over the generated client: how every component reads data.
// A page that needs a new route adds a hook here, not a fetch of its own.
import { useQuery } from "@tanstack/react-query";

import { client, unwrap, type EngineStatus } from "./client";

export type { EngineStatus, Health } from "./client";

export const queryKeys = {
  sessions: ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  engineStatus: ["engine", "status"] as const,
  health: ["health"] as const,
};

/** Every session, newest first (`GET /api/v1/sessions`). */
export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: async ({ signal }) => unwrap(await client.GET("/api/v1/sessions", { signal })),
  });
}

/** One session (`GET /api/v1/sessions/{id}`). */
export function useSession(id: string) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: async ({ signal }) =>
      unwrap(await client.GET("/api/v1/sessions/{id}", { params: { path: { id } }, signal })),
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
