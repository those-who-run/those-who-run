// shadcn/ui's Toggle (new-york-v4), restyled through the tokens: 44 px, muted when
// off, and when on, white on `--surface-raised` with a `--border-strong` edge, so on
// and off differ by more than a fill. Screen readers hear aria-pressed.
import { cva, type VariantProps } from "class-variance-authority";
import { Toggle as TogglePrimitive } from "radix-ui";
import type * as React from "react";

import { cn } from "@/lib/utils";

const toggleVariants = cva(
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium whitespace-nowrap text-muted transition-colors duration-fast hover:text-fg disabled:pointer-events-none disabled:opacity-50 data-[state=on]:border-border-strong data-[state=on]:bg-surface-raised data-[state=on]:text-fg [&_svg]:pointer-events-none [&_svg]:size-5 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-transparent",
        outline: "border-border",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Toggle({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return <TogglePrimitive.Root data-slot="toggle" className={cn(toggleVariants({ variant, className }))} {...props} />;
}

// eslint-disable-next-line react-refresh/only-export-components -- shadcn's layout
export { Toggle, toggleVariants };
