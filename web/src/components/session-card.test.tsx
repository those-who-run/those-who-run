// SessionCard from the API's Session values, in each state the guide lists (#295
// R2, R7, AC4, AC6), with the kit's samples.
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { SessionCard, SessionCardSkeleton } from "./session-card";
import { KIT_NOW, KIT_TZ, NAMES, SESSIONS } from "@/kit/samples";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

/** Moves fake time on, letting React render what the timers set. */
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function withRouter(node: ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

function card(session: (typeof SESSIONS)[keyof typeof SESSIONS], live?: "live" | "paused") {
  withRouter(<SessionCard session={session} to={`/sessions/${session.session_id}`} live={live} now={KIT_NOW} tz={KIT_TZ} />);
  return screen.getByRole("article");
}

describe("SessionCard", () => {
  it("race finished: the full track name, linked, with the result from the values", () => {
    const el = card(SESSIONS.raceFinished);
    const link = within(el).getByRole("link", { name: NAMES.willow });
    expect(link.getAttribute("href")).toBe("/sessions/20261018-191204");
    expect(link.getAttribute("title")).toBe(NAMES.willow);
    expect(link.className).toContain("line-clamp-2");
    expect(within(el).getByRole("heading", { level: 3 }).textContent).toBe(NAMES.willow);
    expect(el.textContent).toContain("6-lap race");
    expect(el.textContent).toContain(NAMES.rxVision);
    expect(el.textContent).toContain("Today 20:00");
    expect(el.textContent).toContain("Finished P1/16Position 1 of 16 in 9:56.826");
    expect(el.textContent).toContain("Best 1:37.764 (best lap) (lap 4)");
  });

  it("retired: Python's wording, in sentence case", () => {
    const el = card(SESSIONS.retired);
    expect(el.textContent).toContain("Retired on lap 3 of 12, running P15");
    expect(el.textContent).toContain("Yesterday 17:00");
  });

  it("timed: finished with a position and race time", () => {
    const el = card(SESSIONS.timed);
    expect(el.textContent).toContain("timed race");
    expect(el.textContent).toContain("Finished P3/20Position 3 of 20 in 21:06.182");
  });

  it("time trial: laps and the best lap, no position", () => {
    const el = card(SESSIONS.timeTrial);
    expect(el.textContent).toContain("time trial");
    expect(el.textContent).toContain("5 laps");
    expect(el.textContent).toContain("Best 49.677");
    expect(el.textContent).not.toMatch(/Position/);
    expect(el.textContent).toContain("Wed 14 Oct");
  });

  it("unknown track: muted, the reason on tap, the card still a link", async () => {
    const user = userEvent.setup();
    const el = card(SESSIONS.unknownTrack);
    const link = within(el).getByRole("link", { name: "Unknown track" });
    expect(link.getAttribute("href")).toBe("/sessions/20261018-140201");
    const why = within(el).getByRole("button", { name: "Unknown track" });
    await user.click(why);
    const dialog = await screen.findByRole("dialog", { name: "Unknown track" });
    expect(dialog.textContent).toContain("3 layouts near the start still fit, line not yet crossed.");
    // No car: unknown too, with GT7's code as the reason.
    await user.keyboard("{Escape}");
    await user.click(within(el).getByRole("button", { name: "Unknown car" }));
    expect((await screen.findByRole("dialog", { name: "Unknown car" })).textContent).toContain("car code 4012");
    expect(el.textContent).toContain("No full lap");
  });

  it("live: the badge, the lap and the running position", () => {
    const el = card(SESSIONS.live, "live");
    expect(el.getAttribute("data-live")).toBe("live");
    expect(el.textContent).toContain("Live");
    expect(el.textContent).toContain("Lap 5 of 12, running P3/16");
  });

  it("paused: the same, paused", () => {
    const el = card(SESSIONS.live, "paused");
    expect(el.textContent).toContain("Paused");
  });

  it("lays out by its own width: stacked, a row from 28 rem", () => {
    const el = card(SESSIONS.raceFinished);
    expect(el.className).toContain("@container");
    expect(el.firstElementChild!.className).toMatch(/flex-col .*@md:flex-row/);
  });

  it("loads as its own shape, after 150 ms", async () => {
    vi.useFakeTimers();
    withRouter(<SessionCardSkeleton />);
    const status = screen.getByRole("status", { name: "Loading session" });
    expect(status.className).toContain("@container");
    expect(status.className).toContain("invisible");
    await tick(150);
    expect(status.className).not.toContain("invisible");
  });
});
