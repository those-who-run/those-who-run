// What every pit wall spec shares (#237 R11): `test` pointed at the pit wall the
// global setup started, the layout checks and the screenshot for the CI artifact.
// A new page's spec imports `test` and `expect` from here and adds its own steps.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { test as base, expect, type Page, type TestInfo } from "@playwright/test";

/** Where screenshots go, one directory per viewport: CI uploads it. */
export const SCREENSHOTS = fileURLToPath(new URL("../test-results/screenshots", import.meta.url));

export const test = base.extend({
  baseURL: async ({}, use) => {
    const url = process.env.PITWALL_URL;
    if (!url) {
      throw new Error("PITWALL_URL is not set: run through playwright.config.ts's global setup");
    }
    await use(url);
  },
});

export { expect };

/** Every API session, as the page should list them. */
export async function apiSessions(page: Page): Promise<{ session_id: string; title: string }[]> {
  const resp = await page.request.get("/api/v1/sessions");
  expect(resp.ok()).toBe(true);
  return (await resp.json()).sessions;
}

/** The page is no wider than the viewport: nothing scrolls sideways. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(scroll, `the page is ${scroll}px wide in a ${client}px viewport`).toBeLessThanOrEqual(client);
}

/** A full-page screenshot, `<viewport>/<name>.png` under SCREENSHOTS. */
export async function screenshot(page: Page, testInfo: TestInfo, name: string): Promise<string> {
  const dir = join(SCREENSHOTS, testInfo.project.name);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: "image/png" });
  return path;
}
