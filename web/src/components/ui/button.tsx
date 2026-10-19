// shadcn/ui's Button (new-york-v4), copied in by `shadcn add button` and owned here.
// Its colours are the tokens; docs/design.md (Components) lists what differs from
// upstream. Use it for every action; a link that looks like a button is
// `<Button asChild><Link …/></Button>`. Every size is at least 44 × 44 px.
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-colors duration-fast disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-5 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-accent-hover active:bg-accent-hover",
        outline: "border border-input hover:bg-surface-raised active:bg-surface-raised",
        ghost: "hover:bg-surface-raised active:bg-surface-raised",
        link: "text-accent-text underline-offset-4 hover:underline",
      },
      size: {
        default: "px-4",
        icon: "size-11",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

// eslint-disable-next-line react-refresh/only-export-components -- shadcn's layout
export { Button, buttonVariants };
