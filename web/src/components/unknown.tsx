// Something the engineer couldn't place: "Unknown track", "Unknown car". Muted, never
// guessed and never hidden, with the reason on tap (ADR 0004 point 9): for a track,
// the API's `track.evidence`. With no reason it is muted text only.
import { Explain } from "@/components/explain";
import { cn } from "@/lib/utils";

export function Unknown({
  label = "Unknown track",
  reason,
  className,
}: {
  label?: string;
  /** Why it is unknown, in a sentence; null when the engineer didn't say. */
  reason?: string | null;
  className?: string;
}) {
  if (!reason) {
    return (
      <span data-slot="unknown" className={cn("text-muted", className)}>
        {label}
      </span>
    );
  }
  return (
    <Explain
      title={label}
      className={cn("justify-start", className)}
      trigger={
        <span
          data-slot="unknown"
          className="text-muted underline decoration-dotted underline-offset-4 group-hover:text-fg group-data-[state=open]:text-fg"
        >
          {label}
        </span>
      }
    >
      <p>{reason}</p>
    </Explain>
  );
}
