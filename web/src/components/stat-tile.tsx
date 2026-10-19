// One figure with its label: the session page's summary row (best lap, race time,
// fuel per lap). The label is the guide's one use of small caps. Pass the value
// already formatted by format.ts; a missing value ("—") is muted and said.
import type { ReactNode } from "react";

import { Loading, SkeletonText } from "@/components/loading";
import { Missing } from "@/components/missing";
import { missing } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONES = {
  plain: "",
  best: "text-timing-best",
} as const;

const FRAME = "flex min-w-0 flex-col gap-1 rounded-md border bg-surface p-4";
const LABEL = "text-meta font-medium tracking-label text-muted uppercase";

export function StatTile({
  label,
  value,
  sub,
  tone = "plain",
  className,
}: {
  label: string;
  /** The figure, from format.ts: "1:27.764", "3.2%", "—". */
  value: ReactNode;
  /** A line under it: "lap 4", "of 12 laps". */
  sub?: ReactNode;
  /** `best` for the session's best lap (`--timing-best`). */
  tone?: keyof typeof TONES;
  className?: string;
}) {
  return (
    <div data-slot="stat-tile" className={cn(FRAME, className)}>
      <p className={LABEL}>{label}</p>
      <p className={cn("num-lg whitespace-nowrap", TONES[tone])}>
        {value === missing() ? <Missing label="Unknown" /> : value}
      </p>
      {sub && <p className="text-sm text-muted">{sub}</p>}
    </div>
  );
}

/** A stat tile while its figure loads: the label is known, the value and sub-line
 * are grey blocks of their size. */
export function StatTileSkeleton({ label, sub = true, className }: { label: string; sub?: boolean; className?: string }) {
  return (
    <Loading label={`Loading ${label.toLowerCase()}`} className={cn(FRAME, className)}>
      <p className={LABEL}>{label}</p>
      <p className="num-lg">
        <SkeletonText sample="0:00.000" />
      </p>
      {sub && (
        <p className="text-sm">
          <SkeletonText sample="lap 00" />
        </p>
      )}
    </Loading>
  );
}
