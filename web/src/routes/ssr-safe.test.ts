// @vitest-environment node
//
// ADR 0003 point 3: no browser-only code at module top level. Every route module,
// the route table and the client import under Node with no DOM, so a later move to
// server rendering does not start by untangling `window`.
import { describe, expect, it } from "vitest";

const routeModules = import.meta.glob(["./*.tsx", "!./*.test.tsx"]);
const appModules = import.meta.glob(["../routes.ts", "../api/*.ts", "!../api/*.d.ts", "!../api/*.test.ts"]);

describe("modules import under Node with no DOM", () => {
  it("runs with no DOM", () => {
    expect(typeof window).toBe("undefined");
    expect(typeof document).toBe("undefined");
  });

  it("finds the route modules", () => {
    expect(Object.keys(routeModules)).toEqual(
      expect.arrayContaining(["./sessions.tsx", "./session.tsx"]),
    );
  });

  it.each(Object.entries({ ...routeModules, ...appModules }))("%s", async (_, load) => {
    const mod = (await load()) as Record<string, unknown>;
    expect(Object.keys(mod).length).toBeGreaterThan(0);
  });

  it("catches a module that reads window at top level", async () => {
    await expect(import("./__fixtures__/reads-window")).rejects.toThrow(/window is not defined/);
  });
});
