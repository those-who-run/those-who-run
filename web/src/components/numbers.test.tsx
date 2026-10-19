// LapTime, Gap and Position in each state (#295 R2, R8, AC6).
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Gap, GapSkeleton } from "./gap";
import { LapTime, LapTimeSkeleton } from "./lap-time";
import { Position, PositionSkeleton } from "./position";

/** Moves fake time on, letting React render what the timers set. */
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("LapTime", () => {
  it("formats through lapTime()", () => {
    const { container } = render(<LapTime ms={87_764} />);
    expect(container.textContent).toBe("1:27.764");
    expect(container.firstElementChild!.className).toContain("num");
    expect(container.firstElementChild!.className).toContain("whitespace-nowrap");
  });

  it("marks the best lap in purple and in words", () => {
    const { container } = render(<LapTime ms={49_677} best />);
    const el = container.firstElementChild!;
    expect(el.className).toContain("text-timing-best");
    expect(el.getAttribute("data-best")).toBe("true");
    expect(screen.getByText("(best lap)").className).toBe("sr-only");
  });

  it("shows an invalid lap as a muted dash with an accessible label", () => {
    const { container } = render(<LapTime ms={87_764} invalid />);
    expect(container.querySelector("[aria-hidden]")!.textContent).toBe("—");
    expect(screen.getByText("No lap time").className).toBe("sr-only");
    expect(container.firstElementChild!.className).toContain("text-muted");
    expect(container.textContent).not.toContain("1:27");
  });

  it("shows a missing time the same way", () => {
    render(<LapTime ms={null} />);
    expect(screen.getByText("No lap time")).toBeTruthy();
  });

  it.each([
    ["sm", "text-sm"],
    ["md", "text-base"],
    ["xl", "num-xl"],
  ] as const)("comes in size %s", (size, cls) => {
    const { container } = render(<LapTime ms={87_764} size={size} />);
    expect(container.firstElementChild!.className).toContain(cls);
  });
});

describe("Gap", () => {
  it("reads −0.312 for −312 ms, in the faster style", () => {
    const { container } = render(<Gap ms={-312} />);
    const el = container.firstElementChild!;
    expect(el.textContent).toBe("−0.312");
    expect(el.getAttribute("data-trend")).toBe("faster");
    expect(el.className).toContain("text-timing-improve");
  });

  it("reads +0.866 for 866 ms, in the slower style", () => {
    const { container } = render(<Gap ms={866} />);
    const el = container.firstElementChild!;
    expect(el.textContent).toBe("+0.866");
    expect(el.getAttribute("data-trend")).toBe("slower");
    expect(el.className).toContain("text-timing-slower");
  });

  it("reads Best for the reference lap", () => {
    const { container } = render(<Gap ms={0} best />);
    const el = container.firstElementChild!;
    expect(el.textContent).toBe("Best");
    expect(el.className).toContain("text-timing-best");
  });

  it("keeps the sign on an even gap, without a timing colour", () => {
    const { container } = render(<Gap ms={0.4} />);
    const el = container.firstElementChild!;
    expect(el.textContent).toBe("+0.000");
    expect(el.getAttribute("data-trend")).toBe("even");
    expect(el.className).not.toMatch(/text-timing/);
  });

  it("says when there is no gap", () => {
    render(<Gap ms={null} />);
    expect(screen.getByText("No gap")).toBeTruthy();
  });
});

describe("Position", () => {
  it("is P3 with a muted /16, spoken as a position", () => {
    const { container } = render(<Position position={3} cars={16} />);
    const shown = container.querySelector("[aria-hidden]")!;
    expect(shown.textContent).toBe("P3/16");
    expect(screen.getByText("/16").className).toContain("text-muted");
    expect(screen.getByText("Position 3 of 16").className).toBe("sr-only");
  });

  it("is P1/1 alone in the field", () => {
    const { container } = render(<Position position={1} cars={1} />);
    expect(container.querySelector("[aria-hidden]")!.textContent).toBe("P1/1");
  });

  it("drops the field when its size is unknown", () => {
    render(<Position position={4} cars={null} />);
    expect(screen.getByText("Position 4")).toBeTruthy();
  });

  it("is hidden when the API says a position means nothing", () => {
    const { container } = render(<Position position={3} cars={16} shown={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("is a muted dash when unknown", () => {
    render(<Position position={null} cars={16} />);
    expect(screen.getByText("Position unknown")).toBeTruthy();
  });
});

describe("number skeletons", () => {
  it.each([
    ["lap time", <LapTimeSkeleton key="l" />, "0:00.000"],
    ["gap", <GapSkeleton key="g" />, "+0.000"],
    ["position", <PositionSkeleton key="p" />, "P00/00"],
  ])("hold a %s's place, invisibly, for 150 ms", async (what, el, sample) => {
    vi.useFakeTimers();
    render(el);
    const status = screen.getByRole("status", { name: `Loading ${what}` });
    expect(status.textContent).toBe(sample);
    expect(status.className).toContain("invisible");
    await tick(149);
    expect(status.className).toContain("invisible");
    await tick(1);
    expect(status.className).not.toContain("invisible");
  });
});
