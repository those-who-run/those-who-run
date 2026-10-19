// make web-check fails, rather than skips, without the Playwright browser (#161).
import { existsSync } from "node:fs";

import { chromium } from "@playwright/test";

const path = chromium.executablePath();
if (!existsSync(path)) {
  console.error(`the Playwright browser is missing (${path}): cd web && npx playwright install chromium`);
  process.exit(1);
}
