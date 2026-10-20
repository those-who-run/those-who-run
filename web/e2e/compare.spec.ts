// Lap compare (#299 AC1 to AC6) over the real pit wall and a replayed store, at each
// of the three viewports, with axe on every state it draws. The compare store
// (./global-setup.ts) has the Gilles Villeneuve race and two Suzuka East Course
// races: the pit stop, and the no-stop session, missing lap 6's file.
import type { Locator, Page } from "@playwright/test";

import { gear, lapTime, pedalPct, traceTime, whole } from "../src/lib/format";
import { expectAccessible } from "./a11y";
import { MISSING_LAP } from "./global-setup";
import { apiSessions, expect, expectNoHorizontalScroll, screenshot, storeUrl, test } from "./pitwall";

// Every page and API call here goes to the compare store's pit wall.
test.use({
  baseURL: async ({}, use) => {
    await use(storeUrl("compare"));
  },
});

const RACE = "Circuit Gilles Villeneuve · 12-lap race";
const SUZUKA = "Suzuka Circuit East Course · 6-lap race";

interface LapRow {
  lap: number;
  time_ms: number | null;
  best: boolean;
}

interface Trace {
  t: number[];
  speed_kph: number[];
  throttle_pct: number[];
  brake_pct: number[];
  gear: number[];
  rpm: number[];
}

/** A session's id by its title; the first of several with it. */
async function sessionId(page: Page, title: string): Promise<string> {
  const s = (await apiSessions(page)).find((x) => x.title === title);
  expect(s, `a session titled ${title}`).toBeDefined();
  return s!.session_id;
}

/** The no-stop session, which the setup deleted a lap file from. */
function missingLapSession(): string {
  const [id, lap] = (process.env.E2E_MISSING_LAP ?? "").split("/");
  expect(Number(lap)).toBe(MISSING_LAP);
  return id!;
}

async function laps(page: Page, id: string): Promise<LapRow[]> {
  const resp = await page.request.get(`/api/v1/sessions/${id}/laps`);
  expect(resp.ok()).toBe(true);
  return (await resp.json()).laps;
}

async function trace(page: Page, id: string, lap: number, points: number): Promise<Trace> {
  const resp = await page.request.get(`/api/v1/sessions/${id}/laps/${lap}/trace?points=${points}`);
  expect(resp.ok()).toBe(true);
  return resp.json();
}

const charts = (page: Page): Locator => page.locator("[data-slot=charts]");
const chart = (page: Page, channel: string): Locator =>
  page.locator(`figure[data-channel=${channel}] [data-slot=chart]`);
const readout = (page: Page): Locator => page.locator("[data-slot=readout]");
/** The track map's target (#350): the canvases, focusable as one slider. */
const trackMap = (page: Page): Locator => page.locator("[data-slot=map]");

/** Lap A's dot on the map, in CSS pixels from the map's top left; null with none. */
async function mapDot(page: Page): Promise<{ x: number; y: number } | null> {
  const dot = await trackMap(page).getAttribute("data-dot-a");
  if (!dot) {
    return null;
  }
  const [x, y] = dot.split(",").map(Number);
  return { x: x!, y: y! };
}

/** Waits for every shown chart to have drawn. */
async function chartsDrawn(page: Page, count = 5): Promise<void> {
  await expect(charts(page).locator("figure")).toHaveCount(count);
  await expect(charts(page).locator("[data-slot=chart] canvas")).toHaveCount(count);
}

/** The cursor time and each lap's sample index the readout shows. */
async function readoutState(page: Page) {
  const x = await readout(page).locator("th[data-x]").getAttribute("data-x");
  const a = await readout(page).locator("tr[data-lap=a]").getAttribute("data-index");
  const b = await readout(page).locator("tr[data-lap=b]").getAttribute("data-index");
  return { x: x === null ? null : Number(x), a: a === null ? null : Number(a), b: b === null ? null : Number(b) };
}

/** Each chart's cursor line, in page pixels from the left. */
async function cursorLefts(page: Page): Promise<number[]> {
  return charts(page)
    .locator(".u-cursor-x")
    .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().left)));
}

function nearest(xs: number[], x: number): number {
  let best = 0;
  xs.forEach((v, i) => {
    if (Math.abs(v - x) < Math.abs(xs[best]! - x)) {
      best = i;
    }
  });
  return best;
}

/** The readout's row for a lap matches the trace at the index nearest the cursor. */
async function expectRowMatches(page: Page, side: "a" | "b", t: Trace, x: number, index: number): Promise<void> {
  expect(index).toBe(nearest(t.t, x));
  const row = readout(page).locator(`tr[data-lap=${side}]`);
  await expect(row.locator("td[data-channel=speed]")).toHaveText(whole(t.speed_kph[index]));
  await expect(row.locator("td[data-channel=throttle]")).toHaveText(pedalPct(t.throttle_pct[index]));
  await expect(row.locator("td[data-channel=brake]")).toHaveText(pedalPct(t.brake_pct[index]));
  await expect(row.locator("td[data-channel=gear]")).toHaveText(gear(t.gear[index]));
  await expect(row.locator("td[data-channel=rpm]")).toHaveText(whole(t.rpm[index]));
}

/** A one-finger drag through Chromium's input pipeline, so the browser decides
 * whether it scrolls, as it would for a real finger. */
async function touchDrag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }): Promise<void> {
  const cdp = await page.context().newCDPSession(page);
  const steps = 12;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [from] });
  for (let i = 1; i <= steps; i++) {
    const p = { x: from.x + ((to.x - from.x) * i) / steps, y: from.y + ((to.y - from.y) * i) / steps };
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [p] });
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await cdp.detach();
}

test.beforeEach(async ({ page }) => {
  // A fresh viewer: no hidden channels, and the sideways hint not yet seen.
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("twr-e2e-kept")) {
      localStorage.clear();
    }
  });
});

test("opens on the best lap against the next fastest, with five charts (AC1, AC6)", async ({ page }, testInfo) => {
  const id = await sessionId(page, RACE);
  const rows = await laps(page, id);
  const timed = rows.filter((l) => l.time_ms).sort((x, y) => x.time_ms! - y.time_ms!);
  const best = rows.find((l) => l.best)!;
  const next = timed.find((l) => l.lap !== best.lap)!;

  await page.goto(`/sessions/${id}/compare`);
  await expect(page.getByRole("heading", { name: "Lap compare" })).toBeVisible();
  await expect(page.locator("[data-picker=a]")).toContainText(`Lap ${best.lap}`);
  await expect(page.locator("[data-picker=b]")).toContainText(`Lap ${next.lap}`);
  const summary = page.locator("[data-slot=summary]");
  await expect(summary).toContainText(lapTime(best.time_ms!));
  await expect(summary).toContainText(lapTime(next.time_ms!));
  await expect(summary).toContainText(`A faster by ${lapTime(next.time_ms! - best.time_ms!)}`);
  await chartsDrawn(page);
  await expect(page.getByRole("link", { name: "Back to the session" })).toHaveAttribute("href", `/sessions/${id}`);
  // The track map (#350 AC5): drawn at every width.
  await expect(trackMap(page)).toBeVisible();

  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "compare");
  await expectAccessible(page, testInfo, "compare");
});

test("a pointer on one chart moves the cursor on all five, and the readout reads both laps there (AC2)", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a mouse pointer: the desktop project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  const points = Number(await charts(page).getAttribute("data-points"));
  expect(points).toBeGreaterThan(0);
  expect(points).toBeLessThanOrEqual(1500);
  const [a, b] = await Promise.all([trace(page, id, 1, points), trace(page, id, 2, points)]);

  const box = (await chart(page, "speed").locator(".u-over").boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2);
  await expect.poll(async () => (await readoutState(page)).x).not.toBeNull();
  const lefts = await cursorLefts(page);
  expect(lefts).toHaveLength(5);
  expect(new Set(lefts).size, `cursor lines at ${lefts.join(", ")}`).toBe(1);

  const state = await readoutState(page);
  await expect(readout(page).locator("th[data-x]")).toContainText(traceTime(state.x));
  await expectRowMatches(page, "a", a, state.x!, state.a!);
  await expectRowMatches(page, "b", b, state.x!, state.b!);

  // Leaving the chart keeps the readout: nothing is only under the pointer.
  await page.mouse.move(box.x + box.width / 2, box.y - 200);
  expect((await readoutState(page)).x).toBe(state.x);
});

test("a horizontal touch drag scrubs; a vertical one scrolls the page (AC3)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "touch at 390 × 844: the phone project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  // The track map sits above the charts on a phone (#350 R6): bring the throttle
  // chart on screen first, then check the scrub leaves the page where it is.
  await chart(page, "throttle").scrollIntoViewIfNeeded();
  const scrollAtStart = await page.evaluate(() => window.scrollY);
  const box = (await chart(page, "throttle").locator(".u-over").boundingBox())!;
  const y = box.y + box.height / 2;

  await touchDrag(page, { x: box.x + 20, y }, { x: box.x + box.width * 0.7, y });
  const scrubbed = await readoutState(page);
  expect(scrubbed.x).not.toBeNull();
  const lefts = await cursorLefts(page);
  expect(new Set(lefts).size, `cursor lines at ${lefts.join(", ")}`).toBe(1);
  expect(lefts[0]!).toBeGreaterThan(box.x + box.width * 0.6);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollAtStart);

  const scrollBefore = await page.evaluate(() => window.scrollY);
  const speed = (await chart(page, "speed").locator(".u-over").boundingBox())!;
  const x = speed.x + speed.width / 2;
  await touchDrag(page, { x, y: speed.y + speed.height - 5 }, { x, y: speed.y - 150 });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(scrollBefore + 50);
  // The vertical drag moved the page, not the cursor's time much.
  const after = await readoutState(page);
  expect(Math.abs(after.x! - scrubbed.x!)).toBeLessThan(5);
  // The readout stays pinned under the header while the charts scroll. How far a
  // touch drag scrolls varies run to run, so scroll past the readout's sticky point
  // first, then measure it against the header itself once the page has settled.
  await page.evaluate(() => window.scrollBy(0, 400));
  const header = page.locator("[data-slot=header]");
  await expect
    .poll(async () => {
      const h = (await header.boundingBox())!;
      const r = (await readout(page).boundingBox())!;
      return Math.abs(r.y - (h.y + h.height));
    })
    .toBeLessThanOrEqual(1);
});

/** Points at the middle of a chart, so the readout has values. */
async function pointAt(page: Page, channel: string, fx = 0.5): Promise<void> {
  const over = chart(page, channel).locator(".u-over");
  const box = (await over.boundingBox())!;
  await over.click({ position: { x: box.width * fx, y: box.height / 2 } });
}

test("lap B from another session at the track: both laps draw (AC4)", async ({ page }, testInfo) => {
  const noStop = missingLapSession();
  const pitStop = (await apiSessions(page)).find((s) => s.title === SUZUKA && s.session_id !== noStop)!.session_id;
  const otherLaps = await laps(page, noStop);
  const otherBest = otherLaps.find((l) => l.best)!.lap;

  await page.goto(`/sessions/${pitStop}/compare`);
  await chartsDrawn(page);
  await page.locator("[data-picker=b]").click();
  const sheet = page.getByRole("dialog", { name: "Lap B" });
  await expect(sheet).toBeVisible();
  const others = sheet.getByRole("list", { name: "Sessions at this track" });
  await expect(others.locator(":scope > li")).toHaveCount(1);
  await others.getByRole("button").first().click();
  await expect(others.locator(`button[data-lap="${otherBest}"]`)).toBeVisible();
  await sheet.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await expectAccessible(page, testInfo, "compare-lap-b-sheet");
  await others.locator(`button[data-lap="${otherBest}"]`).click();
  await expect(sheet).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`[?&]b_session=${noStop}`));
  await expect(page).toHaveURL(new RegExp(`[?&]b=${otherBest}(&|$)`));
  await expect(page.locator("[data-picker=b]")).toContainText(`Lap ${otherBest}`);

  await chartsDrawn(page);
  await expect(page.locator("[data-missing]")).toHaveCount(0);
  await pointAt(page, "speed");
  for (const side of ["a", "b"]) {
    await expect(readout(page).locator(`tr[data-lap=${side}] td[data-channel=speed]`)).toHaveText(/^\d/);
  }
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "compare-other-session");
});

test("one lap in the session: lap B is lap A, and its picker asks for another (R9)", async ({ page }, testInfo) => {
  const id = await sessionId(page, RACE);
  const rows = await laps(page, id);
  // The race, as if it had only its best lap.
  await page.route(`**/api/v1/sessions/${id}/laps`, (route) =>
    route.fulfill({ json: { session_id: id, laps: rows.filter((l) => l.best) } }),
  );
  const best = rows.find((l) => l.best)!.lap;
  await page.goto(`/sessions/${id}/compare`);
  await expect(page.getByText("Pick another lap, or one from another session.")).toBeVisible();
  const sheet = page.getByRole("dialog", { name: "Lap B" });
  await expect(sheet).toBeVisible();
  await sheet.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await expectAccessible(page, testInfo, "compare-one-lap");
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(page.locator("[data-picker=a]")).toContainText(`Lap ${best}`);
  await expect(page.locator("[data-picker=b]")).toContainText(`Lap ${best}`);
});

test("a missing lap file says so, and the other lap still draws (AC5)", async ({ page }, testInfo) => {
  const missing = missingLapSession();
  await page.goto(`/sessions/${missing}/compare?a=1&b=${MISSING_LAP}`);
  await expect(page.locator("[data-missing=b]")).toContainText(
    `Lap ${MISSING_LAP}: A lap file is missing or still being written.`,
  );
  await expect(page.locator("[data-missing=a]")).toHaveCount(0);
  await chartsDrawn(page);
  await pointAt(page, "speed", 0.3);
  await expect(readout(page).locator("tr[data-lap=a] td[data-channel=speed]")).toHaveText(/^\d/);
  await expect(readout(page).locator("tr[data-lap=b] td[data-channel=speed]")).toHaveText("—");
  await expectAccessible(page, testInfo, "compare-missing-lap");
});

test("a bad ?a or ?b falls back to the defaults, with a notice (R9)", async ({ page }) => {
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare?a=99&b=x`);
  await expect(page.getByText("There's no lap 99 in this session, so lap A is the best lap.")).toBeVisible();
  await expect(page.getByText("There's no lap x in this session, so lap B is the next fastest.")).toBeVisible();
  await expect(page.locator("[data-picker=a]")).toContainText("Lap 1");
  await expect(page.locator("[data-picker=b]")).toContainText("Lap 2");
});

test("picking lap A puts it in the URL", async ({ page }) => {
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await page.locator("[data-picker=a]").click();
  const sheet = page.getByRole("dialog", { name: "Lap A" });
  await sheet.locator('button[data-lap="2"]').click();
  await expect(sheet).toBeHidden();
  await expect(page).toHaveURL(/[?&]a=2/);
  await expect(page.locator("[data-picker=a]")).toContainText("Lap 2");
});

test("hiding RPM survives a reload (AC6)", async ({ page }, testInfo) => {
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  const rpm = page.getByRole("group", { name: "Channels" }).getByRole("button", { name: "RPM" });
  await expect(rpm).toHaveAttribute("aria-pressed", "true");
  await rpm.click();
  await expect(rpm).toHaveAttribute("aria-pressed", "false");
  await chartsDrawn(page, 4);
  await page.evaluate(() => sessionStorage.setItem("twr-e2e-kept", "1"));
  await page.reload();
  await chartsDrawn(page, 4);
  await expect(page.locator("figure[data-channel=rpm]")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "Channels" }).getByRole("button", { name: "RPM" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "compare-no-rpm");
});

test("a drag zooms every chart, and Reset zoom restores them (R5)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a mouse drag: the desktop project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  const ranges = () =>
    charts(page)
      .locator("[data-slot=chart]")
      .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.xRange));
  const whole = await ranges();
  expect(new Set(whole).size).toBe(1);

  const over = chart(page, "speed").locator(".u-over");
  const box = (await over.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  const reset = page.getByRole("button", { name: "Reset zoom" });
  await expect(reset).toBeVisible();
  await expect(page).toHaveURL(/[?&]zoom=\d+\.\d\d-\d+\.\d\d/);
  const zoomed = await ranges();
  expect(new Set(zoomed).size, `x ranges ${zoomed.join(", ")}`).toBe(1);
  expect(zoomed[0]).not.toBe(whole[0]);

  // The zoom is in the URL: a reload keeps it.
  await page.reload();
  await chartsDrawn(page);
  await expect(reset).toBeVisible();

  await reset.click();
  await expect(reset).toBeHidden();
  await expect(page).not.toHaveURL(/zoom=/);
  expect(await ranges()).toEqual(whole);
});

test("a pinch zooms every chart (R5)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "touch: the phone project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  await chart(page, "speed").scrollIntoViewIfNeeded(); // below the track map (#350)
  const box = (await chart(page, "speed").locator(".u-over").boundingBox())!;
  const y = box.y + box.height / 2;
  const mid = box.x + box.width / 2;
  const cdp = await page.context().newCDPSession(page);
  const fingers = (gap: number) => [
    { x: mid - gap, y, id: 0 },
    { x: mid + gap, y, id: 1 },
  ];
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: fingers(20) });
  for (let gap = 30; gap <= 120; gap += 10) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: fingers(gap) });
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await cdp.detach();
  await expect(page.getByRole("button", { name: "Reset zoom" })).toBeVisible();
  const ranges = await charts(page)
    .locator("[data-slot=chart]")
    .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.xRange));
  expect(new Set(ranges).size, `x ranges ${ranges.join(", ")}`).toBe(1);
  const [lo, hi] = ranges[0]!.split("-").map(Number);
  expect(hi! - lo!).toBeLessThan(40); // about a sixth of a 97 s lap
});

test("a double tap resets the zoom (R5)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "touch: the phone project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare?zoom=10.00-40.00`);
  await chartsDrawn(page);
  const reset = page.getByRole("button", { name: "Reset zoom" });
  await expect(reset).toBeVisible();
  await chart(page, "speed").scrollIntoViewIfNeeded(); // below the track map (#350)
  const box = (await chart(page, "speed").locator(".u-over").boundingBox())!;
  const at ={ x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.touchscreen.tap(at.x, at.y);
  await page.touchscreen.tap(at.x, at.y);
  await expect(reset).toBeHidden();
  await expect(page).not.toHaveURL(/zoom=/);
});

test("a phone in portrait hints at turning sideways, once (R10)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "phone", "a phone in portrait");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await expect(page.getByText("Turn sideways for a wider view.")).toBeVisible();
  await page.evaluate(() => sessionStorage.setItem("twr-e2e-kept", "1"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Lap compare" })).toBeVisible();
  await expect(page.getByText("Turn sideways for a wider view.")).toHaveCount(0);
});

test("the session page's pick bar opens compare on its laps, and Back keeps the picks", async ({ page }) => {
  const noStop = missingLapSession();
  const id = (await apiSessions(page)).find((s) => s.title === SUZUKA && s.session_id !== noStop)!.session_id;
  const bar = page.getByRole("region", { name: "Compare" });
  const pick = (lap: number) => page.getByRole("checkbox", { name: `Pick lap ${lap} to compare` });

  // None picked: the best lap and the next fastest, as compare's own defaults.
  await page.goto(`/sessions/${id}`);
  await bar.getByRole("link", { name: "Compare best and next fastest" }).click();
  await expect(page).toHaveURL(`/sessions/${id}/compare?a=5&b=6`);
  await expect(page.locator("[data-picker=a]")).toContainText("Lap 5");
  await expect(page.locator("[data-picker=b]")).toContainText("Lap 6");
  await chartsDrawn(page);
  await page.goBack();
  await expect(page).toHaveURL(`/sessions/${id}`);

  // Two picked: those, as A and B.
  await pick(2).check();
  await pick(4).check();
  await bar.getByRole("link", { name: "Compare L2 and L4" }).click();
  await expect(page).toHaveURL(`/sessions/${id}/compare?a=2&b=4`);
  await expect(page.locator("[data-picker=a]")).toContainText("Lap 2");
  await expect(page.locator("[data-picker=b]")).toContainText("Lap 4");
  await chartsDrawn(page);

  // The browser's Back keeps the picks.
  await page.goBack();
  await expect(page).toHaveURL(`/sessions/${id}?pick=2%2C4`);
  await expect(pick(2)).toBeChecked();
  await expect(pick(4)).toBeChecked();

  // So does compare's own "Back to the session", even after a pick on compare.
  await bar.getByRole("link", { name: "Compare L2 and L4" }).click();
  await page.locator("[data-picker=a]").click();
  await page.getByRole("dialog", { name: "Lap A" }).locator('button[data-lap="1"]').click();
  await expect(page).toHaveURL(/[?&]a=1/);
  await page.getByRole("link", { name: "Back to the session" }).click();
  await expect(page).toHaveURL(`/sessions/${id}?pick=2%2C4`);
  await expect(pick(2)).toBeChecked();
  await expect(pick(4)).toBeChecked();
});

/** Scrubs the throttle chart to `fx` of its width: a finger on a touch screen, the
 * mouse on a desktop. */
async function scrubThrottle(page: Page, touch: boolean, fx: number): Promise<void> {
  await chart(page, "throttle").scrollIntoViewIfNeeded();
  const box = (await chart(page, "throttle").locator(".u-over").boundingBox())!;
  const y = box.y + box.height / 2;
  if (touch) {
    await touchDrag(page, { x: box.x + 10, y }, { x: box.x + box.width * fx, y });
  } else {
    await page.mouse.move(box.x + box.width * fx, y);
  }
}

test("scrubbing the throttle chart moves the map's dot; tapping the map moves the readout (#350 AC3)", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name === "ipad", "touch on the phone, a mouse on the desktop");
  const touch = testInfo.project.name === "phone";
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  await expect(trackMap(page)).toBeVisible();
  expect(await mapDot(page)).toBeNull();

  // The charts lead: the dot follows the scrub, at the sample the readout shows.
  await scrubThrottle(page, touch, 0.3);
  await expect.poll(() => mapDot(page)).not.toBeNull();
  const first = { dot: (await mapDot(page))!, state: await readoutState(page) };
  await expect(trackMap(page)).toHaveAttribute("data-cursor-a", String(first.state.a));
  await scrubThrottle(page, touch, 0.75);
  await expect.poll(async () => (await readoutState(page)).a).not.toBe(first.state.a);
  const second = await readoutState(page);
  await expect(trackMap(page)).toHaveAttribute("data-cursor-a", String(second.a));
  expect(await mapDot(page)).not.toEqual(first.dot);

  // The map leads: a tap where the dot was moves the cursor back there.
  await trackMap(page).scrollIntoViewIfNeeded();
  const box = (await trackMap(page).boundingBox())!;
  const at = { x: box.x + first.dot.x, y: box.y + first.dot.y };
  if (touch) {
    await page.touchscreen.tap(at.x, at.y);
  } else {
    await page.mouse.click(at.x, at.y);
  }
  await expect.poll(async () => (await readoutState(page)).a).toBe(first.state.a);
  await expect(trackMap(page)).toHaveAttribute("data-cursor-a", String(first.state.a));
  const a = await trace(page, id, 1, Number(await charts(page).getAttribute("data-points")));
  const back = await readoutState(page);
  expect(back.x).toBe(a.t[first.state.a!]);
  await expectRowMatches(page, "a", a, back.x!, back.a!);
  await expectAccessible(page, testInfo, "compare-map-cursor");
});

test("the map takes focus, and the arrow keys step the cursor (#350 R4)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a keyboard: the desktop project");
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  await trackMap(page).focus();
  await page.keyboard.press("Home");
  await expect.poll(async () => (await readoutState(page)).a).toBe(0);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await readoutState(page)).a).toBe(2);
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await readoutState(page)).a).toBe(1);
  await expect(trackMap(page)).toHaveAttribute("aria-valuetext", /s into lap 1$/);
});

test("the map sits above the charts on a phone and beside them, pinned, on a desktop (#350 R6)", async ({
  page,
}, testInfo) => {
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  const viewport = page.viewportSize()!;
  const map = (await trackMap(page).boundingBox())!;
  const first = (await charts(page).boundingBox())!;
  expect(map.height).toBeLessThanOrEqual(viewport.height * 0.4 + 1);
  expect(map.width).toBeLessThanOrEqual(viewport.width);
  if (testInfo.project.name === "desktop") {
    expect(map.x).toBeGreaterThanOrEqual(first.x + first.width);
    await page.evaluate(() => window.scrollBy(0, 800));
    await expect
      .poll(async () => {
        const m = (await trackMap(page).boundingBox())!;
        return m.y >= 0 && m.y + m.height <= viewport.height;
      })
      .toBe(true);
  } else {
    expect(map.y + map.height).toBeLessThanOrEqual(first.y);
  }
  await expectNoHorizontalScroll(page);
});

test("the map's colours: pedals by default, speed remembered after a reload (#350 R2)", async ({ page }, testInfo) => {
  const id = await sessionId(page, RACE);
  await page.goto(`/sessions/${id}/compare`);
  await chartsDrawn(page);
  const figure = page.locator("[data-slot=track-map]");
  const modes = page.getByRole("group", { name: "Map colours" });
  await expect(figure).toHaveAttribute("data-mode", "pedals");
  await expect(page.getByRole("list", { name: "Line colours" })).toContainText(["Brake"]);
  await expect(figure.locator("figcaption")).toHaveText(
    /^Lap 1 at Circuit Gilles Villeneuve: on the brake for \d+% of the lap, full throttle for \d+%$/,
  );
  await modes.getByRole("button", { name: "Speed" }).click();
  await expect(figure).toHaveAttribute("data-mode", "speed");
  await expect(figure.locator("[data-slot=map-legend]")).toContainText("km/h");
  await page.evaluate(() => sessionStorage.setItem("twr-e2e-kept", "1"));
  await page.reload();
  await chartsDrawn(page);
  await expect(figure).toHaveAttribute("data-mode", "speed");
  await expect(modes.getByRole("button", { name: "Speed" })).toHaveAttribute("aria-pressed", "true");
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "compare-map-speed");
  await expectAccessible(page, testInfo, "compare-map-speed");
});
