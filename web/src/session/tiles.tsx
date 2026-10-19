// The session's figures as stat tiles (#298 R2): two across on a phone, four from
// 768 px. Each is the kit's StatTile with its value from format.ts.
import type { LapRow, Session } from "@/api/hooks";
import { StatTile, StatTileSkeleton } from "@/components/stat-tile";
import { duration, fuelAmount, fuelPct, fuelPerLap as fuelPerLapText, lapTime, missing } from "@/lib/format";

import { bestLap, cleanAverage, fuelOnScale, fuelPerLap, fuelScale } from "./model";

const GRID = "grid grid-cols-2 gap-3 md:grid-cols-4";

const LABELS = ["Best lap", "Average", "Laps", "Fuel used", "Pit stops", "Driving"];

function FuelTile({ s, laps }: { s: Session; laps: LapRow[] }) {
  if (s.fuel_use === false) {
    return <StatTile label="Fuel used" value={fuelPct(null, { fuelUse: false })} />;
  }
  const pct = fuelScale(s) === "pct";
  const used = fuelOnScale(s.fuel_used, s);
  const perLap = fuelPerLap(laps, s);
  const text = (v: number | null) => (pct ? fuelPct(v) : fuelAmount(v));
  const perLapText = pct ? fuelPerLapText(perLap) : fuelAmount(perLap);
  return (
    <StatTile
      label="Fuel used"
      value={text(used)}
      sub={
        perLap == null ? (pct ? "of a tank" : "in GT7's units") : (
          <>
            <span className="whitespace-nowrap">{perLapText}</span> per lap
          </>
        )
      }
    />
  );
}

export function SessionTiles({ session: s, laps }: { session: Session; laps: LapRow[] }) {
  const best = bestLap(laps);
  const bestMs = best?.time_ms ?? s.best_lap_ms;
  const bestNo = best?.lap ?? s.best_lap_no;
  const avg = cleanAverage(laps);
  return (
    <section aria-label="Summary" className={GRID}>
      <StatTile
        label="Best lap"
        tone="best"
        value={lapTime(bestMs)}
        sub={bestNo != null ? `lap ${bestNo}` : undefined}
      />
      <StatTile
        label="Average"
        value={avg.ms != null ? lapTime(avg.ms) : missing()}
        sub={avg.count ? `of ${avg.count} clean lap${avg.count === 1 ? "" : "s"}` : "no clean laps"}
      />
      <StatTile
        label="Laps"
        value={String(s.laps_completed)}
        sub={s.total_laps ? `of ${s.total_laps}` : undefined}
      />
      <FuelTile s={s} laps={laps} />
      <StatTile label="Pit stops" value={String(s.pit_stops)} />
      <StatTile
        label="Driving"
        value={duration(s.driving_ms)}
        sub={s.paused_ms ? `paused ${duration(s.paused_ms)}` : undefined}
      />
    </section>
  );
}

export function SessionTilesSkeleton() {
  return (
    <div className={GRID}>
      {LABELS.map((label) => (
        <StatTileSkeleton key={label} label={label} />
      ))}
    </div>
  );
}
