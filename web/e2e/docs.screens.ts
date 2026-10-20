// The docs' screenshots (#336), run by playwright.docs.config.ts (`make
// docs-screenshots`), never by the e2e suite: the session list, the race's session
// page, lap compare and /_kit, at the phone and desktop sizes, into
// docs/assets/screens/<viewport>/<page>.png.
//
// The same pictures every run: the store is dated from a fixed time (the config's
// E2E_REPLAY_CLOCK), the browser's clock is fixed after the newest session, the
// time zone and locale are set, motion is reduced, the fonts have loaded, the
// engineer is in one scenario ("idle"), and no session is open (the docs config's
// E2E_NO_LIVE_SESSION), so no card says "Running" under an "Idle" chip. Each shot
// is the viewport, but the session page's: there the viewport grows to the page's
// height first, so the laps show on a phone, and the pick bar that sticks to the
// viewport's foot sits under them rather than over a lap (as a fullPage shot
// would leave it).
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import type { Page, TestInfo } from "@playwright/test";

import { setEngineer } from "./engineer";
import { apiSessions, expect, test } from "./pitwall";

/** Where the docs' screenshots go, one directory per viewport. */
const SCREENS = fileURLToPath(new URL("../../docs/assets/screens", import.meta.url));

/** After the newest replayed session, on the same day (UTC). */
const NOW = new Date("2026-10-18T20:00:00Z");

const RACE = "Circuit Gilles Villeneuve · 12-lap race";

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await setEngineer(page, "idle");
});

/** The page as it settles: fonts loaded, the engineer chip saying "Idle", nothing
 * loading (but on /_kit, which shows its loading states on purpose), no pointer over
 * anything; then the shot. */
async function shoot(
  page: Page,
  testInfo: TestInfo,
  name: string,
  { loads = true, tall = false }: { loads?: boolean; tall?: boolean } = {},
): Promise<void> {
  await page.evaluate(() => document.fonts.ready);
  await expect(page.getByRole("banner").getByRole("button", { name: "Idle", exact: true })).toBeVisible();
  if (loads) {
    await expect(page.getByRole("status", { name: /^Loading/ })).toHaveCount(0);
  }
  if (tall) {
    const width = page.viewportSize()!.width;
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width, height });
  }
  await page.mouse.move(0, 0);
  const dir = join(SCREENS, testInfo.project.name);
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: join(dir, `${name}.png`), animations: "disabled", caret: "hide" });
}

async function raceId(page: Page): Promise<string> {
  const race = (await apiSessions(page)).find((s) => s.title === RACE);
  expect(race, `a session titled ${RACE}`).toBeDefined();
  return race!.session_id;
}

test("the session list", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("main").locator('a[href^="/sessions/"]').first()).toBeVisible();
  await shoot(page, testInfo, "sessions");
});

test("the race's session page", async ({ page }, testInfo) => {
  await page.goto(`/sessions/${await raceId(page)}`);
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();
  await shoot(page, testInfo, "session", { tall: true });
});

test("lap compare: the best lap against the next fastest", async ({ page }, testInfo) => {
  await page.goto(`/sessions/${await raceId(page)}/compare`);
  await expect(page.getByRole("heading", { name: "Lap compare" })).toBeVisible();
  await expect(page.locator("[data-slot=chart] canvas")).toHaveCount(5);
  await shoot(page, testInfo, "compare");
});

test("the component kit", async ({ page }, testInfo) => {
  await page.goto("/_kit");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shoot(page, testInfo, "kit", { loads: false });
});
