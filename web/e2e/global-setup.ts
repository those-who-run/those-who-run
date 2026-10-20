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
//
// One session in the main store is then copied in as still open (./store.ts), for
// the live session page (#298 AC5), unless E2E_NO_LIVE_SESSION is set: the docs'
// screenshots show a store whose sessions have all finished, as the "Idle" engineer
// chip says.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { setPitwallVersion, startEngineer } from "./engineer";
import { makeLiveSession } from "./store";

const WEB = resolve(fileURLToPath(new URL("..", import.meta.url)));
const ROOT = resolve(WEB, "..");
const FIXTURES = join(ROOT, "tests", "fixtures");

/** Replayed into the store, in this order: a timed race the engineer joined on lap
 * 7 (#298 R8), a time trial (#297 AC1), then the race and the pit stop (#237 AC1).
 * The time trial stands in for #297's drift session: since #260 the engineer
 * ignores that recording as GT7's demo race, so it leaves nothing in a store. The
 * joined race and the time trial go first, so the newest sessions are as they were. */
export const STORE_FIXTURES = [
  "real-nuc-suzuka-joined-mid-race-2026-10-18.jsonl.gz",
  "real-nuc-fuji-timed-2026-10-15.jsonl.gz",
  "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz",
  "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz",
];

/** The time trial, which the short store has too (#297 AC2). */
const TIME_TRIAL = "real-nuc-fuji-timed-2026-10-15.jsonl.gz";

/** The fixture the open session (./store.ts) is copied from: the pit stop's six laps. */
export const LIVE_SOURCE_FIXTURE = "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz";

/** Sessions in the main store: one per fixture, and the open one. */
export const STORE_SESSIONS = STORE_FIXTURES.length + 1;

/** The race's first minute, cut with `those-who-run thin`: a session with no full
 * lap (#297 AC2). */
const ZERO_LAP = { fixture: "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz", end: 60 };

/** The other pit walls (#297 AC2, AC6): the time trial and the zero-lap session;
 * no sessions at all; an index that isn't SQLite; and lap compare's (#299). */
export type OtherStore = "short" | "empty" | "broken" | "compare";

/** Lap compare's store (#299): the race, and two Suzuka East Course races at one
 * sure track id, the pit stop and the session with no stop, so lap B can come from
 * another session at the track. */
export const COMPARE_FIXTURES = [
  "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz",
  "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz",
  "real-nuc-suzuka-no-stop-2026-10-15.jsonl.gz",
];

/** The lap whose Parquet file the setup deletes from the no-stop session in the
 * compare store, so a spec sees a missing lap file (#299 AC5). The session's id and
 * the lap are in process.env.E2E_MISSING_LAP, as `<session id>/<lap>`. */
export const MISSING_LAP = 6;

/** Makes the compare store at `dir`, and returns `<session id>/<lap>` of the lap
 * file it deleted from the no-stop session (the last replayed). */
function compareStore(command: string, dir: string): string {
  const fixtures = COMPARE_FIXTURES.map((f) => join(FIXTURES, f));
  replay(command, dir, fixtures.slice(0, -1));
  const sessions = join(dir, "sessions");
  const before = new Set(readdirSync(sessions));
  replay(command, dir, fixtures.slice(-1));
  const noStop = readdirSync(sessions).find((id) => !before.has(id));
  const file = join(sessions, noStop ?? "", `lap-${String(MISSING_LAP).padStart(2, "0")}.parquet`);
  if (!noStop || !existsSync(file)) {
    throw new Error(`the compare store has no ${file} to delete`);
  }
  rmSync(file);
  return `${noStop}/${MISSING_LAP}`;
}

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

/** Replays so far, for E2E_REPLAY_CLOCK. */
let replays = 0;

/** `replay`'s `--clock`, when E2E_REPLAY_CLOCK (epoch seconds) is set: each replay's
 * sessions are dated from it, an hour apart in replay order, in place of the wall
 * clock, so the store is the same on every run and every day (the docs'
 * screenshots, #336). Every fixture is under an hour long; a longer one would
 * overlap the next. Unset, the replay names its sessions by the clock. */
function clockArgs(): string[] {
  const start = process.env.E2E_REPLAY_CLOCK;
  return start ? ["--clock", String(Number(start) + 3600 * replays++)] : [];
}

/** Replays `recordings` into the store at `data`, in order. */
function replay(command: string, data: string, recordings: string[]): void {
  const env = { ...process.env, LOG_LEVEL: "WARNING", GT7_DATA_DIR: data };
  for (const recording of recordings) {
    run(command, ["replay", recording, "--store", data, ...clockArgs()], env);
  }
}

/** The other stores, made under `tmp`: their data directories by name. */
function otherStores(command: string, tmp: string): Record<OtherStore, string> {
  const dirs = {
    short: join(tmp, "short"),
    empty: join(tmp, "empty"),
    broken: join(tmp, "broken"),
    compare: join(tmp, "compare"),
  };
  process.env.E2E_MISSING_LAP = compareStore(command, dirs.compare);
  const zeroLap = join(tmp, "zero-lap.jsonl.gz");
  run(command, ["thin", join(FIXTURES, ZERO_LAP.fixture), zeroLap, "--end", String(ZERO_LAP.end)], process.env);
  replay(command, dirs.short, [join(FIXTURES, TIME_TRIAL), zeroLap]);
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
  const sessionIds = () => (existsSync(join(data, "sessions")) ? readdirSync(join(data, "sessions")) : []);
  for (const fixture of STORE_FIXTURES) {
    const before = new Set(sessionIds());
    replay(command, data, [join(FIXTURES, fixture)]);
    if (fixture === LIVE_SOURCE_FIXTURE && !process.env.E2E_NO_LIVE_SESSION) {
      // The replay names its session by the clock: the one directory it added.
      const [id] = sessionIds().filter((d) => !before.has(d));
      if (!id) {
        throw new Error(`those-who-run replay ${fixture} stored no session`);
      }
      makeLiveSession(data, id);
      process.env.PITWALL_LIVE_SOURCE = id;
    }
  }
  // For the live spec, which adds laps to the open session as the engineer would.
  process.env.PITWALL_STORE = data;
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
