// Which line is which lap (#299 R2, R3): A's solid accent stroke and B's dashed
// white one, as a short sample beside the letter, so the two never differ by
// colour alone (ADR 0004 point 3).
import { cn } from "@/lib/utils";

export type LapSide = "a" | "b";

export function LapSwatch({ side, className }: { side: LapSide; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-lap={side}
      className={cn(
        "inline-block w-4 align-middle",
        side === "a" ? "border-t-2 border-lap-a" : "border-t-2 border-dashed border-lap-b",
        className,
      )}
    />
  );
}

/** "A" or "B" with its swatch. */
export function LapLetter({ side, className }: { side: LapSide; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-semibold", className)}>
      <LapSwatch side={side} />
      {side === "a" ? "A" : "B"}
    </span>
  );
}
