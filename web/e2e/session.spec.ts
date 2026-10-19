// The session page over the real pit wall and the replayed store (#298), at each of
// the three viewports, each state checked by axe (ADR 0004 point 11). The live case
// drives the store's open session (./store.ts) with the stub engineer.
import type { Page } from "@playwright/test";

import { expectAccessible } from "./a11y";
import { setEngineer } from "./engineer";
import { apiSessions, expect, expectNoHorizontalScroll, screenshot, test } from "./pitwall";
import { addLap, LIVE_LAPS_AT_START, LIVE_SESSION_ID } from "./store";

interface LapRow {
  lap: number;
  time_ms: number | null;
  clean: boolean;
  invalid: boolean;
  fuel_used: number | null;
}

/** The replayed session with this title (not the open copy), and its laps. */
async function sessionTitled(page: Page, title: string) {
  const s = (await apiSessions(page)).find((x) => x.title === title && x.session_id !== LIVE_SESSION_ID);
  expect(s, `a session titled ${title}`).toBeTruthy();
  const one = await (await page.request.get(`/api/v1/sessions/${s!.session_id}`)).json();
  const laps = (await (await page.request.get(`/api/v1/sessions/${s!.session_id}/laps`)).json()).laps as LapRow[];
  return { id: s!.session_id as string, session: one, laps };
}

const RACE = "Circuit Gilles Villeneuve · 12-lap race";
const PIT_STOP = "Suzuka Circuit East Course · 6-lap race";
const JOINED = "Suzuka Circuit · timed race";

const tile = (page: Page, label: string) =>
  page
    .getByRole("region", { name: "Summary" })
    .locator("[data-slot=stat-tile]")
    .filter({ has: page.getByText(label, { exact: true }) });
const row = (page: Page, lap: number) => page.locator(`tbody tr[data-lap="${lap}"]`);

/** The mean of the clean laps' times, as format.ts writes it: whole ms, truncated. */
function cleanAverage(laps: LapRow[]): number {
  const clean = laps.filter((l) => l.clean && !l.invalid && l.time_ms);
  return clean.reduce((n, l) => n + l.time_ms!, 0) / clean.length;
}

function clock(ms: number): string {
  const whole = Math.trunc(ms);
  const m = Math.trunc(whole / 60_000);
  const s = Math.trunc((whole % 60_000) / 1000);
  const frac = String(whole % 1000).padStart(3, "0");
  return m ? `${m}:${String(s).padStart(2, "0")}.${frac}` : `${s}.${frac}`;
}

test("the race: the result first, then its figures (AC1)", async ({ page }, testInfo) => {
  const { id, session, laps } = await sessionTitled(page, RACE);
  await page.goto(`/sessions/${id}`);

  const hero = page.locator("[data-slot=session-hero]");
  await expect(hero.getByRole("heading", { level: 2 })).toHaveText("Circuit Gilles Villeneuve");
  await expect(hero).toContainText("12-lap race");
  await expect(hero).toContainText(session.car);
  // The fixture is the first 230 s of the race: it ends retired on lap 3, P15.
  const headline = hero.locator("[data-slot=headline]");
  await expect(headline).toContainText(`Position ${session.final_position} of ${session.total_cars}`);
  await expect(headline).toContainText("Retired on lap 3 of 12, running P15");
  await expect(page).toHaveTitle(`${RACE} · Pit wall`);

  await expect(tile(page, "Best lap")).toContainText(clock(session.best_lap_ms));
  await expect(tile(page, "Best lap")).toContainText(`lap ${session.best_lap_no}`);
  const clean = laps.filter((l) => l.clean && !l.invalid).length;
  await expect(tile(page, "Average")).toContainText(clock(cleanAverage(laps)));
  await expect(tile(page, "Average")).toContainText(`of ${clean} clean laps`);
  await expect(tile(page, "Laps")).toContainText(`${session.laps_completed}of ${session.total_laps}`);
  // The tank is 100 of GT7's units: fuel is a share of it.
  await expect(tile(page, "Fuel used")).toContainText(`${Math.round((100 * session.fuel_used) / session.fuel_capacity)}%`);
  await expect(tile(page, "Fuel used")).toContainText("per lap");
  await expect(tile(page, "Pit stops")).toContainText("0");

  // The partial lap is muted, with its flag; the best is purple and named.
  await expect(row(page, 3)).toHaveAttribute("data-partial", "true");
  await expect(row(page, 3).getByRole("button", { name: "Partial" })).toBeVisible();
  await expect(row(page, session.best_lap_no)).toContainText("(best lap)");
  await expect(row(page, session.best_lap_no)).toContainText("Best");

  if (testInfo.project.name === "phone") {
    // R1: the answer is above the fold on a 390 × 844 phone.
    const box = await headline.boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  }
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "session-race");
  await expectAccessible(page, testInfo, "session-race");
});

test("the pit stop: pit and out laps flagged, and left out of the average (AC2)", async ({ page }, testInfo) => {
  const { id, laps } = await sessionTitled(page, PIT_STOP);
  await page.goto(`/sessions/${id}`);
  await expect(page.locator("[data-slot=headline]")).toContainText("Finished in 6:29.934");

  await expect(row(page, 3).getByRole("button", { name: "Pit", exact: true })).toBeVisible();
  await expect(row(page, 4).getByRole("button", { name: "Out", exact: true })).toBeVisible();
  // Its explanation opens on a tap, in place of the old caption.
  await row(page, 3).getByRole("button", { name: "Pit", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Pit lap" })).toContainText("It isn't counted in averages.");
  await page.keyboard.press("Escape");

  const clean = laps.filter((l) => l.clean && !l.invalid);
  expect(clean.map((l) => l.lap)).toEqual([1, 2, 5, 6]);
  await expect(tile(page, "Average")).toContainText(clock(cleanAverage(laps)));
  await expect(tile(page, "Average")).toContainText("of 4 clean laps");
  await expect(tile(page, "Pit stops")).toContainText("1");
  await expect(tile(page, "Driving")).toContainText("paused 2 s");
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "session-pit-stop");
});

test("fits the screen: four columns on a phone, the rest on a tap (AC3)", async ({ page }, testInfo) => {
  const { id } = await sessionTitled(page, PIT_STOP);
  await page.goto(`/sessions/${id}`);
  const head = page.locator("thead");
  for (const name of ["Lap", "Time", "Gap", "Pos"]) {
    await expect(head.getByRole("columnheader", { name, exact: true })).toBeVisible();
  }
  const wide = ["Fuel used", "Fuel left", "Top km/h"];
  if (testInfo.project.name === "phone") {
    for (const name of wide) {
      await expect(head.getByRole("columnheader", { name, exact: true })).toBeHidden();
    }
    await expectNoHorizontalScroll(page);
    // A tap on the row opens its fuel and top speed under it; another closes them.
    await row(page, 2).locator("td").nth(2).click();
    const detail = page.locator('tr[data-detail="2"]');
    await expect(detail).toContainText("Fuel used");
    await expect(detail).toContainText("Top speed");
    await expect(detail).toContainText("km/h");
    await expect(row(page, 2).getByRole("button", { name: "Lap 2: fuel and top speed" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expectNoHorizontalScroll(page);
    await screenshot(page, testInfo, "session-row-open");
    await row(page, 2).locator("td").nth(2).click();
    await expect(detail).toHaveCount(0);
  } else {
    for (const name of wide) {
      await expect(head.getByRole("columnheader", { name, exact: true })).toBeVisible();
    }
    await expect(row(page, 2)).toContainText("km/h");
    await expectNoHorizontalScroll(page);
  }
  await screenshot(page, testInfo, "session-columns");
});

test("picks two laps for compare, and Back keeps them (AC4)", async ({ page }) => {
  const { id } = await sessionTitled(page, PIT_STOP);
  await page.goto(`/sessions/${id}`);
  const bar = page.getByRole("region", { name: "Compare" });
  // None picked: the best lap (5) against the next fastest that isn't quicker (6).
  await expect(bar.getByRole("link", { name: "Compare best and next fastest" })).toHaveAttribute(
    "href",
    `/sessions/${id}/compare?a=5&b=6`,
  );

  const pick = (lap: number) => page.getByRole("checkbox", { name: `Pick lap ${lap} to compare` });
  const box = await pick(2).boundingBox();
  // The checkbox's label is the 44 px target around it.
  const target = await page.locator(`tbody tr[data-lap="2"] label`).boundingBox();
  expect(target!.width).toBeGreaterThanOrEqual(44);
  expect(target!.height).toBeGreaterThanOrEqual(44);
  expect(box).toBeTruthy();

  await pick(2).check();
  await expect(bar).toContainText("L2 picked");
  await pick(4).check();
  const link = bar.getByRole("link", { name: "Compare L2 and L4" });
  await expect(link).toHaveAttribute("href", `/sessions/${id}/compare?a=2&b=4`);
  await expect(page).toHaveURL(`/sessions/${id}?pick=2%2C4`);
  await expect(row(page, 2)).toHaveAttribute("data-state", "selected");

  // A third pick replaces the oldest.
  await pick(5).check();
  await expect(pick(2)).not.toBeChecked();
  await expect(bar.getByRole("link", { name: "Compare L4 and L5" })).toBeVisible();
  await pick(5).uncheck();
  await pick(2).check();
  await expect(link).toBeVisible();

  await link.click();
  await expect(page).toHaveURL(`/sessions/${id}/compare?a=2&b=4`);
  await page.goBack();
  await expect(pick(2)).toBeChecked();
  await expect(pick(4)).toBeChecked();
  await expect(bar.getByRole("link", { name: "Compare L2 and L4" })).toBeVisible();

  await bar.getByRole("button", { name: "Clear" }).click();
  await expect(pick(2)).not.toBeChecked();
  await expect(page).toHaveURL(`/sessions/${id}`);
});

test("a live session's new lap lands without a reload, under what is read (AC5)", async ({ page }, testInfo) => {
  // It writes to the store's one open session, so it runs at one width.
  test.skip(testInfo.project.name !== "phone", "the store's open session is driven once");
  const store = process.env.PITWALL_STORE!;
  const source = process.env.PITWALL_LIVE_SOURCE!;
  await setEngineer(page, "live-store");
  const lapAsks: number[] = [];
  page.on("request", (r) => {
    if (r.url().includes(`/api/v1/sessions/${LIVE_SESSION_ID}/laps`)) {
      lapAsks.push(Date.now());
    }
  });

  await page.goto(`/sessions/${LIVE_SESSION_ID}`);
  const hero = page.locator("[data-slot=session-hero]");
  await expect(hero.locator("[data-slot=live-badge]")).toHaveText("Live");
  await expect(page.locator("tbody tr[data-lap]")).toHaveCount(LIVE_LAPS_AT_START);
  const next = LIVE_LAPS_AT_START + 1;
  await expect(page.locator("tr[data-in-progress]")).toHaveText(`Lap ${next} in progress`);
  await screenshot(page, testInfo, "session-live");

  // Read part way down, then the engineer commits a lap.
  await page.evaluate(() => window.scrollTo(0, 300));
  const scrolled = await page.evaluate(() => window.scrollY);
  expect(scrolled).toBeGreaterThan(0);
  addLap(store, source, next);
  await expect(row(page, next)).toBeVisible({ timeout: 6_000 });
  await expect(page.locator("tr[data-in-progress]")).toHaveText(`Lap ${next + 1} in progress`);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);
  await expect(tile(page, "Laps")).toContainText(`${next}of 6`);

  // The engineer leaves the session: the page stops asking.
  await setEngineer(page, "idle");
  await expect(hero.locator("[data-slot=live-badge]")).toHaveCount(0, { timeout: 8_000 });
  await expect(page.locator("tr[data-in-progress]")).toHaveCount(0);
  await page.waitForTimeout(1_000);
  const asked = lapAsks.length;
  await page.waitForTimeout(6_000);
  expect(lapAsks.length, "laps asked for after the session stopped being live").toBe(asked);
  await expectAccessible(page, testInfo, "session-live");
});

test("an unknown id says so, and a session with no laps is empty (AC6)", async ({ page }, testInfo) => {
  await page.goto("/sessions/nope");
  await expect(page.getByRole("heading", { level: 2, name: "No session nope." })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "All sessions" })).toHaveAttribute("href", "/");
  await expect(page).toHaveTitle("Session not found · Pit wall");
  await expectAccessible(page, testInfo, "session-unknown");

  const { id } = await sessionTitled(page, RACE);
  await page.route(`**/api/v1/sessions/${id}/laps`, (route) => route.fulfill({ json: { session_id: id, laps: [] } }));
  await page.goto(`/sessions/${id}`);
  await expect(page.getByRole("heading", { name: "No laps stored for this session." })).toBeVisible();
  await expectAccessible(page, testInfo, "session-no-laps");
});

test("an unreadable store shows the error state, with Retry", async ({ page }, testInfo) => {
  const { id } = await sessionTitled(page, RACE);
  await page.route(`**/api/v1/sessions/${id}`, (route) =>
    route.fulfill({ status: 503, json: { error: "the index is busy, try again" } }),
  );
  await page.goto(`/sessions/${id}`);
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("Couldn't read the session store.");
  await expect(alert.getByRole("button", { name: "Retry" })).toBeVisible();
  await expectAccessible(page, testInfo, "session-error");
});

test("joined mid-session: a note says which laps weren't seen (R8)", async ({ page }, testInfo) => {
  const { id, session } = await sessionTitled(page, JOINED);
  await page.goto(`/sessions/${id}`);
  await expect(page.locator("[data-slot=joined-note]")).toHaveText(
    `The engineer joined on lap ${session.joined_on_lap}. Laps before it weren't seen.`,
  );
  // Fuel use is off in this race: no fuel figures.
  await expect(tile(page, "Fuel used")).toContainText("Fuel off");
  await expect(page.locator("thead").getByRole("columnheader", { name: "Fuel used" })).toHaveCount(0);
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "session-joined");
  await expectAccessible(page, testInfo, "session-joined");
});

test("the table is a table: a caption and header cells (AC7)", async ({ page }) => {
  const { id } = await sessionTitled(page, PIT_STOP);
  await page.goto(`/sessions/${id}`);
  const table = page.getByRole("table");
  await expect(table.locator("caption")).toContainText("Laps");
  await expect(table.getByRole("columnheader")).not.toHaveCount(0);
  // The header sticks under the app's header as the rows scroll.
  expect(await table.locator("thead").evaluate((el) => getComputedStyle(el).position)).toBe("sticky");
});

test("Copy link copies the session's address (R9)", async ({ page, context, baseURL }) => {
  const { id } = await sessionTitled(page, PIT_STOP);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(`/sessions/${id}?pick=2,4`);
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Link copied." })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${baseURL}/sessions/${id}`);
});
