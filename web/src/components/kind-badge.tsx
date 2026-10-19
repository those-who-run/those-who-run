// What sort of session it was: the API's `kind_label` ("12-lap race", "time trial"),
// as the results card names it. The label comes from Python (ADR 0004 point 6), so
// never build one here. An unknown kind is muted.
import { Badge } from "@/components/ui/badge";

export function KindBadge({ label, kind, className }: { label: string; kind?: string; className?: string }) {
  return (
    <Badge variant={kind === "unknown" ? "muted" : "outline"} data-kind={kind} className={className}>
      {label}
    </Badge>
  );
}
