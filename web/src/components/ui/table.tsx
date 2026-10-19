// shadcn/ui's Table (new-york-v4), restyled through the tokens: `--border` rules,
// muted header cells, tabular figures throughout, and a selected row on
// `--surface-raised`. A row that carries a red mark shows its selection with a
// `--border-strong` edge instead (data-marked), since `--accent` is not allowed on
// the raised fill. Every table has a caption (ADR 0004 point 11).
import type * as React from "react";

import { cn } from "@/lib/utils";

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table data-slot="table" className={cn("w-full caption-bottom text-sm num", className)} {...props} />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors duration-fast data-[state=selected]:bg-surface-raised data-[state=selected]:data-marked:bg-transparent data-[state=selected]:data-marked:outline-1 data-[state=selected]:data-marked:-outline-offset-1 data-[state=selected]:data-marked:outline-border-strong",
        className,
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn("h-11 px-2 text-left align-middle text-meta font-medium whitespace-nowrap text-muted", className)}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td data-slot="table-cell" className={cn("h-11 px-2 align-middle whitespace-nowrap", className)} {...props} />;
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-2 text-left text-meta text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow };
