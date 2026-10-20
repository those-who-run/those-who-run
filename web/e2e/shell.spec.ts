// The app shell (#296 AC1 to AC8) over the real pit wall and the stub engineer
// (./engineer.ts), at each of the three viewports, with axe on what it adds.
import type { Locator, Page } from "@playwright/test";

import { expectAccessible } from "./a11y";
import { OTHER_VERSION, setEngineer, type Scenario, TRACK } from "./engineer";
import { apiSessions, expect, expectNoHorizontalScroll, screenshot, sessionLink, test } from "./pitwall";

async function pitwallVersion(page: Page): Promise<string> {
  return (await (await page.request.get("/healthz")).json()).version;
}

const chip = (page: Page): Locator => page.getByRole("banner").locator("[data-slot=live-chip]");

/** The popover, open and done fading in: axe reads colours mid-fade as faint. */
async function openedPanel(page: Page): Promise<Locator> {
  const panel = page.getByRole("dialog", { name: "The engineer" });
  await expect(panel).toBeVisible();
  await panel.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  return panel;
}

/** Opens the chip's popover and returns it. */
async function openPopover(page: Page): Promise<Locator> {
  await chip(page).click();
  return openedPanel(page);
}

// What the chip says in each engineer state (R2), and what its popover adds.
const STATES: { scenario: Scenario; chip: string; panel: string[] }[] = [
  {
    scenario: "driving",
    chip: `Live · ${TRACK} · L3`,
    panel: ["Driving", "TelemetryConnected", "Open the live session"],
  },
  { scenario: "driving-unsure", chip: "Live · Unknown track · L2", panel: ["Driving", "TrackUnknown track"] },
  { scenario: "driving-no-session", chip: "Live", panel: ["Driving"] },
  { scenario: "paused", chip: `Paused · ${TRACK}`, panel: ["Paused", "Open the live session"] },
  { scenario: "replay", chip: "Replay", panel: ["Watching a replay"] },
  { scenario: "demo", chip: "Demo", panel: ["Running a demo"] },
  { scenario: "idle", chip: "Idle", panel: ["Idle", "TelemetryNot connected"] },
  { scenario: "menus", chip: "In the menus", panel: ["In the menus", "TelemetryConnected"] },
];

for (const s of STATES) {
  test(`the chip in the ${s.scenario} state, and its popover (AC1)`, async ({ page }) => {
    const version = await pitwallVersion(page);
    await setEngineer(page, s.scenario);
    await page.goto("/");
    await expect(chip(page)).toHaveAccessibleName(s.chip);
    await expect(chip(page)).toHaveText(s.chip);
    const panel = await openPopover(page);
    for (const text of [...s.panel, `Engineer${version}`, "Telemetry", "VoiceIn the voice channel"]) {
      await expect(panel).toContainText(text);
    }
    await expect(panel).toContainText(`Pit wall ${version} · Read-only`);
    await expect(panel).not.toContainText("deploy");
  });
}

test("the unknown track is muted, and the live dot is red (AC1)", async ({ page }) => {
  await setEngineer(page, "driving-unsure");
  await page.goto("/");
  await expect(chip(page)).toHaveText("Live · Unknown track · L2");
  const colour = (l: Locator) => l.evaluate((e) => getComputedStyle(e).color);
  expect(await colour(chip(page).getByText("Unknown track"))).toBe("rgb(163, 163, 163)");
  const dot = chip(page).locator(".bg-accent");
  expect(await dot.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe("rgb(210, 31, 27)");
});

test("the live session's link opens it (AC1)", async ({ page }) => {
  await setEngineer(page, "driving");
  await page.goto("/");
  const panel = await openPopover(page);
  await panel.getByRole("link", { name: "Open the live session" }).click();
  await expect(page).toHaveURL(/\/sessions\/20261017-162118$/);
  await expect(panel).toBeHidden();
});

test("with the engineer down, the list still loads and the chip says so within 3 s (AC1, AC2)", async ({
  page,
}, testInfo) => {
  const sessions = await apiSessions(page);
  await setEngineer(page, "down");
  const start = Date.now();
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Sessions" }).getByRole("link")).toHaveCount(sessions.length);
  await expect(chip(page)).toHaveText("Engineer offline", { timeout: 3_000 });
  expect(Date.now() - start).toBeLessThan(3_000);
  // Muted, not an error colour.
  expect(
    await chip(page)
      .getByText("Engineer offline")
      .evaluate((e) => getComputedStyle(e).color),
  ).toBe("rgb(163, 163, 163)");
  const panel = await openPopover(page);
  await expect(panel).toContainText("The sessions still work");
  await expect(panel).toContainText(`Pit wall ${await pitwallVersion(page)} · Read-only`);
  await screenshot(page, testInfo, "shell-offline");
});

test("follows the engineer as it changes, every 5 s (R2)", async ({ page }) => {
  await setEngineer(page, "idle");
  await page.goto("/");
  await expect(chip(page)).toHaveText("Idle");
  await setEngineer(page, "driving");
  await expect(chip(page)).toHaveText(`Live · ${TRACK} · L3`, { timeout: 7_000 });
});

test("says a deploy is rolling out when the versions differ (AC3)", async ({ page }, testInfo) => {
  const version = await pitwallVersion(page);
  await setEngineer(page, "other-version");
  await page.goto("/");
  await expect(chip(page)).toHaveAccessibleName("Idle, a deploy is rolling out");
  await expect(chip(page).locator("[data-slot=deploy-marker]")).toBeVisible();
  const panel = await openPopover(page);
  await expect(panel).toContainText(`Engineer ${OTHER_VERSION}, pit wall ${version}: a deploy is rolling out`);
  await screenshot(page, testInfo, "shell-deploy");
});

test("shows no navigation with one section, and both layouts with two (AC4)", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Sessions" })).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);

  // /_kit shows the real Nav with two sections, in the page's flow.
  await page.goto("/_kit");
  const nav = page.getByRole("navigation", { name: "Sections (sample)" });
  await nav.scrollIntoViewIfNeeded();
  await expect(nav.getByRole("link")).toHaveText(["Sessions", "Live"]);
  await expect(nav.getByRole("link", { name: "Sessions" })).toHaveAttribute("aria-current", "page");
  const layout = await nav.evaluate((n) => {
    const list = n.querySelector("ul")!;
    const bar = n.querySelector("[data-slot=nav-bar]")!.getBoundingClientRect();
    return {
      direction: getComputedStyle(list).flexDirection,
      height: n.getBoundingClientRect().height,
      width: n.getBoundingClientRect().width,
      bar: { width: bar.width, height: bar.height },
    };
  });
  const wide = (page.viewportSize()?.width ?? 0) >= 1024;
  if (wide) {
    // A side rail: one column, the red bar 3 px wide on the item's left edge.
    expect(layout.direction).toBe("column");
    expect(layout.width).toBeLessThanOrEqual(96);
    expect(layout.bar.width).toBe(3);
  } else {
    // A bottom tab bar: one row, at most 64 px, the bar 3 px tall on the item's top edge.
    expect(layout.direction).toBe("row");
    expect(layout.height).toBeLessThanOrEqual(64);
    expect(layout.bar.height).toBe(3);
  }
  await screenshot(page, testInfo, "kit-navigation");
});

test("the header: wordmark home, the page's title on wider screens, at most 56 px (R1, R5)", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Sessions · Pit wall");
  const header = page.getByRole("banner");
  const box = (await header.boundingBox())!;
  expect(box.height).toBeLessThanOrEqual(56);
  expect(await header.evaluate((h) => getComputedStyle(h).position)).toBe("sticky");
  expect(
    await header.evaluate((h) => [getComputedStyle(h).borderBottomWidth, getComputedStyle(h).borderBottomColor]),
  ).toEqual(["2px", "rgb(210, 31, 27)"]);
  const title = header.locator("[data-slot=header-title]");
  if ((page.viewportSize()?.width ?? 0) >= 640) {
    await expect(title).toHaveText("Sessions");
    await expect(title).toBeVisible();
  } else {
    await expect(title).toBeHidden();
  }

  const [first] = await apiSessions(page);
  await sessionLink(page, first!.session_id).click();
  await expect(page).toHaveTitle(`${first!.title} · Pit wall`);
  await header.getByRole("link", { name: "Those Who Run" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expectNoHorizontalScroll(page);
});

type ApiSession = Awaited<ReturnType<typeof apiSessions>>[number];

/** A list long enough to scroll on any of the three screens, a session a minute.
 * The 61st is a real one, so its page opens. */
async function longList(page: Page): Promise<ApiSession> {
  const [real] = await apiSessions(page);
  const sessions = Array.from({ length: 80 }, (_, i) => ({
    ...real,
    session_id: i === 60 ? real!.session_id : `20261001-${String(100000 + i)}`,
    title: `Session ${i + 1} · ${real!.title}`,
    started_at: real!.started_at - 60 * i,
  }));
  const options = { track: [], car: [], kind: [] };
  await page.route(/\/api\/v1\/sessions(\?.*)?$/, (route) =>
    route.fulfill({ json: { sessions, options, total: sessions.length, matched: sessions.length } }),
  );
  return real!;
}

for (const how of ["the browser's Back", "the page's back link"]) {
  test(`returns to the list's scroll and filters with ${how} (AC5)`, async ({ page }) => {
    const real = await longList(page);
    await page.goto("/?track=Suzuka");
    // 25 cards a page (#297 R6): the 61st is on the third, which Back keeps. The second
    // click can land before the first has rendered; each is still a page (#379).
    await page.getByRole("button", { name: "Show more" }).click();
    await page.getByRole("button", { name: "Show more" }).click();
    const link = sessionLink(page, real.session_id);
    await link.scrollIntoViewIfNeeded();
    const scrolled = await page.evaluate(() => window.scrollY);
    expect(scrolled).toBeGreaterThan(200);
    await link.click();
    // The session page names itself by its title; it has more than one h2 once its
    // race story is in, so a bare level-2 heading is ambiguous (#379).
    await expect(page).toHaveTitle(`${real.title} · Pit wall`);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

    if (how === "the browser's Back") {
      await page.goBack();
    } else {
      await page.getByRole("link", { name: "All sessions" }).click();
    }
    await expect(page).toHaveURL(/\/\?track=Suzuka$/);
    await expect(link).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(scrolled);
  });
}

test("an unknown path is a 404 page with the way home (AC6)", async ({ page }, testInfo) => {
  await page.goto("/nope");
  await expect(page.getByRole("heading", { name: "Nothing here" })).toBeVisible();
  await expect(page).toHaveTitle("Nothing here · Pit wall");
  await expectAccessible(page, testInfo, "shell-not-found");
  await page.getByRole("main").getByRole("link", { name: "All sessions" }).click();
  await expect(page.getByRole("list", { name: "Sessions" })).toBeVisible();
});

test("a page that throws shows its error state, and the header still works (AC6)", async ({ page }, testInfo) => {
  await setEngineer(page, "idle");
  await page.goto("/_kit?throw");
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("This page failed to show.");
  await expect(alert.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page).toHaveTitle("Page failed · Pit wall");
  await expect(chip(page)).toHaveText("Idle");
  await expectAccessible(page, testInfo, "shell-route-error");
  await screenshot(page, testInfo, "shell-route-error");

  await openPopover(page);
  await page.keyboard.press("Escape");
  await page.getByRole("banner").getByRole("link", { name: "Those Who Run" }).click();
  await expect(page.getByRole("list", { name: "Sessions" })).toBeVisible();
});

test("a page whose chunk is gone after a deploy offers a reload (AC6)", async ({ page }) => {
  await page.goto("/");
  await page.route(/\/assets\/session-[^/]*\.js$/, (route) => route.abort());
  const [first] = await apiSessions(page);
  await sessionLink(page, first!.session_id).click();
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("The pit wall has been updated since this tab opened.");
  await page.unroute(/\/assets\/session-[^/]*\.js$/);
  await alert.getByRole("button", { name: "Reload to get the new version" }).click();
  // The session page names itself by its title; its heading is the track (#298).
  await expect(page).toHaveTitle(`${first!.title} · Pit wall`);
});

test("axe passes on the shell with the popover open, which the keyboard reaches (AC7)", async ({ page }, testInfo) => {
  await setEngineer(page, "driving");
  await page.goto("/");
  await expect(chip(page)).toHaveText(`Live · ${TRACK} · L3`);
  await expectAccessible(page, testInfo, "shell");

  // Tab: the wordmark, then the chip.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("banner").getByRole("link", { name: "Those Who Run" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(chip(page)).toBeFocused();
  await page.keyboard.press("Enter");
  const panel = await openedPanel(page);
  await expect(panel.getByRole("link", { name: "Open the live session" })).toBeVisible();
  await expectAccessible(page, testInfo, "shell-popover");
  await screenshot(page, testInfo, "shell-popover");
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(chip(page)).toBeFocused();
  // The chip is a 44 px target.
  const box = (await chip(page).boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(44);
});

/** A PNG's width and height, from its IHDR chunk. */
function pngSize(body: Buffer): [number, number] {
  return [body.readUInt32BE(16), body.readUInt32BE(20)];
}

test("the web manifest and the home screen icons (AC8)", async ({ page }) => {
  const resp = await page.request.get("/manifest.webmanifest");
  expect(resp.ok()).toBe(true);
  const manifest = await resp.json();
  expect(manifest).toMatchObject({
    name: "Those Who Run · Pit wall",
    short_name: "Pit wall",
    start_url: "/",
    display: "standalone",
    theme_color: "#111111",
    background_color: "#111111",
  });
  const pngs = (manifest.icons as { src: string; sizes: string; type: string; purpose: string }[]).filter(
    (i) => i.type === "image/png",
  );
  expect(pngs.map((i) => `${i.sizes} ${i.purpose}`)).toEqual(["192x192 any", "512x512 any", "512x512 maskable"]);
  for (const icon of pngs) {
    const r = await page.request.get(icon.src);
    expect(r.ok(), icon.src).toBe(true);
    expect(r.headers()["content-type"]).toBe("image/png");
    const [w, h] = pngSize(await r.body());
    expect(`${w}x${h}`, icon.src).toBe(icon.sizes);
  }

  await page.goto("/");
  const head = await page.evaluate(() => ({
    manifest: document.querySelector('link[rel="manifest"]')?.getAttribute("href"),
    touch: document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href"),
    viewport: document.querySelector('meta[name="viewport"]')?.getAttribute("content"),
    appTitle: document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute("content"),
  }));
  expect(head).toEqual({
    manifest: "/manifest.webmanifest",
    touch: "/apple-touch-icon.png",
    viewport: expect.stringContaining("viewport-fit=cover"),
    appTitle: "Pit wall",
  });
  const touch = await page.request.get(head.touch!);
  expect(touch.ok()).toBe(true);
  expect(pngSize(await touch.body())).toEqual([180, 180]);
});
