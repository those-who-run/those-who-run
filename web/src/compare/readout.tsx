// The readout (#299 R4): pinned above the charts, it shows the cursor's time and
// each shown channel's value for lap A and lap B there, so a finger on a chart
// never covers the numbers. Each lap is read at its own nearest sample.
import type { Trace } from "@/api/hooks";
import { missing } from "@/lib/format";
import { cn } from "@/lib/utils";

import { sampleAt } from "./align";
import { X_AXIS, type Channel } from "./channels";
import { useCursor, type CursorStore } from "./cursor";
import { LapLetter, type LapSide } from "./lap-swatch";

function Row({
  side,
  trace,
  x,
  channels,
}: {
  side: LapSide;
  trace: Trace | null;
  x: number | null;
  channels: readonly Channel[];
}) {
  const at = sampleAt(trace, x);
  return (
    <tr data-lap={side} data-index={at?.index}>
      <th scope="row" className="py-0.5 pr-2 text-left font-normal">
        <LapLetter side={side} />
      </th>
      {channels.map((c) => (
        <td key={c.id} data-channel={c.id} className="num py-0.5 pr-2 text-right whitespace-nowrap">
          {trace && at ? c.format(trace[c.field][at.index]) : missing()}
        </td>
      ))}
    </tr>
  );
}

export function Readout({
  cursor,
  a,
  b,
  channels,
  className,
}: {
  cursor: CursorStore;
  a: Trace | null;
  b: Trace | null;
  channels: readonly Channel[];
  className?: string;
}) {
  const x = useCursor(cursor);
  return (
    <div
      data-slot="readout"
      className={cn("overflow-x-auto rounded-md border border-border-strong bg-surface px-3 py-2 text-sm", className)}
    >
      <table className="w-full table-fixed border-collapse">
        <caption className="sr-only">Both laps at the cursor</caption>
        <thead>
          <tr className="text-meta text-muted">
            <th scope="col" data-x={x ?? undefined} className="num py-0.5 pr-2 text-left font-normal whitespace-nowrap">
              <span className="sr-only">Time from the lap's start: </span>
              {x === null ? missing() : `${X_AXIS.format(x)} ${X_AXIS.unit}`}
            </th>
            {channels.map((c) => (
              <th key={c.id} scope="col" className="py-0.5 pr-2 text-right font-normal">
                {c.short}
                <span className="sr-only"> ({c.label})</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <Row side="a" trace={a} x={x} channels={channels} />
          <Row side="b" trace={b} x={x} channels={channels} />
        </tbody>
      </table>
    </div>
  );
}
