// The session list (#297) over the real pit wall and replayed stores, at each of the
// three viewports, each page checked by axe (ADR 0004 point 11). The main store is
// the time trial, the race and the pit stop; storeUrl() reaches the stores with a
// session of no full lap, with none at all, and with an index that can't be read.
// The stub engineer (./engineer.ts) reports the live session.
import type { Page } from "@playwright/test";

import { lapTime, raceTime } from "../src/lib/format";
import { expectAccessible } from "./a11y";
import { setEngineer } from "./engineer";
import { STORE_SESSIONS } from "./global-setup";
import {
  apiSessions,
  expect,
  expectNoHorizontalScroll,
  screenshot,
  sessionLink,
  storeUrl,
  test,
} from "./pitwall";
import { LIVE_SESSION_ID } from "./store";

interface ApiSession {
  session_id: string;
  title: string;
  result: string;
  kind: string;
  track: { name: string };
  finished: boolean;
  total_time_ms: number | null;
  best_lap_ms: number | null;
  laps_completed: number;
}

async function sessionsAt(page: Page, base = ""): Promise<ApiSession[]> {
  const resp = await page.request.get(`${base}/api/v1/sessions`);
  expect(resp.ok()).toBe(true);
  return (await resp.json()).sessions;
}

const card = (page: Page, id: string) =>
  page.locator("[data-slot=session-card]").filter({ has: page.locator(`a[href="/sessions/${id}"]`) });

const list = (page: Page) => page.getByRole("list", { name: "Sessions" });

/** Every visible button and link on the page is at least 44 px tall. */
async function expectTargets(page: Page): Promise<void> {
  const small = await page
    .getByRole("main")
    .evaluate((main) =>
      Array.from(main.querySelectorAll<HTMLElement>("button, [data-card-link]"))
        .filter((e) => e.offsetParent !== null)
        .map((e) => {
          // A card's link covers the whole card (its ::after); the card is the target.
          const box = (e.closest("[data-slot=session-card]") ?? e).getBoundingClientRect();
          return { name: e.textContent?.trim() || e.getAttribute("aria-label"), h: box.height };
        })
        .filter((b) => b.h < 44),
    );
  expect(small, "targets under 44 px").toEqual([]);
}

test("lists the sessions under their day, each saying how it went (AC1, AC5)", async ({ page }, testInfo) => {
  const sessions = await sessionsAt(page);
  expect(sessions).toHaveLength(STORE_SESSIONS);
  await page.goto("/");
  await expect(list(page).getByRole("link")).toHaveCount(sessions.length);

  // Replayed now, so all of them are today's.
  const today = page.getByRole("heading", { level: 3, name: /^Today/ });
  await expect(today).toHaveText(`Today${sessions.length} sessions`);
  // The summary line, with no filter set.
  await expect(page.getByRole("main").getByRole("paragraph").filter({ hasText: new RegExp(`^${sessions.length} sessions$`) })).toBeVisible();

  for (const s of sessions) {
    const c = card(page, s.session_id);
    await expect(c).toBeVisible();
    await expect(sessionLink(page, s.session_id)).toHaveAccessibleName(s.track.name);
    if (s.session_id === LIVE_SESSION_ID) {
      // The open copy of the pit stop (./store.ts): still running, with 4 laps or 5
      // (session.spec.ts adds one as this runs).
      await expect(c).toContainText(/Running, [45] laps/);
    } else if (s.kind === "timed_field") {
      // The race the engineer joined on lap 7 (#298 R8).
      await expect(c).toContainText("1 lap, P1 of 17");
    } else if (s.finished) {
      // The race: its position and race time.
      await expect(c).toContainText("Position 1 of 2");
      await expect(c).toContainText(`in ${raceTime(s.total_time_ms)}`);
    } else if (s.kind === "solo_timed") {
      // The time trial (standing in for the drift session): the best lap and the laps.
      await expect(c).toContainText(`Best ${lapTime(s.best_lap_ms)}`);
      await expect(c).toContainText(`${s.laps_completed} laps`);
    } else {
      await expect(c).toContainText("Retired on lap 3 of 12");
    }
  }

  // One column on a phone, two on an iPad, one row-shaped column at most 48 rem on a desktop.
  const width = page.viewportSize()!.width;
  const boxes = await list(page).locator("[data-slot=session-card]").evaluateAll((cards) =>
    cards.map((c) => c.getBoundingClientRect()).map((b) => ({ x: b.x, y: b.y, w: b.width })),
  );
  if (width < 768) {
    expect(new Set(boxes.map((b) => b.x)).size).toBe(1);
  } else if (width < 1280) {
    expect(boxes[0]!.y).toBe(boxes[1]!.y);
  } else {
    expect(new Set(boxes.map((b) => b.x)).size).toBe(1);
    expect(boxes[0]!.w).toBeLessThanOrEqual(48 * 16);
  }

  await expectTargets(page);
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "sessions");
  await expectAccessible(page, testInfo, "sessions");
});

test("hides a session with no full lap until asked, and keeps ?all=1 (AC2)", async ({ page }, testInfo) => {
  const base = storeUrl("short");
  const sessions = await sessionsAt(page, base);
  const short = sessions.find((s) => s.laps_completed === 0)!;
  const full = sessions.find((s) => s.laps_completed > 0)!;
  expect(short).toBeDefined();

  await page.goto(`${base}/`);
  await expect(sessionLink(page, full.session_id)).toBeVisible();
  await expect(sessionLink(page, short.session_id)).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 3, name: /^Today/ })).toHaveText("Today2 sessions");
  const show = page.getByRole("button", { name: "1 session with no full lap Show" });
  await expect(show).toBeVisible();
  await screenshot(page, testInfo, "sessions-short-hidden");
  await expectAccessible(page, testInfo, "sessions-short-hidden");

  await show.click();
  await expect(page).toHaveURL(/[?&]all=1$/);
  await expect(card(page, short.session_id)).toContainText("No full lap");
  await expect(page.getByRole("button", { name: "No full lap" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(page).toHaveURL(/[?&]all=1$/);
  await expect(sessionLink(page, short.session_id)).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expectAccessible(page, testInfo, "sessions-short-shown");

  // The toggle hides them again.
  await page.getByRole("button", { name: "No full lap" }).click();
  await expect(sessionLink(page, short.session_id)).toHaveCount(0);
  await expect(page).not.toHaveURL(/all=1/);
});

test("filters by track in the URL; Back removes it and Clear all resets (AC3)", async ({ page }, testInfo) => {
  const sessions = await apiSessions(page);
  const target = sessions.find((s) => s.track.name === "Suzuka Circuit East Course")!;
  // The pit stop, and its open copy (./store.ts).
  const matching = sessions.filter((s) => s.track.name === target.track.name).length;
  await page.goto("/");
  await expect(list(page).getByRole("link")).toHaveCount(sessions.length);

  await page.getByRole("group", { name: "Filters" }).getByRole("button", { name: "Track" }).click();
  const picker = page.getByRole("dialog", { name: "Track" });
  await expect(picker).toBeVisible();
  // The options come with their counts.
  const option = picker.getByRole("button", { name: `${target.track.name} ${matching}` });
  await expect(option).toBeVisible();
  await picker.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await expectAccessible(page, testInfo, "sessions-filter-open");
  await screenshot(page, testInfo, "sessions-filter-open");
  await option.click();
  await expect(picker).toBeHidden();

  await expect(page).toHaveURL(/\?track=Suzuka\+Circuit\+East\+Course$/);
  await expect(list(page).getByRole("link")).toHaveCount(matching);
  await expect(sessionLink(page, target.session_id)).toBeVisible();
  await expect(page.getByText(`${matching} of ${sessions.length} sessions`)).toBeVisible();
  const active = page.getByRole("list", { name: "Active filters" });
  await expect(active.getByRole("button", { name: `Remove filter: ${target.track.name}` })).toBeVisible();
  await expectTargets(page);
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "sessions-filtered");

  // Back takes the filter off; Forward puts it back.
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(list(page).getByRole("link")).toHaveCount(sessions.length);
  await page.goForward();
  await expect(list(page).getByRole("link")).toHaveCount(matching);

  await active.getByRole("button", { name: "Clear all" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(list(page).getByRole("link")).toHaveCount(sessions.length);
  await expect(page.getByRole("list", { name: "Active filters" })).toHaveCount(0);
});

test("a filter that matches nothing says so, with Clear filters (R7)", async ({ page }, testInfo) => {
  await page.goto("/?track=Nowhere&from=not-a-day");
  await expect(page.getByRole("heading", { name: "No sessions match these filters" })).toBeVisible();
  // A bad date is dropped, not an error: only the track is active.
  await expect(page.getByRole("list", { name: "Active filters" }).getByRole("button")).toHaveCount(2);
  await expectAccessible(page, testInfo, "sessions-no-match");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(list(page)).toBeVisible();
});

test("pins the live session and follows its laps without a reload (AC4)", async ({ page }, testInfo) => {
  let asks = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/v1/sessions") {
      asks += 1;
    }
  });
  await setEngineer(page, "driving-unsure");
  await page.goto("/");
  const live = page.getByRole("region", { name: "On track" });
  await expect(live).toBeVisible();
  await expect(live).toContainText("Live");
  await expect(live).toContainText("Lap 2 of 6");
  await expect(live).toContainText("Position 3 of 16");
  // Pinned above the days.
  const above = await live.evaluate(
    (el) => !!(el.compareDocumentPosition(document.querySelector("[aria-label=Sessions]")!) & 4),
  );
  expect(above).toBe(true);
  await page.evaluate(() => ((window as unknown as { marker: number }).marker = 1));
  await screenshot(page, testInfo, "sessions-live");
  await expectAccessible(page, testInfo, "sessions-live");

  await setEngineer(page, "driving");
  await expect(live).toContainText("Lap 3 of 6", { timeout: 6_000 });
  expect(await page.evaluate(() => (window as unknown as { marker?: number }).marker)).toBe(1);
  // The list is asked again every 5 s while a session is live.
  await expect.poll(() => asks, { timeout: 7_000 }).toBeGreaterThan(1);

  // The session ends: the pinned card goes.
  await setEngineer(page, "idle");
  await expect(live).toBeHidden({ timeout: 7_000 });
});

test("with no sessions, says how to get one (AC6)", async ({ page }, testInfo) => {
  await page.goto(`${storeUrl("empty")}/`);
  await expect(page.getByRole("heading", { name: "No sessions yet" })).toBeVisible();
  await expect(page.getByText("Drive a lap with the engineer running and it appears here.")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "sessions-empty");
  await expectAccessible(page, testInfo, "sessions-empty");
});

test("an unreadable index shows the error, with Retry (AC6)", async ({ page }, testInfo) => {
  await page.goto(`${storeUrl("broken")}/`);
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("Couldn't read the session store.", { timeout: 10_000 });
  await alert.getByText("Details").click();
  await expect(alert).toContainText("internal server error");
  const retry = alert.getByRole("button", { name: "Retry" });
  await expect(retry).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "sessions-error");
  await expectAccessible(page, testInfo, "sessions-error");
  await retry.click();
  await expect(alert.getByRole("button", { name: /Retry/ })).toBeVisible();
});

test("a session's card opens its page (R2)", async ({ page }, testInfo) => {
  const [first] = await apiSessions(page);
  await page.goto("/");
  await sessionLink(page, first!.session_id).click();
  await expect(page).toHaveURL(`/sessions/${first!.session_id}`);
  // The session page names itself by its title; its heading is the track (#298).
  await expect(page).toHaveTitle(`${first!.title} · Pit wall`);
  await expectNoHorizontalScroll(page);
  await expectAccessible(page, testInfo, "session");
});

test("a results card's /?session=<id> lands on /sessions/<id>", async ({ page }) => {
  const [first] = await apiSessions(page);
  await page.goto(`/?session=${first!.session_id}`);
  await expect(page).toHaveURL(`/sessions/${first!.session_id}`);
  // The session page names itself by its title; its heading is the track (#298).
  await expect(page).toHaveTitle(`${first!.title} · Pit wall`);
});

test("an unknown path has a page of its own", async ({ page }, testInfo) => {
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Nothing here" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expectAccessible(page, testInfo, "not-found");
});
