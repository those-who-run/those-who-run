// A gap to a reference lap: the lap table's gap column, compare's delta. The sign is
// always shown, so the colour (green faster, amber slower, purple for the best lap
// itself) is never the only cue (ADR 0004 point 3).
import { Loading, SkeletonText } from "@/components/loading";
import { Missing } from "@/components/missing";
import { NUMBER_SIZES, type NumberSize } from "@/components/number-size";
import { gap, missing } from "@/lib/format";
import { cn } from "@/lib/utils";

type GapTrend = "faster" | "slower" | "even" | "best";

const TREND_CLASS: Record<GapTrend, string> = {
  faster: "text-timing-improve",
  slower: "text-timing-slower",
  even: "text-fg",
  best: "text-timing-best",
};

/** Which way a gap goes, as format.gap writes it: whole milliseconds, so −0.4 ms is even. */
function gapTrend(ms: number, best = false): GapTrend {
  if (best) {
    return "best";
  }
  const whole = Math.trunc(ms);
  return whole < 0 ? "faster" : whole > 0 ? "slower" : "even";
}

export function Gap({
  ms,
  best = false,
  size = "md",
  className,
}: {
  /** The gap in milliseconds: negative is faster than the reference. */
  ms: number | null | undefined;
  /** This is the reference (the best lap): "Best". */
  best?: boolean;
  size?: NumberSize;
  className?: string;
}) {
  const text = gap(ms, { best });
  if (text === missing()) {
    return <Missing label="No gap" className={cn(NUMBER_SIZES[size], "whitespace-nowrap", className)} />;
  }
  const trend = gapTrend(ms ?? 0, best);
  return (
    <span data-trend={trend} className={cn(NUMBER_SIZES[size], "whitespace-nowrap", TREND_CLASS[trend], className)}>
      {text}
    </span>
  );
}

/** Where a gap will be: "+0.000" in the same type. */
export function GapSkeleton({ size = "md", className }: { size?: NumberSize; className?: string }) {
  return (
    <Loading inline label="Loading gap" className={className}>
      <SkeletonText sample="+0.000" className={NUMBER_SIZES[size]} />
    </Loading>
  );
}
