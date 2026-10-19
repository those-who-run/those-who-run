// A view that failed to load: what failed and what to do, the detail behind a
// disclosure, and Retry (ADR 0004 point 9). It sits where the view would be, so the
// shell keeps working around it. "Couldn't read the session store." / "Retry, or
// check the engineer's logs."
import { CircleAlertIcon, RotateCwIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ErrorState({
  title,
  hint = "Retry, or check the engineer's logs.",
  detail,
  onRetry,
  retrying = false,
  className,
}: {
  /** What failed, in a sentence. */
  title: string;
  /** What to do. */
  hint?: ReactNode;
  /** The error itself (the API's message), shown on request. */
  detail?: string | null;
  onRetry?: () => void;
  retrying?: boolean;
  className?: string;
}) {
  return (
    <section
      role="alert"
      data-slot="error-state"
      className={cn("flex flex-col items-start gap-2 rounded-md border bg-surface p-4", className)}
    >
      <p className="flex items-start gap-2 font-semibold">
        <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent-text" />
        {title}
      </p>
      <p className="text-sm text-muted">{hint}</p>
      {detail && (
        <details className="w-full text-sm">
          <summary className="flex min-h-11 cursor-pointer items-center text-muted hover:text-fg">Details</summary>
          <pre className="font-mono text-meta break-words whitespace-pre-wrap text-muted">{detail}</pre>
        </details>
      )}
      {onRetry && (
        <Button variant="outline" onClick={onRetry} disabled={retrying}>
          <RotateCwIcon aria-hidden="true" />
          {retrying ? "Retrying…" : "Retry"}
        </Button>
      )}
    </section>
  );
}
