// A stub engineer for the Playwright run (#296 Fixtures): the pit wall's
// GT7_ENGINEER_URL points here, and it answers `GET /api/v1/status` (#292) the way
// the engineer would, for the scenario a test asks for.
//
// Specs run in parallel against one pit wall, so the scenario travels with each
// request rather than living in the stub: a test calls `setEngineer(page, name)`,
// which sends `Authorization: Bearer stub-<name>` on every request the page makes.
// Authorization is one of the few headers the pit wall's proxy forwards to the
// engineer (REQUEST_HEADERS in pitwall/server.py), and the pit wall itself reads
// no token. With no scenario the engineer is down: the stub drops the connection,
// the proxy answers its 502, and the pages carry on as they do on the NUC with the
// engineer stopped.
import { createServer, type Server } from "node:http";

import type { Page } from "@playwright/test";

/** The engineer's version when a scenario doesn't say otherwise: the pit wall's
 * own, set by the global setup once the pit wall has answered /healthz. */
let pitwallVersion = "0.0.0";

export function setPitwallVersion(version: string): void {
  pitwallVersion = version;
}

/** The deploy-rolling-out scenario's engineer version: never the pit wall's. */
export const OTHER_VERSION = "0.0.0-older";

export const TRACK = "Suzuka Circuit East Course";
export const SESSION_ID = "20261017-162118";

const live = (track: { id: number | null; name: string | null; sure: boolean } | null, lap: number) => ({
  id: SESSION_ID,
  kind: "lap_race",
  track,
  car: "Porsche 911 GT3 RS (992) '22",
  lap,
  laps_total: 6,
  position: 3,
  cars: 16,
});

const SCENARIOS = {
  idle: {},
  menus: { telemetry: { connected: true, last_packet_age_s: 0.2 } },
  driving: {
    activity: "driving",
    idle_secs: 0,
    telemetry: { connected: true, last_packet_age_s: 0.0 },
    session: live({ id: 4, name: TRACK, sure: true }, 3),
  },
  "driving-unsure": {
    activity: "driving",
    idle_secs: 0,
    telemetry: { connected: true, last_packet_age_s: 0.0 },
    session: live({ id: null, name: TRACK, sure: false }, 2),
  },
  "driving-no-session": { activity: "driving", idle_secs: 0, telemetry: { connected: true, last_packet_age_s: 0.0 } },
  paused: {
    activity: "paused",
    idle_secs: 12,
    telemetry: { connected: true, last_packet_age_s: 0.1 },
    session: live({ id: 4, name: TRACK, sure: true }, 4),
  },
  replay: { activity: "replay", idle_secs: 0, telemetry: { connected: true, last_packet_age_s: 0.0 } },
  demo: { activity: "demo", idle_secs: 0, telemetry: { connected: true, last_packet_age_s: 0.0 } },
  "other-version": { version: OTHER_VERSION },
} as const;

export type Scenario = keyof typeof SCENARIOS | "down";

/** The engineer's status body for a scenario. */
export function status(scenario: keyof typeof SCENARIOS): Record<string, unknown> {
  return {
    version: pitwallVersion,
    started_at: 1_792_000_000,
    activity: "idle",
    idle_secs: 600,
    telemetry: { connected: false, last_packet_age_s: null },
    voice_connected: true,
    session: null,
    ...SCENARIOS[scenario],
  };
}

function scenarioOf(authorization: string | undefined): Scenario {
  const name = /^Bearer stub-(.+)$/.exec(authorization ?? "")?.[1];
  return name && name in SCENARIOS ? (name as Scenario) : "down";
}

/** Starts the stub on a free local port; resolves to its URL and server. */
export function startEngineer(): Promise<{ url: string; server: Server }> {
  const server = createServer((req, res) => {
    const scenario = scenarioOf(req.headers.authorization);
    if (req.method !== "GET" || req.url?.split("?")[0] !== "/api/v1/status" || scenario === "down") {
      // Down: no answer at all, as an engineer that isn't running.
      req.socket.destroy();
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify(status(scenario)));
  });
  return new Promise((ok, fail) => {
    server.once("error", fail);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (typeof address === "object" && address) {
        ok({ url: `http://127.0.0.1:${address.port}`, server });
      } else {
        fail(new Error("the stub engineer has no address"));
      }
    });
  });
}

/** From now on the page's engineer is in `scenario` ("down" for none). */
export async function setEngineer(page: Page, scenario: Scenario): Promise<void> {
  await page.setExtraHTTPHeaders(scenario === "down" ? {} : { Authorization: `Bearer stub-${scenario}` });
}
