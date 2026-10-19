// Loading, as the kit draws it (ADR 0004 point 9): a skeleton shaped like the
// content, shown only after 150 ms, so a fast answer never flashes grey. Until then
// the skeleton keeps its space but is invisible, so nothing jumps either way.
// Every data component's `…Skeleton` is built from these.
import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** How long a load may take before its skeleton shows. */
export const SKELETON_DELAY_MS = 150;

/** False until `ms` have passed since the first render. */
function useAfter(ms: number): boolean {
  const [done, setDone] = useState(ms <= 0);
  useEffect(() => {
    if (ms <= 0) {
      return;
    }
    const timer = setTimeout(() => setDone(true), ms);
    return () => clearTimeout(timer);
  }, [ms]);
  return done;
}

/** Holds a skeleton's place, and shows it after `delay` ms. `label` is what a screen
 * reader hears: "Loading sessions". */
export function Loading({
  label,
  inline = false,
  delay = SKELETON_DELAY_MS,
  className,
  children,
}: {
  label: string;
  inline?: boolean;
  delay?: number;
  className?: string;
  children: ReactNode;
}) {
  const shown = useAfter(delay);
  const Tag = inline ? "span" : "div";
  return (
    <Tag
      role="status"
      aria-label={label}
      data-slot="loading"
      data-shown={shown || undefined}
      className={cn(!shown && "invisible", inline && "inline-block", className)}
    >
      {children}
    </Tag>
  );
}

/** A grey block exactly the size of `sample` set in the same type: a lap time's
 * skeleton is "0:00.000" in the lap time's font, so the real value lands on it. */
export function SkeletonText({ sample, className }: { sample: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-slot="skeleton"
      className={cn(
        "inline-block max-w-full overflow-hidden rounded-sm bg-surface-raised align-bottom whitespace-nowrap motion-safe:animate-pulse",
        className,
      )}
    >
      <span className="invisible">{sample}</span>
    </span>
  );
}
