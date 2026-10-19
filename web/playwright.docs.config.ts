import { defineConfig } from "@playwright/test";

import { VIEWPORTS } from "./e2e/viewports";

// The docs' screenshots (#336): `make docs-screenshots` runs this, never
// `make web-check`. The same global setup as the e2e suite (the built app on the
// real pit wall over the replayed fixtures, with the stub engineer), but the store
// dated from a fixed time, so every run gives the same pictures. Writes
// docs/assets/screens/<viewport>/<page>.png.

/** The replayed sessions start here, an hour apart (./e2e/global-setup.ts). */
process.env.E2E_REPLAY_CLOCK ??= String(Date.UTC(2026, 9, 18, 8, 0, 0) / 1000);

const SIZES = ["phone", "desktop"];

export default defineConfig({
  testDir: "./e2e",
  testMatch: "docs.screens.ts",
  globalSetup: "./e2e/global-setup.ts",
  outputDir: "./test-results/docs",
  forbidOnly: !!process.env.CI,
  fullyParallel: true,
  reporter: "list",
  use: {
    browserName: "chromium",
    timezoneId: "UTC",
    locale: "en-GB",
    reducedMotion: "reduce",
    colorScheme: "dark",
  },
  projects: VIEWPORTS.filter((v) => SIZES.includes(v.name)).map((v) => ({
    name: v.name,
    // The phone at device scale 2, not 3: a third of the bytes, and still sharp.
    use: v.name === "phone" ? { ...v.use, deviceScaleFactor: 2 } : v.use,
  })),
});
