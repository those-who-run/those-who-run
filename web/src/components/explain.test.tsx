// LapFlag and Unknown: the explanation behind a tap, by pointer and by keyboard
// (#295 R2, R6, AC5, AC6). KindBadge and LiveBadge, the plain labels beside them.
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { KindBadge } from "./kind-badge";
import { LapFlag } from "./lap-flag";
import { LiveBadge } from "./live-badge";
import { Unknown } from "./unknown";

beforeAll(() => {
  // Radix measures its popper; jsdom has no ResizeObserver.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(cleanup);

describe("LapFlag", () => {
  it.each([
    ["pit", "Pit", "Pit lap", /Fuel went up/],
    ["out", "Out", "Out lap", /after a pit stop/],
    ["partial", "Partial", "Partial lap", /session ended in/],
    ["restart", "Restart", "Engineer restarted", /engineer restarted/],
  ] as const)("%s: its word opens what it means on a click", async (flag, label, title, text) => {
    const user = userEvent.setup();
    render(<LapFlag flag={flag} />);
    const button = screen.getByRole("button", { name: label });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    await user.click(button);
    const dialog = await screen.findByRole("dialog", { name: title });
    expect(dialog.textContent).toMatch(text);
    expect(dialog.textContent).toContain("It isn't counted in averages.");
    expect(button.getAttribute("aria-expanded")).toBe("true");
  });

  it("opens with Enter and closes with Escape", async () => {
    const user = userEvent.setup();
    render(<LapFlag flag="pit" />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Pit" }));
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Pit lap" })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a 44 px target", () => {
    render(<LapFlag flag="out" />);
    expect(screen.getByRole("button", { name: "Out" }).className).toMatch(/min-h-11.*min-w-11/);
  });
});

describe("Unknown", () => {
  it("is muted, with the reason on tap", async () => {
    const user = userEvent.setup();
    render(<Unknown reason="3 layouts near the start still fit, line not yet crossed." />);
    const button = screen.getByRole("button", { name: "Unknown track" });
    expect(button.querySelector("[data-slot=unknown]")!.className).toContain("text-muted");
    await user.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Unknown track" });
    expect(dialog.textContent).toContain("3 layouts near the start");
  });

  it("is muted text only when there is no reason", () => {
    const { container } = render(<Unknown label="Unknown car" reason={null} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.textContent).toBe("Unknown car");
    expect(container.firstElementChild!.className).toContain("text-muted");
  });
});

describe("KindBadge", () => {
  it("shows the API's label", () => {
    render(<KindBadge label="12-lap race" kind="lap_race" />);
    expect(screen.getByText("12-lap race").getAttribute("data-variant")).toBe("outline");
  });

  it("is muted for an unknown kind", () => {
    render(<KindBadge label="session" kind="unknown" />);
    expect(screen.getByText("session").getAttribute("data-variant")).toBe("muted");
  });
});

describe("LiveBadge", () => {
  it("says Live, with a red dot that pulses only where motion is welcome", () => {
    const { container } = render(<LiveBadge />);
    expect(container.textContent).toBe("Live");
    const dot = container.querySelector("[aria-hidden]")!;
    expect(dot.className).toContain("bg-accent");
    expect(dot.className).toContain("motion-safe:animate-pulse");
  });

  it("says Paused, with a still, hollow dot", () => {
    const { container } = render(<LiveBadge state="paused" />);
    expect(container.textContent).toBe("Paused");
    const dot = container.querySelector("[aria-hidden]")!;
    expect(dot.className).not.toContain("bg-accent");
    expect(dot.className).not.toContain("animate");
  });
});
