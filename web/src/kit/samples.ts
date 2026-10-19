// Sample data for /_kit, typed as the API's generated types: a schema change breaks
// the kit's build before it breaks a page. Track and car names are real, copied from
// the engineer's store on 2026-10-18 as plain strings, so the kit shows what long names
// do at 390 px.
import type { components } from "@/api/schema";

type Session = components["schemas"]["Session"];
type LapRow = components["schemas"]["LapRow"];

/** The kit's "now", so its dates read the same in every screenshot: Sun 18 Oct 2026,
 * 21:00 in Dublin. */
export const KIT_NOW = Date.UTC(2026, 9, 18, 20, 0) / 1000;
export const KIT_TZ = "Europe/Dublin";

const HOUR = 3600;

export const NAMES = {
  willow: "Willow Springs International Raceway: Big Willow",
  tokyo: "Tokyo Expressway - East Clockwise",
  gilles: "Circuit Gilles Villeneuve",
  suzuka: "Suzuka Circuit East Course",
  rxVision: "Mazda RX-VISION GT3 EVO '26",
  gr86: "Toyota GR86 RZ '21",
  porsche: "Porsche 911 GT3 RS (992) '22",
};

function session(over: Partial<Session> & Pick<Session, "session_id">): Session {
  return {
    title: "",
    result: "",
    started_at: KIT_NOW - 2 * HOUR,
    ended_at: KIT_NOW - HOUR,
    closed: true,
    kind: "lap_race",
    kind_label: "12-lap race",
    track: { id: 1, name: NAMES.gilles, sure: true, evidence: "finish line crossed, a full lap fits the layout (0.98)" },
    car: NAMES.porsche,
    car_code: 3361,
    finished: false,
    final_position: null,
    total_cars: null,
    position_shown: false,
    total_time_ms: null,
    best_lap_ms: null,
    best_lap_no: null,
    laps_completed: 0,
    total_laps: 0,
    fuel_use: true,
    fuel_used: null,
    fuel_capacity: 100,
    fuel_by_stint: [],
    pit_stops: 0,
    driving_ms: null,
    paused_ms: null,
    joined_on_lap: null,
    continued: false,
    restart_laps: [],
    ...over,
  };
}

/** Every SessionCard state the guide lists. */
export const SESSIONS = {
  raceFinished: session({
    session_id: "20261018-191204",
    title: `${NAMES.willow} · 6-lap race`,
    result: "🚩 Finished P1 of 16 in 9:56.826",
    started_at: KIT_NOW - HOUR,
    kind_label: "6-lap race",
    track: { id: 218, name: NAMES.willow, sure: true, evidence: "finish line crossed, a full lap fits the layout (0.97)" },
    car: NAMES.rxVision,
    finished: true,
    final_position: 1,
    total_cars: 16,
    position_shown: true,
    total_time_ms: 596_826,
    best_lap_ms: 97_764,
    best_lap_no: 4,
    laps_completed: 6,
    total_laps: 6,
  }),
  retired: session({
    session_id: "20261017-162118",
    title: `${NAMES.gilles} · 12-lap race`,
    result: "Retired on lap 3 of 12, running P15",
    started_at: KIT_NOW - 28 * HOUR,
    final_position: 15,
    total_cars: 20,
    position_shown: true,
    best_lap_ms: 96_595,
    best_lap_no: 2,
    laps_completed: 2,
    total_laps: 12,
  }),
  timed: session({
    session_id: "20261016-210455",
    title: `${NAMES.tokyo} · timed race`,
    result: "🚩 Finished P3 of 20 in 21:06.182",
    started_at: KIT_NOW - 47 * HOUR,
    kind: "timed_field",
    kind_label: "timed race",
    track: { id: 360, name: NAMES.tokyo, sure: true, evidence: "finish line crossed, a full lap fits the layout (0.95)" },
    car: NAMES.gr86,
    finished: true,
    final_position: 3,
    total_cars: 20,
    position_shown: true,
    total_time_ms: 1_266_182,
    best_lap_ms: 101_402,
    best_lap_no: 9,
    laps_completed: 12,
  }),
  timeTrial: session({
    session_id: "20261015-180019",
    title: `${NAMES.suzuka} · time trial`,
    result: "5 laps",
    started_at: KIT_NOW - 4 * 24 * HOUR,
    kind: "solo_timed",
    kind_label: "time trial",
    track: { id: 59, name: NAMES.suzuka, sure: true, evidence: "finish line crossed, a full lap fits the layout (0.99)" },
    car: NAMES.gr86,
    best_lap_ms: 49_677,
    best_lap_no: 3,
    laps_completed: 5,
  }),
  unknownTrack: session({
    session_id: "20261018-140201",
    title: "Unknown track · session",
    result: "no full lap",
    started_at: KIT_NOW - 7 * HOUR,
    kind: "unknown",
    kind_label: "session",
    track: {
      id: null,
      name: "Unknown track",
      sure: false,
      evidence: "3 layouts near the start still fit, line not yet crossed",
    },
    car: null,
    car_code: 4012,
  }),
  live: session({
    session_id: "20261018-203012",
    title: `${NAMES.willow} · 12-lap race`,
    result: "Running",
    started_at: KIT_NOW - 600,
    ended_at: null,
    closed: false,
    track: { id: 218, name: NAMES.willow, sure: true, evidence: "finish line crossed, a full lap fits the layout (0.97)" },
    car: NAMES.rxVision,
    final_position: 3,
    total_cars: 16,
    position_shown: true,
    best_lap_ms: 98_102,
    best_lap_no: 2,
    laps_completed: 4,
    total_laps: 12,
  }),
} satisfies Record<string, Session>;

function lap(over: Partial<LapRow> & Pick<LapRow, "lap">): LapRow {
  return {
    time_ms: null,
    complete: true,
    fuel_start: null,
    fuel_end: null,
    fuel_used: null,
    position: null,
    frames: 5_400,
    file: `lap-${String(over.lap).padStart(3, "0")}.parquet`,
    top_speed_kph: null,
    pit: false,
    out_lap: false,
    invalid: false,
    best: false,
    fuel_use: true,
    restart: false,
    clean: true,
    ...over,
  };
}

/** A lap table's rows, with every flag. Gaps are to the best lap, lap 4. */
export const LAPS: LapRow[] = [
  lap({ lap: 1, time_ms: 101_233, position: 5, top_speed_kph: 241, fuel_used: 3.3 }),
  lap({ lap: 2, time_ms: 98_630, position: 4, top_speed_kph: 246, fuel_used: 3.2 }),
  lap({ lap: 3, time_ms: 99_412, position: 3, top_speed_kph: 245, fuel_used: 3.2, pit: true, clean: false }),
  lap({ lap: 4, time_ms: 97_764, position: 1, top_speed_kph: 248, fuel_used: 3.1, best: true }),
  lap({ lap: 5, time_ms: 104_870, position: 2, top_speed_kph: 239, fuel_used: 3.2, out_lap: true, clean: false }),
  lap({ lap: 6, time_ms: 98_201, position: 1, top_speed_kph: 247, fuel_used: 3.3, restart: true, clean: false }),
  lap({
    lap: 7,
    time_ms: null,
    complete: false,
    position: 1,
    top_speed_kph: 230,
    fuel_used: 1.4,
    invalid: true,
    clean: false,
  }),
];

type EngineStatus = components["schemas"]["EngineStatus"];
type LiveSession = components["schemas"]["LiveSession"];

/** The kit's pit wall version, and the engineer's when the two match. */
export const KIT_VERSION = "0.7.1";

/** An engineer status (#292), for the live chip's states. */
export function engine(over: Partial<EngineStatus> = {}): EngineStatus {
  return {
    version: KIT_VERSION,
    started_at: KIT_NOW - 3 * HOUR,
    activity: "idle",
    idle_secs: 600,
    telemetry: { connected: false, last_packet_age_s: null },
    voice_connected: true,
    session: null,
    ...over,
  };
}

/** The session the engineer has open, on a track it is sure of. */
export function liveSession(over: Partial<LiveSession> = {}): LiveSession {
  return {
    id: "20261018-201500",
    kind: "lap_race",
    track: { id: 1, name: NAMES.willow, sure: true },
    car: NAMES.rxVision,
    lap: 3,
    laps_total: 12,
    position: 3,
    cars: 16,
    ...over,
  };
}
