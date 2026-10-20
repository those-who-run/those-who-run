// The session list (#297) through the route table, with the API answered here: the
// live card, short sessions, the filters in the URL, and the states.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { engine, liveSession, SESSIONS } from "@/kit/samples";
import { routes } from "@/routes";

const NOW = Date.now() / 1000;
const list = [
  { ...SESSIONS.live, started_at: NOW - 60, closed: false },
  { ...SESSIONS.raceFinished, started_at: NOW - 3600, continued: true, restart_laps: [3] },
  { ...SESSIONS.timed, session_id: "20261018-120000", started_at: NOW - 7200, laps_completed: 0 },
];
const BODY = {
  sessions: list,
  options: {
    track: [{ value: SESSIONS.raceFinished.track.name, count: 1 }],
    car: [],
    kind: [{ value: "lap_race", label: "lap race", count: 2 }],
  },
  total: 3,
  matched: 3,
};

class PageRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
  }
}

/** Answers the list with `body`, and the engineer with `status` (down when null). */
function answer(body: unknown, status: unknown = null, code = 200) {
  vi.stubGlobal("Request", PageRequest);
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL((input as Request).url).pathname;
    if (path === "/api/engine/status") {
      return status
        ? new Response(JSON.stringify(status))
        : new Response(JSON.stringify({ error: "the engineer is not answering" }), { status: 502 });
    }
    if (path === "/healthz") {
      return new Response(JSON.stringify({ ok: true, version: "0.7.1", index: true, engineer: false }));
    }
    return new Response(JSON.stringify(body), { status: code });
  });
}

function renderAt(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const listCalls = (fetch: ReturnType<typeof answer>) =>
  fetch.mock.calls
    .map(([r]) => new URL((r as Request).url))
    .filter((u) => u.pathname === "/api/v1/sessions");

describe("the session list", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("groups by day with the count, and sends the viewer's zone (R1)", async () => {
    const fetch = answer(BODY);
    renderAt("/");
    const today = await screen.findByRole("heading", { level: 3, name: /^Today/ });
    expect(today.textContent).toBe("Today3 sessions");
    const url = listCalls(fetch)[0]!;
    expect(url.searchParams.get("tz")).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("tucks away a session with no full lap, and ?all=1 shows it (R4)", async () => {
    answer(BODY);
    const router = renderAt("/");
    const show = await screen.findByRole("button", { name: "1 session with no full lap Show" });
    expect(screen.queryByRole("link", { name: SESSIONS.timed.track.name })).toBeNull();
    fireEvent.click(show);
    await waitFor(() => expect(router.state.location.search).toBe("?all=1"));
    expect(await screen.findByRole("link", { name: SESSIONS.timed.track.name })).toBeTruthy();
  });

  it("notes a restart (R9)", async () => {
    answer(BODY);
    renderAt("/");
    expect(await screen.findByText("Restarted on lap 3")).toBeTruthy();
  });

  it("pins the live session with the engineer's lap and position (R3)", async () => {
    const status = engine({
      activity: "driving",
      session: liveSession({ id: SESSIONS.live.session_id, lap: 5, laps_total: 12, position: 2, cars: 16 }),
    });
    answer(BODY, status);
    renderAt("/");
    const live = await screen.findByRole("region", { name: "On track" });
    expect(await within(live).findByText("Lap 5 of 12")).toBeTruthy();
    expect(within(live).getByText("Position 2 of 16")).toBeTruthy();
    expect(within(live).getByText("Live")).toBeTruthy();
    // Not in its day as well.
    const days = screen.getByRole("list", { name: "Sessions" });
    expect(days.querySelector(`a[href="/sessions/${SESSIONS.live.session_id}"]`)).toBeNull();
  });

  it("filters through the URL, and shows what is set (R5)", async () => {
    const fetch = answer({ ...BODY, sessions: [list[1]], matched: 1 });
    const track = SESSIONS.raceFinished.track.name;
    const router = renderAt(`/?track=${encodeURIComponent(track)}&kind=lap_race`);
    expect(await screen.findByText("1 of 3 sessions")).toBeTruthy();
    const url = listCalls(fetch)[0]!;
    expect([url.searchParams.get("track"), url.searchParams.get("kind")]).toEqual([track, "lap_race"]);
    const active = screen.getByRole("list", { name: "Active filters" });
    expect(within(active).getByRole("button", { name: "Remove filter: lap race" })).toBeTruthy();
    fireEvent.click(within(active).getByRole("button", { name: `Remove filter: ${track}` }));
    await waitFor(() => expect(router.state.location.search).toBe("?kind=lap_race"));
    fireEvent.click(within(screen.getByRole("list", { name: "Active filters" })).getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("says when nothing matches, with Clear filters (R7)", async () => {
    answer({ ...BODY, sessions: [], matched: 0 });
    const router = renderAt("/?car=Nothing");
    fireEvent.click(await screen.findByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("says how to get a first session (R7)", async () => {
    answer({ ...BODY, sessions: [], total: 0, matched: 0 });
    renderAt("/");
    expect(await screen.findByText("No sessions yet")).toBeTruthy();
    expect(screen.getByText("Drive a lap with the engineer running and it appears here.", { exact: false })).toBeTruthy();
  });

  it("shows the store's error with Retry (R7)", async () => {
    answer({ error: "file is not a database" }, null, 500);
    renderAt("/");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Couldn't read the session store.");
    expect(alert.textContent).toContain("file is not a database");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("shows a page more for each click on Show more, however quick (R6, #379)", async () => {
    const sessions = Array.from({ length: 80 }, (_, i) => ({
      ...SESSIONS.raceFinished,
      session_id: `20261001-${String(100000 + i)}`,
      started_at: NOW - 3600 - 60 * i,
    }));
    answer({ ...BODY, sessions, total: sessions.length, matched: sessions.length });
    const router = renderAt("/");
    const more = await screen.findByRole("button", { name: "Show more" });
    // Both clicks land before the first one's navigation has rendered.
    fireEvent.click(more);
    fireEvent.click(more);
    await waitFor(() =>
      expect(within(screen.getByRole("list", { name: "Sessions" })).getAllByRole("link")).toHaveLength(75),
    );
    expect(router.state.location.state).toMatchObject({ shown: 75 });
  });
});
