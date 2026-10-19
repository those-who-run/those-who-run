// A session that is open right now: "Live" with the red dot, or "Paused". The dot is
// `--accent`, so the badge sits on `--bg` or `--surface` only, never on
// `--surface-raised` (docs/design.md, Allowed pairs). The dot pulses, except under
// reduced motion; the word says the state, so the colour is never alone.
import { cn } from "@/lib/utils";

export type LiveState = "live" | "paused";

export function LiveBadge({ state = "live", className }: { state?: LiveState; className?: string }) {
  return (
    <span
      data-slot="live-badge"
      data-state={state}
      className={cn("inline-flex items-center gap-1.5 text-sm font-medium whitespace-nowrap", className)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-2.5 shrink-0 rounded-full",
          state === "live" ? "bg-accent motion-safe:animate-pulse" : "border-2 border-muted",
        )}
      />
      {state === "live" ? "Live" : "Paused"}
    </span>
  );
}
