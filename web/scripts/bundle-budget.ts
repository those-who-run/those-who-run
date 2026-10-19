// The bundle budget (#237 R6, ADR 0003 point 2): the gzipped size of the entry and
// of each route chunk, from Vite's build manifest, against bundle-budget.json.
//
//   node scripts/bundle-budget.ts         check dist/ and print the sizes
//   node scripts/bundle-budget.ts --set   write the budget as this build plus 10%
//
// The entry is what the first page load needs: the entry chunk, the chunks it
// imports statically and their CSS. A route is its lazy chunk plus what it imports
// that the entry does not already load. Every module under src/routes/ must be a
// lazy chunk of its own (R4): one that is imported statically fails here too.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

export interface ManifestChunk {
  file: string;
  src?: string;
  isEntry?: boolean;
  isDynamicEntry?: boolean;
  imports?: string[];
  css?: string[];
}

export type Manifest = Record<string, ManifestChunk>;

/** Limits in gzipped bytes. `route` is the ceiling for any route chunk (60 KB);
 * `routes` holds each route's own, set from a build. */
export interface Budget {
  entry: number;
  route: number;
  routes: Record<string, number>;
}

export interface Measured {
  name: string;
  files: string[];
  gzip: number;
  limit: number;
}

export interface Report {
  entry: Measured;
  routes: Measured[];
  errors: string[];
}

const ROUTE_CEILING = 60 * 1024;

/** The files a chunk loads with it: itself, its static imports, and their CSS. */
function closure(manifest: Manifest, key: string, seen = new Set<string>()): Set<string> {
  const chunk = manifest[key];
  if (!chunk || seen.has(key)) {
    return new Set();
  }
  seen.add(key);
  const files = new Set([chunk.file, ...(chunk.css ?? [])]);
  for (const dep of chunk.imports ?? []) {
    for (const f of closure(manifest, dep, seen)) {
      files.add(f);
    }
  }
  return files;
}

export function measure(
  manifest: Manifest,
  read: (file: string) => Uint8Array,
  budget: Budget,
  routeModules: string[],
): Report {
  const gzip = (files: Iterable<string>) =>
    [...files].reduce((n, f) => n + gzipSync(read(f), { level: 9 }).length, 0);
  const errors: string[] = [];

  const entryKey = Object.keys(manifest).find((k) => manifest[k]?.isEntry);
  if (entryKey === undefined) {
    throw new Error("the manifest has no entry chunk: is build.manifest on?");
  }
  const entryFiles = closure(manifest, entryKey);
  const entry: Measured = {
    name: `entry (${entryKey})`,
    files: [...entryFiles],
    gzip: gzip(entryFiles),
    limit: budget.entry,
  };
  if (entry.gzip > entry.limit) {
    errors.push(`${entry.name} is ${kb(entry.gzip)} gzipped, over its budget of ${kb(entry.limit)}`);
  }

  const routes: Measured[] = [];
  for (const [key, chunk] of Object.entries(manifest)) {
    if (!chunk.isDynamicEntry || !chunk.src?.startsWith("src/routes/")) {
      continue;
    }
    const files = [...closure(manifest, key)].filter((f) => !entryFiles.has(f));
    const limit = Math.min(budget.routes[chunk.src] ?? budget.route, budget.route);
    const m = { name: chunk.src, files, gzip: gzip(files), limit };
    routes.push(m);
    if (m.gzip > m.limit) {
      errors.push(`route chunk ${m.name} is ${kb(m.gzip)} gzipped, over its budget of ${kb(m.limit)}`);
    }
  }
  const lazy = new Set(routes.map((r) => r.name));
  for (const mod of routeModules) {
    if (!lazy.has(mod)) {
      errors.push(`${mod} is not a lazy route chunk: load it with \`lazy\` in src/routes.ts (#237 R4)`);
    }
  }
  if (budget.route > ROUTE_CEILING) {
    errors.push(`the route ceiling ${kb(budget.route)} is over the ${kb(ROUTE_CEILING)} ADR 0003 allows`);
  }
  routes.sort((a, b) => a.name.localeCompare(b.name));
  return { entry, routes, errors };
}

/** This build plus 10%: what `--set` writes. */
export function budgetFrom(report: Report, routeCeiling = ROUTE_CEILING): Budget {
  const plus = (n: number) => Math.ceil(n * 1.1);
  return {
    entry: plus(report.entry.gzip),
    route: routeCeiling,
    routes: Object.fromEntries(report.routes.map((r) => [r.name, Math.min(plus(r.gzip), routeCeiling)])),
  };
}

export function kb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function table(report: Report): string {
  const rows = [report.entry, ...report.routes].map(
    (m) => `  ${m.name.padEnd(36)} ${kb(m.gzip).padStart(9)} of ${kb(m.limit).padStart(9)}`,
  );
  return ["Bundle sizes (gzipped):", ...rows].join("\n");
}

function main(argv: string[]): number {
  const web = resolve(fileURLToPath(new URL("..", import.meta.url)));
  const dist = join(web, "dist");
  const budgetFile = join(web, "bundle-budget.json");
  const manifest = JSON.parse(readFileSync(join(dist, ".vite", "manifest.json"), "utf8")) as Manifest;
  const budget = JSON.parse(readFileSync(budgetFile, "utf8")) as Budget;
  const routeModules = readdirSync(join(web, "src", "routes"))
    .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
    .map((f) => `src/routes/${f}`);
  const report = measure(manifest, (f) => readFileSync(join(dist, f)), budget, routeModules);
  console.log(table(report));
  if (argv.includes("--set")) {
    writeFileSync(budgetFile, JSON.stringify(budgetFrom(report), null, 2) + "\n");
    console.log(`wrote ${budgetFile}: this build plus 10%`);
    return 0;
  }
  for (const e of report.errors) {
    console.error(`bundle budget: ${e}`);
  }
  return report.errors.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
