// The session list over the real pit wall and a replayed store (#237 AC1 to AC3),
// at each of the three viewports, each page checked by axe (ADR 0004 point 11).
import { expectAccessible } from "./a11y";
import { STORE_FIXTURES } from "./global-setup";
import { apiSessions, expect, expectNoHorizontalScroll, screenshot, test } from "./pitwall";

test("lists every session, with no sideways scroll", async ({ page }, testInfo) => {
  const sessions = await apiSessions(page);
  expect(sessions).toHaveLength(STORE_FIXTURES.length);

  await page.goto("/");
  const list = page.getByRole("list", { name: "Sessions" });
  await expect(list).toBeVisible();
  await expect(list.getByRole("link")).toHaveCount(sessions.length);
  for (const s of sessions) {
    const link = list.getByRole("link", { name: s.title, exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", `/sessions/${s.session_id}`);
  }
  await expect(page.getByText("Circuit Gilles Villeneuve · 12-lap race")).toBeVisible();
  await expect(page.getByText("Suzuka Circuit East Course · 6-lap race")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, testInfo, "sessions");
  await expectAccessible(page, testInfo, "sessions");
});

test("a session's link opens its page", async ({ page }, testInfo) => {
  const [first] = await apiSessions(page);
  await page.goto("/");
  await page.getByRole("link", { name: first!.title, exact: true }).click();
  await expect(page).toHaveURL(`/sessions/${first!.session_id}`);
  await expect(page.getByRole("heading", { name: first!.title })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expectAccessible(page, testInfo, "session");
});

test("a results card's /?session=<id> lands on /sessions/<id>", async ({ page }) => {
  const [first] = await apiSessions(page);
  await page.goto(`/?session=${first!.session_id}`);
  await expect(page).toHaveURL(`/sessions/${first!.session_id}`);
  await expect(page.getByRole("heading", { name: first!.title })).toBeVisible();
});

test("an unknown path has a page of its own", async ({ page }, testInfo) => {
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Nothing here" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await expectAccessible(page, testInfo, "not-found");
});
