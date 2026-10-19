// The live engineer chip (#296 R2, R3, R9): its words in every engineer state, the
// popover, the deploy notice, and the polling: every 5 s while visible, none while
// hidden, and any failure read as "Engineer offline".
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Node's Request wants an absolute URL; a browser resolves the client's paths
// against the page, and so does this. The client takes Request when it is made,
// as this file's imports load, so it is replaced before them.
vi.hoisted(() => {
  class PageRequest extends Request {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
    }
  }
  globalThis.Request = PageRequest;
});

import type { EngineView } from "@/api/hooks";
import { engine, KIT_VERSION, liveSession, NAMES } from "@/kit/samples";

import { chipLine, chipText, versionsDiffer } from "./engine";
import { EngineChip } from "./engine-chip";
import { LiveChip } from "./live-chip";

const online = (over: Parameters<typeof engine>[0] = {}): EngineView => ({ state: "online", status: engine(over) });

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  focusManager.setFocused(undefined);
});

describe("the chip's words (R2)", () => {
  const cases: [string, EngineView, string][] = [
    [
      "driving on a track the detector is sure of",
      online({ activity: "driving", session: liveSession({ track: { id: 2, name: "Suzuka", sure: true }, lap: 3 }) }),
      "Live · Suzuka · L3",
    ],
    [
      "driving on a track it isn't sure of",
      online({
        activity: "driving",
        session: liveSession({ track: { id: null, name: "Suzuka", sure: false }, lap: 3 }),
      }),
      "Live · Unknown track · L3",
    ],
    [
      "driving with no track yet",
      online({ activity: "driving", session: liveSession({ track: null, lap: 1 }) }),
      "Live · Unknown track · L1",
    ],
    [
      "driving on the grid (lap 0)",
      online({ activity: "driving", session: liveSession({ lap: 0 }) }),
      `Live · ${NAMES.willow}`,
    ],
    ["driving with no session open", online({ activity: "driving" }), "Live"],
    ["paused", online({ activity: "paused", session: liveSession() }), `Paused · ${NAMES.willow}`],
    ["paused with no session", online({ activity: "paused" }), "Paused"],
    ["replay", online({ activity: "replay" }), "Replay"],
    ["demo", online({ activity: "demo" }), "Demo"],
    ["idle", online(), "Idle"],
    ["idle in the menus", online({ telemetry: { connected: true, last_packet_age_s: 0.2 } }), "In the menus"],
    ["offline", { state: "offline" }, "Engineer offline"],
  ];

  it.each(cases)("%s", (_, view, line) => {
    expect(chipLine(chipText(view))).toBe(line);
  });

  it("is muted offline, and the unknown track is muted, never an error colour", () => {
    render(<EngineChip engine={{ state: "offline" }} pitwall={KIT_VERSION} />);
    const chip = screen.getByRole("button", { name: "Engineer offline" });
    expect(chip.dataset.tone).toBe("muted");
    expect(screen.getByText("Engineer offline").closest(".text-muted")).not.toBeNull();
    expect(chip.innerHTML).not.toMatch(/accent/);
    cleanup();

    render(<EngineChip engine={cases[1]![1]} pitwall={KIT_VERSION} />);
    expect(screen.getByText("Unknown track").className).toContain("text-muted");
  });

  it("has the pulsing red dot while live, a still hollow one when paused", () => {
    render(<EngineChip engine={cases[0]![1]} pitwall={KIT_VERSION} />);
    const live = screen.getByRole("button", { name: "Live · Suzuka · L3" });
    expect(live.querySelector(".bg-accent")?.getAttribute("class")).toContain("motion-safe:animate-pulse");
    cleanup();
    render(<EngineChip engine={cases[5]![1]} pitwall={KIT_VERSION} />);
    const paused = screen.getByRole("button", { name: `Paused · ${NAMES.willow}` });
    expect(paused.querySelector(".bg-accent")).toBeNull();
    expect(paused.querySelector(".border-muted")).not.toBeNull();
  });
});

function inRouter(ui: ReactNode) {
  const router = createMemoryRouter([{ path: "*", element: ui }], { initialEntries: ["/sessions"] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("the popover (R2, R3, R9)", () => {
  it("shows the version, telemetry, voice, the live session and the pit wall", async () => {
    const view = online({
      activity: "driving",
      voice_connected: false,
      telemetry: { connected: true, last_packet_age_s: 0.1 },
      session: liveSession(),
    });
    const router = inRouter(<EngineChip engine={view} pitwall={KIT_VERSION} />);
    await userEvent.click(screen.getByRole("button", { name: /^Live/ }));
    const panel = await screen.findByRole("dialog", { name: "The engineer" });
    expect(panel.textContent).toContain("Driving");
    expect(panel.textContent).toContain(`Engineer${KIT_VERSION}`);
    expect(panel.textContent).toContain("TelemetryConnected");
    expect(panel.textContent).toContain("VoiceNot in the voice channel");
    expect(panel.textContent).toContain(`Pit wall ${KIT_VERSION} · Read-only`);
    expect(panel.textContent).not.toContain("deploy");

    await userEvent.click(screen.getByRole("link", { name: "Open the live session" }));
    expect(router.state.location.pathname).toBe("/sessions/20261018-201500");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says the engineer is offline, and that the sessions still work", async () => {
    inRouter(<EngineChip engine={{ state: "offline" }} pitwall={KIT_VERSION} />);
    await userEvent.click(screen.getByRole("button", { name: "Engineer offline" }));
    const panel = await screen.findByRole("dialog", { name: "The engineer" });
    expect(panel.textContent).toContain("The sessions still work");
    expect(panel.textContent).toContain(`Pit wall ${KIT_VERSION} · Read-only`);
    expect(screen.queryByRole("link", { name: "Open the live session" })).toBeNull();
  });

  it("says a deploy is rolling out when the versions differ, with a marker on the chip", async () => {
    const view = online({ version: "0.7.0" });
    expect(versionsDiffer(view, "0.7.1")).toBe(true);
    expect(versionsDiffer(view, "0.7.0")).toBe(false);
    expect(versionsDiffer(view, null)).toBe(false);
    expect(versionsDiffer({ state: "offline" }, "0.7.1")).toBe(false);

    inRouter(<EngineChip engine={view} pitwall="0.7.1" />);
    const chip = screen.getByRole("button", { name: "Idle, a deploy is rolling out" });
    expect(chip.querySelector("[data-slot=deploy-marker]")?.getAttribute("class")).toContain("bg-info");
    await userEvent.click(chip);
    expect((await screen.findByRole("dialog")).textContent).toContain(
      "Engineer 0.7.0, pit wall 0.7.1: a deploy is rolling out",
    );
  });

  it("opens from the keyboard and closes on Escape", async () => {
    inRouter(<EngineChip engine={online()} pitwall={KIT_VERSION} />);
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Idle" }));
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "The engineer" })).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

/** The engineer answers each status call with the next of `answers`; the last repeats. */
function engineer(answers: (() => Response)[]) {
  let n = 0;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL((input as Request).url).pathname;
    if (path === "/healthz") {
      return Response.json({ ok: true, version: KIT_VERSION, index: true, engineer: true });
    }
    const answer = answers[Math.min(n, answers.length - 1)]!;
    n += 1;
    return answer();
  });
}

const statusCalls = (fetch: ReturnType<typeof engineer>) =>
  fetch.mock.calls.filter(([r]) => new URL((r as Request).url).pathname === "/api/engine/status").length;

function renderLiveChip() {
  const client = new QueryClient();
  const router = createMemoryRouter([{ path: "*", element: <LiveChip /> }]);
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("polling the engineer (R2)", () => {
  it("asks every 5 s while the tab is visible, and stops while it is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetch = engineer([() => Response.json(engine())]);
    renderLiveChip();
    expect(await screen.findByRole("button", { name: "Idle" })).toBeTruthy();
    expect(statusCalls(fetch)).toBe(1);

    await tick(5_000);
    expect(statusCalls(fetch)).toBe(2);
    await tick(5_000);
    expect(statusCalls(fetch)).toBe(3);

    act(() => focusManager.setFocused(false));
    await tick(20_000);
    expect(statusCalls(fetch)).toBe(3);

    // Shown again: asked straight away, then every 5 s.
    act(() => focusManager.setFocused(true));
    await tick(0);
    expect(statusCalls(fetch)).toBe(4);
    await tick(5_000);
    expect(statusCalls(fetch)).toBe(5);
  });

  it("reads a 502 as offline, with no retry, and comes back when the engineer does", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetch = engineer([
      () => Response.json(engine({ activity: "driving", session: liveSession() })),
      () => Response.json({ error: "the engineer is not answering" }, { status: 502 }),
      () => Response.json(engine({ activity: "replay" })),
    ]);
    renderLiveChip();
    expect(await screen.findByRole("button", { name: /^Live/ })).toBeTruthy();
    await tick(5_000);
    expect(await screen.findByRole("button", { name: "Engineer offline" })).toBeTruthy();
    expect(statusCalls(fetch)).toBe(2);
    await tick(5_000);
    expect(await screen.findByRole("button", { name: "Replay" })).toBeTruthy();
  });

  it("reads a pit wall that doesn't answer as offline", async () => {
    engineer([
      () => {
        throw new TypeError("Failed to fetch");
      },
    ]);
    renderLiveChip();
    expect(await screen.findByRole("button", { name: "Engineer offline" })).toBeTruthy();
  });
});
