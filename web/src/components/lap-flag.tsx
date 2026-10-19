// A lap's flag in the lap table: Pit, Out, Partial or Restart (`LapRow.pit`,
// `out_lap`, `invalid` and `restart`). The word is the flag, so colour carries
// nothing; what it means opens on tap or Enter, in place of the caption the
// Streamlit page had under its table.
import { Explain } from "@/components/explain";
import { badgeVariants } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type LapFlagKind = "pit" | "out" | "partial" | "restart";

const FLAGS: Record<LapFlagKind, { label: string; title: string; text: string }> = {
  pit: {
    label: "Pit",
    title: "Pit lap",
    text: "Fuel went up during the lap: the car stopped in the pits.",
  },
  out: {
    label: "Out",
    title: "Out lap",
    text: "The lap after a pit stop, started from the pit lane.",
  },
  partial: {
    label: "Partial",
    title: "Partial lap",
    text: "The lap the session ended in. It has no lap time.",
  },
  restart: {
    label: "Restart",
    title: "Engineer restarted",
    text: "The engineer restarted during this lap, so part of it wasn't seen.",
  },
};

export function LapFlag({ flag, className }: { flag: LapFlagKind; className?: string }) {
  const f = FLAGS[flag];
  return (
    <Explain
      title={f.title}
      className={className}
      trigger={
        <span
          data-flag={flag}
          className={cn(
            badgeVariants({ variant: "outline" }),
            "transition-colors duration-fast group-hover:border-fg group-data-[state=open]:border-fg",
          )}
        >
          {f.label}
        </span>
      }
    >
      <p>{f.text}</p>
      <p>It isn't counted in averages.</p>
    </Explain>
  );
}
