// The bar at the bottom of the session page (#298 R5): two laps picked in the table
// make "Compare L2 and L4", a link to lap compare (#299); with none picked it
// offers the best lap against the next fastest. It sticks to the bottom of the
// screen while the table scrolls under it, and rests after the table at the end.
import { Link } from "react-router";

import { Button } from "@/components/ui/button";

import { comparePair, compareHref } from "./model";

export function PickBar({
  sessionId,
  picks,
  fallback,
  onClear,
}: {
  sessionId: string;
  /** The picks, oldest first. */
  picks: number[];
  /** With nothing picked: the best lap and the next fastest, when there are two. */
  fallback: [number, number] | null;
  onClear: () => void;
}) {
  const pair = comparePair(picks);
  if (!picks.length && !fallback) {
    return null;
  }
  return (
    <div
      data-slot="pick-bar"
      role="region"
      aria-label="Compare"
      className="sticky bottom-0 z-20 mt-4 border-t bg-bg pt-2 pb-safe"
    >
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 pb-2">
        {pair ? (
          <Button asChild>
            <Link to={compareHref(sessionId, pair)}>
              Compare L{pair[0]} and L{pair[1]}
            </Link>
          </Button>
        ) : picks.length === 1 ? (
          <p className="text-sm text-muted">L{picks[0]} picked. Pick one more lap to compare.</p>
        ) : (
          <Button asChild variant="outline">
            <Link to={compareHref(sessionId, fallback!)}>Compare best and next fastest</Link>
          </Button>
        )}
        {picks.length > 0 && (
          <Button variant="ghost" onClick={onClear}>
            Clear
          </Button>
        )}
      </div>
    </div>
  );
}
