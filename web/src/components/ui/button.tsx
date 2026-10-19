// shadcn/ui's Button (new-york), copied in by `shadcn add button` and owned here.
// Its colours are Tailwind defaults until #294's tokens and #295's kit restyle it.
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-neutral-900 text-white hover:bg-neutral-700",
        outline: "border border-neutral-300 hover:bg-neutral-100",
        link: "underline-offset-4 hover:underline",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Button({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, className }))} {...props} />;
}

// eslint-disable-next-line react-refresh/only-export-components -- shadcn's layout
export { Button, buttonVariants };
