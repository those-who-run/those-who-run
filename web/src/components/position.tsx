// A finishing or running position: "P3" with a muted "/16". Hidden when the API says
// a position means nothing here (`position_shown`): a solo run has no field. Use it
// wherever a position appears, so a screen reader hears "Position 3 of 16".
import { Loading, SkeletonText } from "@/components/loading";
import { Missing } from "@/components/missing";
import { NUMBER_SIZES, type NumberSize } from "@/components/number-size";
import { missing, position as formatPosition } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The field size is smaller than the position: `/16` beside a 56 px `P1`. */
const OF_SIZES: Record<NumberSize, string> = {
  sm: "",
  md: "",
  xl: "text-2xl",
};

export function Position({
  position,
  cars,
  shown = true,
  size = "md",
  className,
}: {
  position: number | null | undefined;
  cars?: number | null;
  /** The API's `position_shown`: false hides the position altogether. */
  shown?: boolean;
  size?: NumberSize;
  className?: string;
}) {
  if (!shown) {
    return null;
  }
  const p = formatPosition(position, cars);
  if (p.position === missing()) {
    return <Missing label="Position unknown" className={cn(NUMBER_SIZES[size], "whitespace-nowrap", className)} />;
  }
  const spoken = `Position ${p.position.slice(1)}${p.of ? ` of ${p.of.slice(1)}` : ""}`;
  return (
    <span data-slot="position" className={cn(NUMBER_SIZES[size], "whitespace-nowrap", className)}>
      <span aria-hidden="true">
        {p.position}
        {p.of && <span className={cn("text-muted", OF_SIZES[size])}>{p.of}</span>}
      </span>
      <span className="sr-only">{spoken}</span>
    </span>
  );
}

/** Where a position will be: "P00/00" in the same type. */
export function PositionSkeleton({ size = "md", className }: { size?: NumberSize; className?: string }) {
  return (
    <Loading inline label="Loading position" className={className}>
      <SkeletonText sample="P00/00" className={NUMBER_SIZES[size]} />
    </Loading>
  );
}
