// @vitest-environment node
import { describe, expect, it } from "vitest";

import { budgetFrom, measure, type Budget, type Manifest } from "./bundle-budget.ts";

// Incompressible bytes, so the gzipped size is about the raw size.
function noise(n: number): Uint8Array {
  const out = new Uint8Array(n);
  let x = 2463534242;
  for (let i = 0; i < n; i++) {
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    out[i] = x & 0xff;
  }
  return out;
}

const MANIFEST: Manifest = {
  "index.html": { file: "assets/index.js", src: "index.html", isEntry: true, css: ["assets/index.css"] },
  "_shared.js": { file: "assets/shared.js", imports: ["index.html"] },
  "src/routes/sessions.tsx": {
    file: "assets/sessions.js",
    src: "src/routes/sessions.tsx",
    isDynamicEntry: true,
    imports: ["_shared.js", "index.html"],
  },
  "src/routes/session.tsx": {
    file: "assets/session.js",
    src: "src/routes/session.tsx",
    isDynamicEntry: true,
    imports: ["index.html"],
  },
};

const SIZES: Record<string, number> = {
  "assets/index.js": 40_000,
  "assets/index.css": 2_000,
  "assets/shared.js": 5_000,
  "assets/sessions.js": 1_000,
  "assets/session.js": 3_000,
};

const files: Record<string, Uint8Array> = Object.fromEntries(
  Object.entries(SIZES).map(([f, n]) => [f, noise(n)]),
);
const read = (f: string) => files[f]!;
const ROUTES = ["src/routes/sessions.tsx", "src/routes/session.tsx"];
const ROOMY: Budget = { entry: 100_000, route: 61_440, routes: {} };

describe("the bundle budget", () => {
  it("measures the entry with its CSS, and each route with what the entry lacks", () => {
    const report = measure(MANIFEST, read, ROOMY, ROUTES);
    expect(report.errors).toEqual([]);
    expect(report.entry.files.sort()).toEqual(["assets/index.css", "assets/index.js"]);
    expect(report.entry.gzip).toBeGreaterThan(42_000);
    const sessions = report.routes.find((r) => r.name === "src/routes/sessions.tsx")!;
    expect(sessions.files.sort()).toEqual(["assets/sessions.js", "assets/shared.js"]);
    expect(sessions.gzip).toBeGreaterThan(6_000);
  });

  it("fails a route chunk over its budget, naming it (AC6)", () => {
    const budget = { ...ROOMY, routes: { "src/routes/session.tsx": 2_000 } };
    const { errors } = measure(MANIFEST, read, budget, ROUTES);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/^route chunk src\/routes\/session\.tsx is .* over its budget of 2\.0 KB$/);
  });

  it("caps every route at the ceiling", () => {
    const budget = { ...ROOMY, route: 4_000, routes: { "src/routes/sessions.tsx": 50_000 } };
    const { errors } = measure(MANIFEST, read, budget, ROUTES);
    expect(errors.join("\n")).toContain("route chunk src/routes/sessions.tsx");
  });

  it("fails the entry over its budget", () => {
    const { errors } = measure(MANIFEST, read, { ...ROOMY, entry: 10_000 }, ROUTES);
    expect(errors[0]).toMatch(/^entry \(index\.html\) is .* over its budget/);
  });

  it("fails a route module that is not lazy (R4)", () => {
    const { errors } = measure(MANIFEST, read, ROOMY, [...ROUTES, "src/routes/laps.tsx"]);
    expect(errors).toEqual([expect.stringContaining("src/routes/laps.tsx is not a lazy route chunk")]);
  });

  it("sets a budget at the build plus 10%", () => {
    const report = measure(MANIFEST, read, ROOMY, ROUTES);
    const set = budgetFrom(report);
    expect(set.entry).toBe(Math.ceil(report.entry.gzip * 1.1));
    expect(set.routes["src/routes/session.tsx"]).toBe(Math.ceil(report.routes[0]!.gzip * 1.1));
    expect(set.route).toBe(61_440);
  });
});
