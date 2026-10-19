// axe over a page (ADR 0004 point 11, #295 R5): every page spec calls this at every
// viewport, and no serious or critical violation is allowed. The full report is
// attached to the test, so a failure names the rule, the element and the fix.
import AxeBuilder from "@axe-core/playwright";
import type { Page, TestInfo } from "@playwright/test";

import { expect } from "./pitwall";

const BLOCKING = new Set(["serious", "critical"]);

export async function expectAccessible(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  await testInfo.attach(`axe-${name}.json`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  const blocking = results.violations
    .filter((v) => BLOCKING.has(v.impact ?? ""))
    .map((v) => `${v.impact} ${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join("; ")})`);
  expect(blocking, `axe on ${name}: serious or critical violations`).toEqual([]);
}
