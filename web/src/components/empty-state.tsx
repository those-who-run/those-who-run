// A view with nothing to show: what is missing, why, and what to do next (ADR 0004
// point 9). "No sessions in Willow Springs yet" / "Drive a lap with the engineer
// running." The action is optional: a Button, or a link styled as one.
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  why,
  action,
  headingLevel = 3,
  className,
}: {
  title: string;
  why: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3 | 4;
  className?: string;
}) {
  const Heading = `h${headingLevel}` as const;
  return (
    <section
      data-slot="empty-state"
      className={cn("flex flex-col items-start gap-2 rounded-md border border-dashed p-6", className)}
    >
      <Heading className="text-lg font-semibold">{title}</Heading>
      <p className="text-muted">{why}</p>
      {action && <div className="mt-2">{action}</div>}
    </section>
  );
}
