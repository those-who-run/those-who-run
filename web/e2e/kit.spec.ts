// /_kit, the component kit's review page (#295 AC1 to AC5), at each of the three
// viewports. Its screenshots go in the CI artifact with the pages'.
import type { Page } from "@playwright/test";

import { expectAccessible } from "./a11y";
import { expect, expectNoHorizontalScroll, screenshot, test } from "./pitwall";

const SECTIONS = [
  "LapTime",
  "Gap",
  "Position",
  "KindBadge",
  "LapFlag",
  "StatTile",
  "SessionCard",
  "LiveBadge",
  "EmptyState",
  "ErrorState",
  "Unknown",
  "Lap table",
  "Primitives",
];

const WILLOW = "Willow Springs International Raceway: Big Willow";
const RX_VISION = "Mazda RX-VISION GT3 EVO '26";

/** The kit, loaded, with its fonts in and its skeletons past their 150 ms. */
async function openKit(page: Page): Promise<void> {
  await page.goto("/_kit");
  await expect(page.getByRole("heading", { name: "Component kit" })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const loading = page.locator("[data-slot=loading]");
  await expect(loading.first()).toHaveAttribute("data-shown", "true");
  await expect(loading.and(page.locator(":not([data-shown])"))).toHaveCount(0);
}

test("shows every component in every state, with no sideways scroll (AC1)", async ({ page }, testInfo) => {
  await openKit(page);
  for (const name of SECTIONS) {
    await expect(page.getByRole("region", { name, exact: true }), name).toBeVisible();
  }
  const states = (section: string) =>
    page.getByRole("region", { name: section, exact: true }).locator("[data-state-name]");
  await expect(states("LapTime")).toHaveText(
    ["normal", "best", "invalid", "sm", "md", "xl", "loading"].map((s) => new RegExp(`^${s}`)),
  );
  await expect(states("Gap")).toHaveCount(6);
  await expect(states("Position")).toHaveCount(6);
  const cards = page.getByRole("region", { name: "SessionCard", exact: true });
  for (const s of ["race finished", "retired", "timed", "time trial", "unknown track", "live", "paused", "loading"]) {
    await expect(cards.locator(`[data-state-name="${s}"]`), s).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "LapFlag" }).getByRole("button")).toHaveText([
    "Pit",
    "Out",
    "Partial",
    "Restart",
  ]);
  // Loading: a skeleton for each data component, shown once its 150 ms are up.
  for (const label of ["Loading lap time", "Loading gap", "Loading position", "Loading driving time", "Loading session"]) {
    await expect(page.getByRole("status", { name: label }), label).toBeVisible();
  }
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "kit");
});

test("axe finds nothing serious or critical (AC2)", async ({ page }, testInfo) => {
  await openKit(page);
  await expectAccessible(page, testInfo, "kit");
});

test("every button, explanation and card is at least 44 × 44 px (AC3)", async ({ page }) => {
  await openKit(page);
  const targets = page.locator(
    "button:visible, [role=combobox]:visible, summary:visible, [data-slot=session-card]:visible",
  );
  const count = await targets.count();
  expect(count).toBeGreaterThan(30);
  const small: string[] = [];
  for (let i = 0; i < count; i++) {
    const t = targets.nth(i);
    const box = await t.boundingBox();
    if (!box || box.width < 44 || box.height < 44) {
      const label = (await t.getAttribute("aria-label")) ?? (await t.innerText()).slice(0, 40);
      small.push(`${label}: ${box ? `${box.width.toFixed(1)} × ${box.height.toFixed(1)}` : "no box"}`);
    }
  }
  expect(small, "targets under 44 × 44 px").toEqual([]);
});

test("a long track and car fit; the title wraps to two lines, then ends in an ellipsis (AC4)", async ({ page }) => {
  await openKit(page);
  const viewport = page.viewportSize()!;
  const cards = page.getByRole("region", { name: "SessionCard", exact: true });

  // The full-width card: inside the viewport, its title at most two lines, named in full.
  const card = cards.locator('[data-state-name="race finished"] [data-slot=session-card]');
  const box = (await card.boundingBox())!;
  const column = (await cards.boundingBox())!;
  expect(box.width, "the card fills its column").toBeGreaterThanOrEqual(column.width - 1);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  await expect(card).toContainText(RX_VISION);
  const title = card.getByRole("link", { name: WILLOW, exact: true });
  await expect(title).toHaveAttribute("title", WILLOW);
  const lines = await title.evaluate((el) => {
    const s = getComputedStyle(el);
    return { clamp: s.webkitLineClamp, lines: el.getBoundingClientRect().height / parseFloat(s.lineHeight) };
  });
  expect(lines.clamp).toBe("2");
  expect(lines.lines).toBeLessThanOrEqual(2.01);

  // In a 16 rem column the name needs more than two lines: it is cut at two, with an
  // ellipsis, and the full name is still its title and accessible name.
  const narrow = cards.locator("[data-kit=narrow]");
  const cut = narrow.getByRole("link", { name: WILLOW, exact: true });
  await expect(cut).toHaveAttribute("title", WILLOW);
  const clipped = await cut.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      clamp: s.webkitLineClamp,
      overflow: s.overflow,
      shown: Math.round(el.clientHeight / parseFloat(s.lineHeight)),
      cut: el.scrollHeight > el.clientHeight,
    };
  });
  expect(clipped).toEqual({ clamp: "2", overflow: "hidden", shown: 2, cut: true });
  const narrowBox = (await narrow.boundingBox())!;
  expect(narrowBox.x + narrowBox.width).toBeLessThanOrEqual(viewport.width);
});

test("a lap flag explains itself by tap and by Enter, and closes with Escape (AC5)", async ({ page }, testInfo) => {
  await openKit(page);
  const pit = page.getByRole("region", { name: "LapFlag" }).getByRole("button", { name: "Pit" });
  const explanation = page.getByRole("dialog", { name: "Pit lap" });

  if (testInfo.project.use.hasTouch) {
    await pit.tap();
  } else {
    await pit.click();
  }
  await expect(explanation).toBeVisible();
  await expect(explanation).toContainText("Fuel went up during the lap");
  await page.keyboard.press("Escape");
  await expect(explanation).toBeHidden();

  await pit.focus();
  await page.keyboard.press("Enter");
  await expect(explanation).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(explanation).toBeHidden();
  await expect(pit).toBeFocused();
});

test("focus is visible: the focus ring on a keyboard-focused button", async ({ page }) => {
  await openKit(page);
  const pit = page.getByRole("region", { name: "LapFlag" }).getByRole("button", { name: "Pit" });
  await pit.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(pit).toBeFocused();
  const outline = await pit.evaluate((el) => {
    const s = getComputedStyle(el);
    return { style: s.outlineStyle, width: s.outlineWidth, colour: s.outlineColor };
  });
  expect(outline).toEqual({ style: "solid", width: "2px", colour: "rgb(255, 107, 99)" });
});

test.describe("under reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("the live dot and the skeletons are still", async ({ page }) => {
    await openKit(page);
    const still = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[data-slot=live-badge] > span, [data-slot=skeleton]")).map(
        (el) => getComputedStyle(el).animationName,
      ),
    );
    expect(still.length).toBeGreaterThan(5);
    expect(new Set(still)).toEqual(new Set(["none"]));
  });
});
