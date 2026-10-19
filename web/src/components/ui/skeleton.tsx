// shadcn/ui's Skeleton (new-york-v4), restyled: `--surface-raised`, a 2 px radius,
// and a pulse only where motion is welcome. Data components show it through
// <Loading> (../loading.tsx), which waits 150 ms first.
import type * as React from "react";

import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("rounded-sm bg-surface-raised motion-safe:animate-pulse", className)}
      {...props}
    />
  );
}

export { Skeleton };
