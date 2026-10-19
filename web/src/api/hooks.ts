// TanStack Query hooks over the generated client: how every component reads data.
// A page that needs a new route adds a hook here, not a fetch of its own.
import { useQuery } from "@tanstack/react-query";

import { client, unwrap } from "./client";

export const queryKeys = {
  sessions: ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
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
