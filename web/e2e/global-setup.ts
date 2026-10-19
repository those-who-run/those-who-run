// Starts the real pit wall over a store replayed from fixtures, serving web/dist
// (ADR 0003 point 5), with a stub engineer behind it (./engineer.ts, #296). Specs
// get its address as PITWALL_URL, through ./pitwall.ts.
//
// The store is made the way the Python tests make one: `those-who-run replay
// <fixture> --store <dir>` for each fixture in STORE_FIXTURES, into a temporary
// directory removed afterwards. TWR names the command (make sets it to
// .venv/bin/those-who-run).
//
// Beside it, a pit wall for each of the other stores (#297): one with a session of
// no full lap, an empty one, and one whose index can't be read. Specs reach them
// through `storeUrl(name)` in ./pitwall.ts, so the main store stays as every other
// spec expects it.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { setPitwallVersion, startEngineer } from "./engineer";

const WEB = resolve(fileURLToPath(new URL("..", import.meta.url)));
const ROOT = resolve(WEB, "..");
const FIXTURES = join(ROOT, "tests", "fixtures");

/** Replayed into the store, in this order: a time trial (#297 AC1), then the race
 * and the pit stop (#237 AC1). The time trial stands in for #297's drift session:
 * since #260 the engineer ignores that recording as GT7's demo race, so it leaves
 * nothing in a store. It goes first, so the newest sessions are as they were. */
export const STORE_FIXTURES = [
  "real-nuc-fuji-timed-2026-10-15.jsonl.gz",
  "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz",
  "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz",
];

/** The race's first minute, cut with `those-who-run thin`: a session with no full
 * lap (#297 AC2). */
const ZERO_LAP = { fixture: "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz", end: 60 };

/** The other pit walls (#297 AC2, AC6): the time trial and the zero-lap session;
 * no sessions at all; an index that isn't SQLite. */
export type OtherStore = "short" | "empty" | "broken";

function twr(): string {
  const command = process.env.TWR ?? join(ROOT, ".venv", "bin", "those-who-run");
  if (!existsSync(command)) {
    throw new Error(`${command} not found: run make venv, or set TWR to those-who-run`);
  }
  return command;
}

function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const server = createServer();
    server.unref();
    server.on("error", fail);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => (typeof address === "object" && address ? ok(address.port) : fail()));
    });
  });
}

async function waitForHealth(url: string, ms: number): Promise<void> {
  const until = Date.now() + ms;
  for (;;) {
    try {
      // Any answer will do: the broken store's pit wall is up but unhealthy.
      await fetch(`${url}/healthz`);
      return;
    } catch {
      // not listening yet
    }
    if (Date.now() > until) {
      throw new Error(`the pit wall did not answer ${url}/healthz within ${ms} ms`);
    }
    await new Promise((r) => setTimeout(r, 100));
  }
}

function run(command: string, args: string[], env: NodeJS.ProcessEnv): void {
  const out = spawnSync(command, args, { env, stdio: ["ignore", "ignore", "inherit"] });
  if (out.status !== 0) {
    throw new Error(`those-who-run ${args.slice(0, 2).join(" ")} failed (exit ${out.status})`);
  }
}

/** Replays `recordings` into the store at `data`, in order. */
function replay(command: string, data: string, recordings: string[]): void {
  const env = { ...process.env, LOG_LEVEL: "WARNING", GT7_DATA_DIR: data };
  for (const recording of recordings) {
    run(command, ["replay", recording, "--store", data], env);
  }
}

/** The other stores, made under `tmp`: their data directories by name. */
function otherStores(command: string, tmp: string): Record<OtherStore, string> {
  const dirs = { short: join(tmp, "short"), empty: join(tmp, "empty"), broken: join(tmp, "broken") };
  const zeroLap = join(tmp, "zero-lap.jsonl.gz");
  run(command, ["thin", join(FIXTURES, ZERO_LAP.fixture), zeroLap, "--end", String(ZERO_LAP.end)], process.env);
  replay(command, dirs.short, [join(FIXTURES, STORE_FIXTURES[0]!), zeroLap]);
  mkdirSync(dirs.empty);
  mkdirSync(dirs.broken);
  writeFileSync(join(dirs.broken, "index.sqlite"), "not a database ".repeat(512));
  return dirs;
}

/** A pit wall over the store at `data`, serving web/dist, with `engineer` behind it. */
async function startPitwall(
  command: string,
  data: string,
  engineer: string,
  logLevel = "WARNING",
): Promise<{ url: string; stop: () => Promise<void> }> {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const env = {
    ...process.env,
    LOG_LEVEL: logLevel,
    GT7_DATA_DIR: data,
    GT7_ENGINEER_URL: engineer,
    GT7_ENGINEER_CONTROL_URL: "http://127.0.0.1:9",
  };
  const args = ["pitwall", "--address", "127.0.0.1", "--port", String(port), "--static", join(WEB, "dist")];
  const server = spawn(command, args, { env, stdio: "inherit" });
  const exited = new Promise<void>((r) => server.once("exit", () => r()));
  await waitForHealth(url, 15_000);
  return {
    url,
    stop: async () => {
      server.kill("SIGTERM");
      await exited;
    },
  };
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  if (!existsSync(join(WEB, "dist", "index.html"))) {
    throw new Error("web/dist has no index.html: run make web-build first");
  }
  const command = twr();
  const tmp = mkdtempSync(join(tmpdir(), "twr-e2e-"));
  const data = join(tmp, "data");
  replay(
    command,
    data,
    STORE_FIXTURES.map((f) => join(FIXTURES, f)),
  );
  const others = otherStores(command, tmp);

  // The stub engineer (./engineer.ts): down unless a test asks for a scenario, so
  // /api/engine/status is a 502 and the data routes carry on. No control port.
  const engineer = await startEngineer();
  const main = await startPitwall(command, data, engineer.url);
  const started = await Promise.all(
    (Object.entries(others) as [OtherStore, string][]).map(
      // The broken store's pit wall logs a traceback per ask: expected, and kept out.
      async ([name, dir]) =>
        [name, await startPitwall(command, dir, engineer.url, name === "broken" ? "CRITICAL" : "WARNING")] as const,
    ),
  );
  // The stub's engineer is on the pit wall's version unless a scenario says not.
  setPitwallVersion(((await (await fetch(`${main.url}/healthz`)).json()) as { version: string }).version);
  process.env.PITWALL_URL = main.url;
  process.env.PITWALL_STORES = JSON.stringify(Object.fromEntries(started.map(([name, p]) => [name, p.url])));

  return async () => {
    await Promise.all([main, ...started.map(([, p]) => p)].map((p) => p.stop()));
    engineer.server.closeAllConnections();
    await new Promise<void>((r) => engineer.server.close(() => r()));
    rmSync(tmp, { recursive: true, force: true });
  };
}
