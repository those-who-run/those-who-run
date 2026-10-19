// A session still being driven, for the live session page (#298 AC5): the global
// setup copies a replayed session into the store as an open one (no summary.json,
// as the engineer leaves it mid-session) with its last laps held back, and a test
// adds a held-back lap the way the engineer commits one, a row in the index's
// `laps` table. The pit wall reads the index read-only and keys its ETags on the
// index's write time, so the next poll sees the new lap.
//
// Only the live spec writes, and only to this session, so the other specs' view of
// the store never changes under them.
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

/** The open session's id: what the stub engineer's "live-store" scenario drives. */
export const LIVE_SESSION_ID = "20261015-e2e-live";

/** Laps the live session starts with; the rest are held back for addLap. */
export const LIVE_LAPS_AT_START = 4;

function index(data: string): DatabaseSync {
  const db = new DatabaseSync(join(data, "index.sqlite"));
  db.exec("PRAGMA busy_timeout = 5000");
  return db;
}

/** Copies `source` (a closed session) into the store as LIVE_SESSION_ID, open,
 * with its first LIVE_LAPS_AT_START laps. A second before its source, so the
 * source is still the newest session, and both are on the same day. */
export function makeLiveSession(data: string, source: string): void {
  const db = index(data);
  try {
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(source) as Record<string, unknown>;
    if (!row) {
      throw new Error(`no session ${source} in the store`);
    }
    const cols = Object.keys(row);
    const values = cols.map((c) => {
      switch (c) {
        case "id":
          return LIVE_SESSION_ID;
        case "started_at":
          return (row.started_at as number) - 1;
        case "ended_at":
          return null;
        case "laps_completed":
          return LIVE_LAPS_AT_START;
        default:
          return row[c] as never;
      }
    });
    db.prepare(`INSERT INTO sessions (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`).run(
      ...(values as never[]),
    );
    const laps = db.prepare("SELECT * FROM laps WHERE session_id = ? AND lap <= ? ORDER BY lap");
    for (const lap of laps.all(source, LIVE_LAPS_AT_START) as Record<string, unknown>[]) {
      copyLap(db, data, source, lap);
    }
  } finally {
    db.close();
  }
}

function copyLap(db: DatabaseSync, data: string, source: string, lap: Record<string, unknown>): void {
  const dir = join(data, "sessions", LIVE_SESSION_ID);
  mkdirSync(dir, { recursive: true });
  copyFileSync(join(data, "sessions", source, lap.file as string), join(dir, lap.file as string));
  const cols = Object.keys(lap);
  db.prepare(`INSERT OR REPLACE INTO laps (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`).run(
    ...(cols.map((c) => (c === "session_id" ? LIVE_SESSION_ID : lap[c])) as never[]),
  );
}

/** Commits lap `n` of `source` to the live session, as the engineer does when a
 * lap closes. */
export function addLap(data: string, source: string, n: number): void {
  const db = index(data);
  try {
    const lap = db.prepare("SELECT * FROM laps WHERE session_id = ? AND lap = ?").get(source, n) as
      | Record<string, unknown>
      | undefined;
    if (!lap) {
      throw new Error(`session ${source} has no lap ${n}`);
    }
    db.exec("BEGIN");
    copyLap(db, data, source, lap);
    db.prepare("UPDATE sessions SET laps_completed = ? WHERE id = ?").run(n, LIVE_SESSION_ID);
    db.exec("COMMIT");
  } finally {
    db.close();
  }
}
