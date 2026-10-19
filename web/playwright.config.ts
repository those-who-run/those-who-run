import { defineConfig } from "@playwright/test";

import { VIEWPORTS } from "./e2e/viewports";

// The built app (web/dist) on the real pit wall server over a replayed store, in
// Chromium at three sizes (ADR 0003 point 5). e2e/global-setup.ts starts it.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  outputDir: "./test-results/playwright",
  forbidOnly: !!process.env.CI,
  fullyParallel: true,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: { browserName: "chromium", trace: "retain-on-failure" },
  projects: VIEWPORTS.map((v) => ({ name: v.name, use: v.use })),
});
