// The laps table (#298 R3 to R5): a semantic <table> with a sticky header, the
// flags as LapFlag badges in the Lap cell, the best lap in the timing-best style
// and partial laps muted. Each row has a 44 px checkbox to pick it for compare.
//
// On a phone (below 640 px) it shows Lap, Time, Gap and Pos; the fuel and top
// speed move into a second row, a <td colspan>, that opens on a tap of the row or
// of the lap number (a button, for the keyboard). From 640 px every column shows.
import { ChevronDownIcon } from "lucide-react";
import { Fragment, useState, type MouseEvent } from "react";

import type { LapRow, Session } from "@/api/hooks";
import { Gap } from "@/components/gap";
import { LapFlag } from "@/components/lap-flag";
import { LapTime } from "@/components/lap-time";
import { Loading, SkeletonText } from "@/components/loading";
import { Position } from "@/components/position";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fuelAmount, fuelPct, fuelPerLap, speedKph } from "@/lib/format";
import { cn } from "@/lib/utils";

import { bestLap, fuelOnScale, fuelScale, lapFlags } from "./model";

/** Shown from 640 px only; on a phone the expanding row has it. */
const WIDE = "hidden sm:table-cell";
const TABLE = "w-full text-sm num sm:text-base";
const HEAD = "sticky top-header z-10 bg-bg";

/** What a lap's fuel and top speed read, on the session's fuel scale. */
function lapExtras(l: LapRow, s: Session) {
  const fuelUse = l.fuel_use && s.fuel_use !== false;
  const pct = fuelScale(s) === "pct";
  const used = fuelOnScale(l.fuel_used, s);
  const left = fuelOnScale(l.fuel_end, s);
  return {
    fuelUse,
    used: pct ? fuelPerLap(used, { fuelUse }) : fuelAmount(used, { fuelUse }),
    left: pct ? fuelPct(left, { fuelUse }) : fuelAmount(left, { fuelUse }),
    top: speedKph(l.top_speed_kph),
  };
}

/** A click on the row itself, not on a checkbox, button or link in it. */
function onRowItself(e: MouseEvent): boolean {
  return !(e.target as Element).closest("button, a, input, label, [role=dialog]");
}

export function LapsTable({
  session: s,
  laps,
  picks,
  onPick,
  inProgress,
}: {
  session: Session;
  laps: LapRow[];
  /** The laps picked for compare, oldest first. */
  picks: number[];
  onPick: (lap: number) => void;
  /** While live: the lap being driven, the table's last row. */
  inProgress?: number | null;
}) {
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const toggle = (lap: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(lap)) {
        next.add(lap);
      }
      return next;
    });

  const best = bestLap(laps);
  const showPos = s.position_shown;
  const showFuel = s.fuel_use !== false;
  // Pick, Lap, Time, Gap, [Pos], [Fuel used, Fuel left], Top km/h
  const columns = 5 + (showPos ? 1 : 0) + (showFuel ? 2 : 0);
  const phoneColumns = 4 + (showPos ? 1 : 0);
  const fuelUnit = fuelScale(s) === "pct" ? "" : " (units)";

  return (
    <table className={TABLE} aria-describedby="laps-help">
      <caption className="pb-2 text-left">
        <span className="block text-xl font-semibold">Laps</span>
        <span id="laps-help" className="block text-sm text-muted">
          Pick two to compare.<span className="sm:hidden"> Tap a lap for its fuel and top speed.</span>
        </span>
      </caption>
      <TableHeader className={HEAD}>
        <TableRow>
          <TableHead className="w-11 px-0">
            <span className="sr-only">Pick to compare</span>
          </TableHead>
          <TableHead>Lap</TableHead>
          <TableHead>Time</TableHead>
          <TableHead>Gap</TableHead>
          {showPos && <TableHead>Pos</TableHead>}
          {showFuel && <TableHead className={WIDE}>Fuel used{fuelUnit}</TableHead>}
          {showFuel && <TableHead className={WIDE}>Fuel left{fuelUnit}</TableHead>}
          <TableHead className={WIDE}>Top km/h</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {laps.map((l) => {
          const x = lapExtras(l, s);
          const picked = picks.includes(l.lap);
          const expanded = open.has(l.lap);
          const isBest = best?.lap === l.lap;
          const detailId = `lap-${l.lap}-detail`;
          return (
            <Fragment key={l.lap}>
              <TableRow
                data-lap={l.lap}
                data-best={isBest || undefined}
                data-partial={l.invalid || undefined}
                data-state={picked ? "selected" : undefined}
                data-marked={picked ? "" : undefined}
                onClick={(e) => onRowItself(e) && toggle(l.lap)}
                className={cn("max-sm:cursor-pointer", l.invalid && "text-muted", expanded && "max-sm:border-b-0")}
              >
                <TableCell className="w-11 px-0">
                  <label className="flex size-11 cursor-pointer items-center justify-center">
                    <input
                      type="checkbox"
                      className="size-5 cursor-pointer accent-fg"
                      checked={picked}
                      onChange={() => onPick(l.lap)}
                      aria-label={`Pick lap ${l.lap} to compare`}
                    />
                  </label>
                </TableCell>
                <TableCell className="py-0">
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className="-ml-2 flex min-h-11 min-w-11 cursor-pointer items-center gap-0.5 px-2 sm:hidden"
                      aria-expanded={expanded}
                      aria-controls={expanded ? detailId : undefined}
                      aria-label={`Lap ${l.lap}: fuel and top speed`}
                      onClick={() => toggle(l.lap)}
                    >
                      {l.lap}
                      <ChevronDownIcon
                        aria-hidden="true"
                        className={cn("size-4 text-muted transition-transform duration-fast", expanded && "rotate-180")}
                      />
                    </button>
                    <span className="hidden sm:inline">{l.lap}</span>
                    {lapFlags(l).map((f) => (
                      <LapFlag key={f} flag={f} className="-my-1" />
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <LapTime ms={l.time_ms} best={isBest} invalid={l.invalid} size="sm" className="sm:text-base" />
                </TableCell>
                <TableCell>
                  <Gap
                    ms={!l.invalid && l.time_ms != null && best?.time_ms != null ? l.time_ms - best.time_ms : null}
                    best={isBest}
                    size="sm"
                    className="sm:text-base"
                  />
                </TableCell>
                {showPos && (
                  <TableCell>
                    <Position position={l.position} size="sm" className="sm:text-base" />
                  </TableCell>
                )}
                {showFuel && <TableCell className={WIDE}>{x.used}</TableCell>}
                {showFuel && <TableCell className={WIDE}>{x.left}</TableCell>}
                <TableCell className={WIDE}>{x.top}</TableCell>
              </TableRow>
              {expanded && (
                <TableRow id={detailId} data-detail={l.lap} className="sm:hidden">
                  <TableCell colSpan={phoneColumns} className="h-auto pt-0 pb-3 whitespace-normal">
                    <dl className="flex flex-wrap gap-x-4 gap-y-1 pl-11 text-sm">
                      {showFuel && (
                        <div className="flex gap-1">
                          <dt className="text-muted">Fuel used{fuelUnit}</dt>
                          <dd>{x.used}</dd>
                        </div>
                      )}
                      {showFuel && (
                        <div className="flex gap-1">
                          <dt className="text-muted">Fuel left{fuelUnit}</dt>
                          <dd>{x.left}</dd>
                        </div>
                      )}
                      {!showFuel && (
                        <div className="flex gap-1">
                          <dt className="text-muted">Fuel</dt>
                          <dd>Fuel off</dd>
                        </div>
                      )}
                      <div className="flex gap-1">
                        <dt className="text-muted">Top speed</dt>
                        <dd>{x.top}</dd>
                      </div>
                    </dl>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
        {inProgress != null && (
          <TableRow data-in-progress={inProgress}>
            <TableCell colSpan={columns} className="text-muted">
              <span className="pl-11">Lap {inProgress} in progress</span>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </table>
  );
}

/** The table while the laps load: its header and three rows of grey. */
export function LapsTableSkeleton() {
  return (
    <Loading label="Loading the lap table">
      <p className="pb-2 text-xl font-semibold">Laps</p>
      <div className="space-y-px">
        {[1, 2, 3].map((n) => (
          <div key={n} className="flex h-11 items-center gap-4 border-b pl-11 text-sm">
            <SkeletonText sample="00" />
            <SkeletonText sample="0:00.000" />
            <SkeletonText sample="+0.000" />
          </div>
        ))}
      </div>
    </Loading>
  );
}
