// A lap time, anywhere one is shown: a lap row, a stat tile, the session hero. Use
// it rather than lapTime() in a span, so the best lap is always purple and named,
// and an invalid lap is always the muted "—" with words for a screen reader.
import { Loading, SkeletonText } from "@/components/loading";
import { Missing } from "@/components/missing";
import { NUMBER_SIZES, type NumberSize } from "@/components/number-size";
import { lapTime, missing } from "@/lib/format";
import { cn } from "@/lib/utils";

export function LapTime({
  ms,
  best = false,
  invalid = false,
  size = "md",
  className,
}: {
  /** The lap time in milliseconds, as the API sends it. */
  ms: number | null | undefined;
  /** The session's best lap (`LapRow.best`): `--timing-best`, and said. */
  best?: boolean;
  /** No lap time to compare (`LapRow.invalid`): "—", whatever `ms` is. */
  invalid?: boolean;
  size?: NumberSize;
  className?: string;
}) {
  const text = invalid ? missing() : lapTime(ms);
  if (text === missing()) {
    return <Missing label="No lap time" className={cn(NUMBER_SIZES[size], "whitespace-nowrap", className)} />;
  }
  return (
    <span
      data-best={best || undefined}
      className={cn(NUMBER_SIZES[size], "whitespace-nowrap", best && "text-timing-best", className)}
    >
      {text}
      {best && <span className="sr-only"> (best lap)</span>}
    </span>
  );
}

/** Where a lap time will be: "0:00.000" in the same type. */
export function LapTimeSkeleton({ size = "md", className }: { size?: NumberSize; className?: string }) {
  return (
    <Loading inline label="Loading lap time" className={className}>
      <SkeletonText sample="0:00.000" className={NUMBER_SIZES[size]} />
    </Loading>
  );
}
