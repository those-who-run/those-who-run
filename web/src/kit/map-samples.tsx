// The track map's states for /_kit (#350 R9): pedals with the cursor on both laps,
// speed, a pit lap broken at its cut-scene, loading, and no trace. Its own chunk,
// so the kit's page stays under the route ceiling. The laps are drawn from a closed
// curve here, not a store: the kit has no pit wall behind it.
import { useState, type ReactNode } from "react";

import type { Trace } from "@/api/hooks";
import { createCursorStore } from "@/compare/cursor";
import type { MapMode } from "@/compare/map";
import { TrackMap } from "@/compare/track-map";

import { NAMES } from "./samples";

const POINTS = 600;

/** A lap round a closed curve about 4 km long: fast where it bends gently, on the
 * brake into the tight parts, `offset` metres to the side of the first. */
function sampleLap(lap: number, offset = 0, pace = 1): Trace {
  const pts = Array.from({ length: POINTS }, (_, i) => {
    const a = (2 * Math.PI * i) / POINTS;
    return {
      x: 520 * Math.cos(a) + 140 * Math.cos(3 * a) + offset,
      z: 300 * Math.sin(a) - 90 * Math.sin(2 * a) + offset,
    };
  });
  const bend = pts.map((p, i) => {
    const prev = pts[(i + POINTS - 1) % POINTS]!;
    const next = pts[(i + 1) % POINTS]!;
    const h1 = Math.atan2(p.z - prev.z, p.x - prev.x);
    const h2 = Math.atan2(next.z - p.z, next.x - p.x);
    return Math.abs(Math.atan2(Math.sin(h2 - h1), Math.cos(h2 - h1)));
  });
  const top = Math.max(...bend);
  // The speed a bend allows, eased so the car brakes before it and accelerates out.
  const allowed = bend.map((b) => 90 + 190 * (1 - b / top) ** 2);
  const speed = allowed.map((_, i) => Math.min(...[0, 4, 8, 12].map((k) => allowed[(i + k) % POINTS]!)) * pace);
  const t: number[] = [0];
  for (let i = 1; i < POINTS; i++) {
    const d = Math.hypot(pts[i]!.x - pts[i - 1]!.x, pts[i]!.z - pts[i - 1]!.z);
    t.push(Math.round((t[i - 1]! + d / (speed[i]! / 3.6)) * 1000) / 1000);
  }
  const change = speed.map((v, i) => speed[(i + 1) % POINTS]! - v);
  return {
    session_id: "kit",
    lap,
    t,
    speed_kph: speed.map((v) => Math.round(v * 10) / 10),
    throttle_pct: change.map((c) => (c > 0.5 ? 100 : c < -1 ? 0 : 30)),
    brake_pct: change.map((c) => (c < -1 ? 80 : 0)),
    gear: speed.map((v) => Math.min(6, 2 + Math.floor(v / 60))),
    rpm: speed.map(() => 7000),
    x: pts.map((p) => Math.round(p.x * 10) / 10),
    z: pts.map((p) => Math.round(p.z * 10) / 10),
  };
}

/** A pit lap: the last stretch in the pit lane, the cut-scene jumping the car
 * 130 m in a frame. */
function pitLap(): Trace {
  const lap = sampleLap(6);
  const cut = Math.floor(POINTS * 0.85);
  const shift = (v: number, i: number) => (i >= cut ? v + 130 : v);
  const t = lap.t.map((v, i) => (i >= cut ? v - (lap.t[cut]! - lap.t[cut - 1]!) + 0.017 : v));
  return {
    ...lap,
    x: lap.x.map(shift),
    t,
    speed_kph: lap.speed_kph.map((v, i) => (i >= cut - 40 ? 60 : v)),
  };
}

function State({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div data-state-name={name} className="w-full max-w-md min-w-0 space-y-1">
      <p className="text-meta text-muted">{name}</p>
      {children}
    </div>
  );
}

function Sample({
  name,
  a,
  b = null,
  at = null,
  mode: initial = "pedals",
  loading = false,
}: {
  name: string;
  a: Trace | null;
  b?: Trace | null;
  at?: number | null;
  mode?: MapMode;
  loading?: boolean;
}) {
  const [cursor] = useState(() => {
    const store = createCursorStore((cb) => cb());
    store.set(at);
    return store;
  });
  const [mode, setMode] = useState<MapMode>(initial);
  return (
    <State name={name}>
      <TrackMap
        a={a}
        b={b}
        lapA={a?.lap ?? null}
        track={NAMES.gilles}
        cursor={cursor}
        onSeek={(x) => cursor.set(x)}
        mode={mode}
        onMode={setMode}
        loading={loading}
      />
    </State>
  );
}

export function MapSamples() {
  const [laps] = useState(() => ({
    a: sampleLap(4),
    b: sampleLap(5, 6, 0.97),
    pit: pitLap(),
  }));
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-6">
      <Sample name="pedals, both laps at the cursor" a={laps.a} b={laps.b} at={30} />
      <Sample name="speed" a={laps.a} b={laps.b} at={30} mode="speed" />
      <Sample name="pit lap, broken at the cut-scene" a={laps.pit} />
      <Sample name="loading" a={null} loading />
      <Sample name="no trace" a={null} />
    </div>
  );
}
