// The session page through the generated client, in each state (#298 R1 to R9),
// with the kit's samples as the API's answers.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { LapRow, Session } from "@/api/hooks";
import { engine, LAPS, liveSession, SESSIONS } from "@/kit/samples";
import type { RaceStory as RaceStoryChart } from "@/session/race-story";

import { Component } from "./session";

// The race story's chart needs a canvas, which jsdom lacks: a stand-in with a
// button per point, so the page's side of it (when it shows, the picks and the
// highlight) is tested here, and the chart itself in e2e/session.spec.ts.
vi.mock("@/session/race-story", () => ({
  RaceStory: ({ story, picks, highlight, onHighlight, onPick }: Parameters<typeof RaceStoryChart>[0]) => (
    <div
      role="img"
      aria-label={story.summary}
      data-slot="race-story"
      data-highlight={highlight ?? ""}
      data-picks={picks.join(",")}
    >
      {story.points.map((p) => (
        <button key={p.lap} type="button" onClick={() => onPick(p.lap)} onMouseEnter={() => onHighlight(p.lap)}>
          Point {p.lap}
        </button>
      ))}
    </div>
  ),
}));

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// Node's Request, which jsdom keeps, wants an absolute URL; a browser resolves the
// client's same-origin paths against the page. The client takes Request when it is
// made, at import, so this goes in before any import.
vi.hoisted(() => {
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, globalThis.location.href) : input, init);
    }
  };
});

interface Api {
  session?: Session | { status: number; error: string };
  laps?: LapRow[] | { status: number; error: string };
  engine?: ReturnType<typeof engine> | null;
}

/** Answers the API from `api`, which a test may change between asks. */
function serve(api: Api) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL((input as Request).url).pathname;
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    const answer = (v: unknown) => {
      const failure = v as { status?: number; error?: string } | undefined;
      return failure?.status ? json({ error: failure.error }, failure.status) : json(v);
    };
    if (path === "/api/engine/status") {
      return api.engine ? json(api.engine) : json({ error: "down" }, 502);
    }
    if (path.endsWith("/laps")) {
      const laps = api.laps ?? [];
      return Array.isArray(laps) ? json({ session_id: "x", laps }) : answer(laps);
    }
    return answer(api.session);
  });
}

function renderAt(url: string) {
  const router = createMemoryRouter(
    [
      { path: "/sessions/:id", Component },
      { path: "/sessions/:id/compare", element: <p>compare</p> },
      { path: "/", element: <p>list</p> },
    ],
    { initialEntries: [url] },
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const lapAsks = (fetch: ReturnType<typeof serve>) =>
  fetch.mock.calls.filter(([r]) => new URL((r as Request).url).pathname.endsWith("/laps")).length;

describe("the session page", () => {
  it("leads with the result, then the tiles and the laps (R1, R2, R3)", async () => {
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    expect(await screen.findByRole("heading", { level: 2, name: SESSIONS.raceFinished.track.name })).toBeTruthy();
    const hero = document.querySelector("[data-slot=headline]")!;
    expect(hero.textContent).toContain("Position 1 of 16");
    expect(hero.textContent).toContain("Finished in 9:56.826");
    expect(document.title).toBe(`${SESSIONS.raceFinished.title} · Pit wall`);

    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary.textContent).toContain("Best lap1:37.764lap 4");
    expect(summary.textContent).toContain("of 3 clean laps");
    expect(summary.textContent).toContain("Laps6of 6");
    expect(summary.textContent).toContain("Pit stops0");

    const table = screen.getByRole("table");
    expect(table.querySelector("caption")!.textContent).toContain("Laps");
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Pick to compare",
      "Lap",
      "Time",
      "Gap",
      "Pos",
      "Fuel used",
      "Fuel left",
      "Top km/h",
    ]);
    const best = table.querySelector('tr[data-lap="4"]')!;
    expect(best.getAttribute("data-best")).toBe("true");
    expect(best.textContent).toContain("Best");
    expect(table.querySelector('tr[data-lap="7"]')!.className).toContain("text-muted");
    expect(within(table).getByRole("button", { name: "Pit" })).toBeTruthy();
  });

  it("shows GT7's own fuel units when the tank's size is unknown", async () => {
    serve({ session: { ...SESSIONS.raceFinished, fuel_capacity: null, fuel_used: 19.6 }, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    const summary = await screen.findByRole("region", { name: "Summary" });
    await vi.waitFor(() => expect(summary.textContent).toContain("Fuel used19.6 units3.2 units per lap"));
    expect(screen.getByRole("columnheader", { name: "Fuel used (units)" })).toBeTruthy();
  });

  it("says Fuel off and leaves out the fuel columns when fuel use is off", async () => {
    serve({ session: { ...SESSIONS.raceFinished, fuel_use: false }, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    await screen.findByRole("table");
    expect(screen.getByRole("region", { name: "Summary" }).textContent).toContain("Fuel usedFuel off");
    expect(screen.queryByRole("columnheader", { name: "Fuel used" })).toBeNull();
  });

  it("opens a lap's fuel and top speed on a tap (R4)", async () => {
    const user = userEvent.setup();
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    const button = await screen.findByRole("button", { name: "Lap 2: fuel and top speed" });
    await user.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const detail = document.getElementById(button.getAttribute("aria-controls")!)!;
    expect(detail.textContent).toContain("Top speed246 km/h");
    expect(detail.querySelector("td")!.getAttribute("colspan")).toBe("5");
    await user.click(document.querySelector('tr[data-lap="2"] td:nth-child(3)')!);
    expect(document.getElementById("lap-2-detail")).toBeNull();
  });

  it("picks two laps for compare, a third replacing the oldest (R5)", async () => {
    const user = userEvent.setup();
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    const router = renderAt("/sessions/20261018-191204");
    const bar = await screen.findByRole("region", { name: "Compare" });
    expect(within(bar).getByRole("link").getAttribute("href")).toBe("/sessions/20261018-191204/compare?a=4&b=6");
    await user.click(screen.getByRole("checkbox", { name: "Pick lap 2 to compare" }));
    await user.click(screen.getByRole("checkbox", { name: "Pick lap 4 to compare" }));
    expect(within(bar).getByRole("link", { name: "Compare L2 and L4" }).getAttribute("href")).toBe(
      "/sessions/20261018-191204/compare?a=2&b=4",
    );
    expect(router.state.location.search).toBe("?pick=2%2C4");
    await user.click(screen.getByRole("checkbox", { name: "Pick lap 5 to compare" }));
    expect((screen.getByRole("checkbox", { name: "Pick lap 2 to compare" }) as HTMLInputElement).checked).toBe(false);
    expect(within(bar).getByRole("link", { name: "Compare L4 and L5" })).toBeTruthy();
  });

  it("starts from the picks in the URL", async () => {
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204?pick=4,2");
    expect(await screen.findByRole("link", { name: "Compare L2 and L4" })).toBeTruthy();
    expect(document.querySelector('tr[data-lap="2"]')!.getAttribute("data-state")).toBe("selected");
  });

  it("notes a session the engineer joined part way (R8)", async () => {
    serve({ session: { ...SESSIONS.timed, joined_on_lap: 5 }, laps: LAPS });
    renderAt("/sessions/x");
    expect((await screen.findByText(/The engineer joined on lap 5/)).textContent).toBe(
      "The engineer joined on lap 5. Laps before it weren't seen.",
    );
  });

  it("names an unknown track, with the detector's reason on tap", async () => {
    serve({ session: SESSIONS.unknownTrack, laps: [] });
    renderAt("/sessions/x");
    expect(await screen.findByRole("button", { name: "Unknown track" })).toBeTruthy();
  });
});

describe("its states (R7)", () => {
  it("loads as skeletons of the hero, the tiles and the rows", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    renderAt("/sessions/x");
    expect(screen.getByRole("status", { name: "Loading session" })).toBeTruthy();
    expect(screen.getByRole("status", { name: "Loading best lap" })).toBeTruthy();
    expect(screen.getByRole("status", { name: "Loading the lap table" })).toBeTruthy();
  });

  it("says when there is no such session", async () => {
    serve({ session: { status: 404, error: "no such session" } });
    renderAt("/sessions/nope");
    expect(await screen.findByRole("heading", { level: 2, name: "No session nope." })).toBeTruthy();
    expect(screen.getByRole("link", { name: "All sessions" }).getAttribute("href")).toBe("/");
    expect(document.title).toBe("Session not found · Pit wall");
  });

  it("says when the session has no laps", async () => {
    serve({ session: SESSIONS.raceFinished, laps: [] });
    renderAt("/sessions/x");
    expect(await screen.findByRole("heading", { name: "No laps stored for this session." })).toBeTruthy();
  });

  it("shows the error state when the store can't be read, with Retry", async () => {
    serve({ session: { status: 503, error: "the index is busy, try again" } });
    renderAt("/sessions/x");
    // One retry first, a second later (hooks.ts).
    const alert = await screen.findByRole("alert", {}, { timeout: 3_000 });
    expect(alert.textContent).toContain("Couldn't read the session store.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("live (R6)", () => {
  const open: Session = { ...SESSIONS.raceFinished, closed: false, finished: false, session_id: "live-1" };

  it("asks every 5 s while the engineer's session is this one, and stops when it isn't", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api: Api = {
      session: open,
      laps: LAPS.slice(0, 3),
      engine: engine({ activity: "driving", session: liveSession({ id: "live-1", lap: 4 }) }),
    };
    const fetch = serve(api);
    renderAt("/sessions/live-1");
    expect(await screen.findByText("Lap 4 in progress")).toBeTruthy();
    expect(document.querySelector("[data-slot=live-badge]")!.textContent).toBe("Live");

    api.laps = LAPS.slice(0, 4);
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(await screen.findByText("Lap 5 in progress")).toBeTruthy();
    expect(document.querySelector('tr[data-lap="4"]')).toBeTruthy();

    api.engine = engine();
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    await vi.waitFor(() => expect(document.querySelector("[data-slot=live-badge]")).toBeNull());
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    const asked = lapAsks(fetch);
    await act(() => vi.advanceTimersByTimeAsync(15_000));
    expect(lapAsks(fetch)).toBe(asked);
  });

  it("isn't live for another session", async () => {
    serve({
      session: open,
      laps: LAPS,
      engine: engine({ activity: "driving", session: liveSession({ id: "other" }) }),
    });
    renderAt("/sessions/live-1");
    await screen.findByRole("table");
    expect(document.querySelector("[data-slot=live-badge]")).toBeNull();
    expect(document.querySelector("tr[data-in-progress]")).toBeNull();
  });
});

describe("the race story (#300)", () => {
  const SUMMARY = "6 laps, best 1:37.764 on lap 4, pit on lap 3, out lap 5, P5 to P1";

  it("sits between the tiles and the table, named by its summary (R1, R5)", async () => {
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    const chart = await screen.findByRole("img", { name: SUMMARY });
    const summary = screen.getByRole("region", { name: "Summary" });
    const table = screen.getByRole("table");
    expect(summary.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(chart.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // One point per complete lap: lap 7 is partial.
    expect(within(chart).getAllByRole("button").map((b) => b.textContent)).toEqual(
      [1, 2, 3, 4, 5, 6].map((n) => `Point ${n}`),
    );
  });

  it("isn't there with two complete laps: no chart, no box (R1)", async () => {
    serve({ session: SESSIONS.raceFinished, laps: [...LAPS.slice(0, 2), LAPS[6]!] });
    renderAt("/sessions/20261018-191204");
    await screen.findByRole("table");
    expect(document.querySelector("[data-slot=race-story]")).toBeNull();
    expect(screen.queryByText("Race story")).toBeNull();
  });

  it("picks a lap on a tap, as its checkbox does (R4)", async () => {
    const user = userEvent.setup();
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    const router = renderAt("/sessions/20261018-191204");
    const chart = await screen.findByRole("img", { name: SUMMARY });
    await user.click(within(chart).getByRole("button", { name: "Point 2" }));
    expect((screen.getByRole("checkbox", { name: "Pick lap 2 to compare" }) as HTMLInputElement).checked).toBe(true);
    await user.click(within(chart).getByRole("button", { name: "Point 4" }));
    await user.click(within(chart).getByRole("button", { name: "Point 5" }));
    // A third pick replaces the oldest.
    await vi.waitFor(() => expect(router.state.location.search).toBe("?pick=4%2C5"));
    expect(chart.dataset.picks).toBe("4,5");
    expect((screen.getByRole("checkbox", { name: "Pick lap 2 to compare" }) as HTMLInputElement).checked).toBe(false);
    // And a tap on a picked lap unpicks it.
    await user.click(within(chart).getByRole("button", { name: "Point 5" }));
    expect(chart.dataset.picks).toBe("4");
  });

  it("highlights a lap's row from its point, and its point from the row (R4)", async () => {
    const user = userEvent.setup();
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    const chart = await screen.findByRole("img", { name: SUMMARY });
    const row = (n: number) => document.querySelector(`tbody tr[data-lap="${n}"]`)!;

    await user.hover(within(chart).getByRole("button", { name: "Point 3" }));
    expect(row(3).hasAttribute("data-highlighted")).toBe(true);
    expect(row(2).hasAttribute("data-highlighted")).toBe(false);

    await user.hover(row(2));
    expect(chart.dataset.highlight).toBe("2");
    expect(row(3).hasAttribute("data-highlighted")).toBe(false);
    await user.unhover(row(2));
    expect(chart.dataset.highlight).toBe("");
  });

  it("gains a point as a live lap lands (R6)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const open: Session = { ...SESSIONS.raceFinished, closed: false, finished: false, session_id: "live-1" };
    const api: Api = {
      session: open,
      laps: LAPS.slice(0, 2),
      engine: engine({ activity: "driving", session: liveSession({ id: "live-1", lap: 3 }) }),
    };
    serve(api);
    renderAt("/sessions/live-1");
    expect(await screen.findByText("Lap 3 in progress")).toBeTruthy();
    expect(document.querySelector("[data-slot=race-story]")).toBeNull();

    api.laps = LAPS.slice(0, 3);
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    const chart = await screen.findByRole("img", { name: "3 laps, best 1:38.630 on lap 2, pit on lap 3, P5 to P3" });
    expect(within(chart).getAllByRole("button")).toHaveLength(3);

    api.laps = LAPS.slice(0, 4);
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    await vi.waitFor(() => expect(within(chart).getAllByRole("button")).toHaveLength(4));
  });
});

describe("Copy link (R9)", () => {
  it("copies the session's address, without the picks", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204?pick=2,4");
    await user.click(await screen.findByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/sessions/20261018-191204`);
    expect(await screen.findByText("Link copied.")).toBeTruthy();
  });

  it("shows the address to copy by hand where there is no clipboard", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    serve({ session: SESSIONS.raceFinished, laps: LAPS });
    renderAt("/sessions/20261018-191204");
    await user.click(await screen.findByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("button", { name: "Copy link" }));
    expect((screen.getByRole("textbox", { name: "The session's link" }) as HTMLInputElement).value).toBe(
      `${window.location.origin}/sessions/20261018-191204`,
    );
  });
});
