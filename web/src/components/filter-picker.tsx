// Filters, as a list page sets them (#297 R5): a row of chips, each opening its
// options in a bottom sheet below 640 px and a popover from 640 px; the options with
// how many sessions each would leave; and the active filters as removable chips
// with "Clear all". Every target is 44 px. /_kit shows each state.
import { ChevronDownIcon, XIcon } from "lucide-react";
import { useState, useSyncExternalStore, type ComponentProps, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

/** From 640 px a picker opens as a popover; below it, as a bottom sheet. */
const WIDE = "(min-width: 640px)";

/** The query, where the browser has matchMedia (jsdom doesn't). */
function wideQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(WIDE) : null;
}

function useWide(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = wideQuery();
      query?.addEventListener("change", changed);
      return () => query?.removeEventListener("change", changed);
    },
    () => wideQuery()?.matches ?? false,
    () => false,
  );
}

/** A filter's chip: "Track ▾", raised with a `--border-strong` edge when set. */
export function FilterChip({ label, active = false, ...props }: { label: string; active?: boolean } & ComponentProps<"button">) {
  return (
    <Button
      variant="outline"
      data-slot="filter-chip"
      data-active={active || undefined}
      className={cn(active && "border-border-strong bg-surface-raised")}
      {...props}
    >
      {label}
      {active && <span className="sr-only"> (set)</span>}
      <ChevronDownIcon aria-hidden="true" />
    </Button>
  );
}

/** A filter chip that opens its options. `layout` is the viewport's ("auto") unless
 * /_kit asks for one. `children` gets a function that closes it. */
export function FilterPicker({
  label,
  active = false,
  description,
  layout = "auto",
  children,
}: {
  label: string;
  active?: boolean;
  /** What the sheet's heading says under the label: "Show only one track." */
  description: string;
  layout?: "auto" | "sheet" | "popover";
  children: (close: () => void) => ReactNode;
}) {
  const wide = useWide();
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const trigger = <FilterChip label={label} active={active} />;
  if (layout === "popover" || (layout === "auto" && wide)) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent
          align="start"
          aria-label={label}
          className="max-h-(--radix-popover-content-available-height) w-80 overflow-y-auto p-2"
        >
          {children(close)}
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent>
        <SheetHeader className="pb-0">
          <SheetTitle>{label}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        <div className="px-2">{children(close)}</div>
      </SheetContent>
    </Sheet>
  );
}

export interface FilterOption {
  value: string;
  label: string;
  /** Sessions this value would leave; 0 is shown but can't be picked. */
  count: number;
}

/** A picker's options: "Any track" first, then each value with its count. The
 * picked one is pressed. Picking calls `onPick` with the value, "" for any. */
export function FilterOptions({
  label,
  any,
  current,
  options,
  onPick,
}: {
  label: string;
  any: string;
  current: string | undefined;
  options: FilterOption[];
  onPick: (value: string) => void;
}) {
  return (
    <ul aria-label={label} data-slot="filter-options" className="space-y-0.5">
      {[{ value: "", label: any, count: null as number | null }, ...options].map((o) => {
        const selected = (current ?? "") === o.value;
        return (
          <li key={o.value || "any"}>
            <Button
              variant="ghost"
              aria-pressed={selected}
              disabled={o.count === 0 && !selected}
              className={cn(
                "h-auto w-full justify-between gap-3 py-2 text-left text-base font-normal whitespace-normal",
                selected && "bg-surface-raised",
              )}
              onClick={() => onPick(o.value)}
            >
              <span className="min-w-0 break-words">{o.label}</span>
              {o.count !== null && <span className="num shrink-0 text-sm text-muted">{o.count}</span>}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

export interface ActiveFilter {
  key: string;
  /** The value as the chip shows it: "Suzuka Circuit East Course", "17 Oct – 18 Oct". */
  label: string;
  remove: () => void;
}

/** The filters that are set, each a chip that removes it, and "Clear all". Nothing
 * when none is set. */
export function ActiveFilters({ filters, onClear }: { filters: ActiveFilter[]; onClear: () => void }) {
  if (filters.length === 0) {
    return null;
  }
  return (
    <ul aria-label="Active filters" data-slot="active-filters" className="flex flex-wrap items-center gap-2">
      {filters.map((f) => (
        <li key={f.key} className="max-w-full min-w-0">
          <Button
            variant="outline"
            className="max-w-full border-border-strong"
            aria-label={`Remove filter: ${f.label}`}
            onClick={f.remove}
          >
            <span className="truncate">{f.label}</span>
            <XIcon aria-hidden="true" />
          </Button>
        </li>
      ))}
      <li>
        <Button variant="link" onClick={onClear}>
          Clear all
        </Button>
      </li>
    </ul>
  );
}
