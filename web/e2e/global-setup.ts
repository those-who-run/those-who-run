// Starts the real pit wall over a store replayed from fixtures, serving web/dist
// (ADR 0003 point 5). Specs get its address as PITWALL_URL, through ./pitwall.ts.
//
// The store is made the way the Python tests make one: `those-who-run replay
// <fixture> --store <dir>` for each fixture in STORE_FIXTURES, into a temporary
// directory removed afterwards. TWR names the command (make sets it to
// .venv/bin/those-who-run).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(fileURLToPath(new URL("..", import.meta.url)));
const ROOT = resolve(WEB, "..");
const FIXTURES = join(ROOT, "tests", "fixtures");

/** Replayed into the store, in this order: the race and the pit stop (#237 AC1). */
export const STORE_FIXTURES = [
  "real-nuc-gilles-villeneuve-race-2026-10-17.jsonl.gz",
  "real-nuc-suzuka-pit-stop-2026-10-15.jsonl.gz",
];

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
      if ((await fetch(`${url}/healthz`)).ok) {
        return;
      }
    } catch {
      // not listening yet
    }
    if (Date.now() > until) {
      throw new Error(`the pit wall did not answer ${url}/healthz within ${ms} ms`);
    }
    await new Promise((r) => setTimeout(r, 100));
  }
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const dist = join(WEB, "dist");
  if (!existsSync(join(dist, "index.html"))) {
    throw new Error("web/dist has no index.html: run make web-build first");
  }
  const command = twr();
  const tmp = mkdtempSync(join(tmpdir(), "twr-e2e-"));
  const data = join(tmp, "data");
  const env = { ...process.env, LOG_LEVEL: "WARNING", GT7_DATA_DIR: data };
  for (const fixture of STORE_FIXTURES) {
    const replay = spawnSync(command, ["replay", join(FIXTURES, fixture), "--store", data], {
      env,
      stdio: ["ignore", "ignore", "inherit"],
    });
    if (replay.status !== 0) {
      throw new Error(`those-who-run replay ${fixture} failed (exit ${replay.status})`);
    }
  }

  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const server = spawn(
    command,
    ["pitwall", "--address", "127.0.0.1", "--port", String(port), "--static", dist],
    // No engineer anywhere: /api/engine/* answer 502, the data routes carry on.
    { env: { ...env, GT7_ENGINEER_URL: "http://127.0.0.1:9", GT7_ENGINEER_CONTROL_URL: "http://127.0.0.1:9" }, stdio: "inherit" },
  );
  const exited = new Promise<void>((r) => server.once("exit", () => r()));
  await waitForHealth(url, 15_000);
  process.env.PITWALL_URL = url;

  return async () => {
    server.kill("SIGTERM");
    await exited;
    rmSync(tmp, { recursive: true, force: true });
  };
}
