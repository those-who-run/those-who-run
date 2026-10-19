// An explanation behind a tap: the one way the kit says more about something
// (LapFlag's meaning, Unknown's reason). A Popover, not a tooltip, so it opens by
// tap, click, Enter or Space and closes with Escape; nothing depends on hover (ADR
// 0004 point 7). The trigger is a 44 × 44 px button whatever it draws.
import { useId, type ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function Explain({
  trigger,
  title,
  children,
  className,
}: {
  /** What the button draws: a badge, a muted word. Its text is the button's name. */
  trigger: ReactNode;
  /** The explanation's heading, which names the popover. */
  title: string;
  children: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-slot="explain"
          className={cn(
            "group inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded-md text-left",
            className,
          )}
        >
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent aria-labelledby={titleId} className="space-y-1">
        <p id={titleId} className="font-semibold text-fg">
          {title}
        </p>
        <div className="text-muted">{children}</div>
      </PopoverContent>
    </Popover>
  );
}
