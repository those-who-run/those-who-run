// A missing value: the muted "—" from format.ts's missing(), with words for a screen
// reader, which would otherwise read the dash or nothing. LapTime, Gap, Position
// and StatTile show it for a value that is unknown; a page rarely needs it directly.
import { missing } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Missing({ label, className }: { label: string; className?: string }) {
  return (
    <span data-missing="" className={cn("text-muted", className)}>
      <span aria-hidden="true">{missing()}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
