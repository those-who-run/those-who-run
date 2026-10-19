// StatTile, EmptyState and ErrorState in each state (#295 R2, R3, AC6).
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyState } from "./empty-state";
import { ErrorState } from "./error-state";
import { StatTile, StatTileSkeleton } from "./stat-tile";
import { Button } from "./ui/button";
import { fuelPct, lapTime, missing } from "@/lib/format";

/** Moves fake time on, letting React render what the timers set. */
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("StatTile", () => {
  it("shows a label, a value and a sub-line", () => {
    const { container } = render(<StatTile label="Best lap" value={lapTime(87_764)} sub="lap 4" tone="best" />);
    expect(container.textContent).toBe("Best lap1:27.764lap 4");
    const value = screen.getByText("1:27.764");
    expect(value.className).toContain("num-lg");
    expect(value.className).toContain("text-timing-best");
    expect(screen.getByText("Best lap").className).toContain("uppercase");
  });

  it("shows a missing value as a muted dash, said as unknown", () => {
    render(<StatTile label="Top speed" value={missing()} />);
    expect(screen.getByText("Unknown").className).toBe("sr-only");
    expect(screen.getByText("—").parentElement!.className).toContain("text-muted");
  });

  it("takes Fuel off as its value", () => {
    render(<StatTile label="Fuel" value={fuelPct(43, { fuelUse: false })} />);
    expect(screen.getByText("Fuel off")).toBeTruthy();
  });

  it("has no sub-line unless given one", () => {
    const { container } = render(<StatTile label="Fuel" value="43%" />);
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });

  it("loads as its own shape, after 150 ms", async () => {
    vi.useFakeTimers();
    render(<StatTileSkeleton label="Best lap" />);
    const status = screen.getByRole("status", { name: "Loading best lap" });
    expect(status.textContent).toContain("Best lap");
    expect(status.querySelectorAll("p")).toHaveLength(3);
    expect(status.className).toContain("invisible");
    await tick(150);
    expect(status.className).not.toContain("invisible");
  });
});

describe("EmptyState", () => {
  it("says what is missing, why, and what to do", () => {
    render(
      <EmptyState
        title="No sessions yet"
        why="Drive a lap with the engineer running."
        action={<Button>Show all tracks</Button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "No sessions yet" })).toBeTruthy();
    expect(screen.getByText("Drive a lap with the engineer running.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show all tracks" })).toBeTruthy();
  });

  it("needs no action", () => {
    render(<EmptyState title="No laps stored for this session." why="The session ended before a lap." headingLevel={2} />);
    expect(screen.getByRole("heading", { level: 2 })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ErrorState", () => {
  it("says what failed and what to do, with the detail behind a disclosure", async () => {
    const user = userEvent.setup();
    render(<ErrorState title="Couldn't read the session store." detail="503 the index is busy" />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Couldn't read the session store.");
    expect(alert.textContent).toContain("Retry, or check the engineer's logs.");
    const details = alert.querySelector("details")!;
    expect(details.open).toBe(false);
    await user.click(screen.getByText("Details"));
    expect(details.open).toBe(true);
    expect(screen.getByText("503 the index is busy")).toBeTruthy();
  });

  it("retries", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<ErrorState title="Couldn't load the laps." onRetry={onRetry} />);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("can't be retried twice at once", () => {
    render(<ErrorState title="Couldn't load the laps." onRetry={() => {}} retrying />);
    expect((screen.getByRole("button", { name: "Retrying…" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("has no detail or Retry unless given them", () => {
    const { container } = render(<ErrorState title="A lap file is missing or still being written." />);
    expect(container.querySelector("details")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
