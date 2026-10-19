// The lap pickers (#299 R1): a button per lap showing its pick ("Lap 5 0:59.541"),
// opening a sheet (./picker-sheet.tsx) that lists the laps. The sheets are a chunk
// of their own, fetched when a button is first pointed at, focused or pressed, so
// the charts draw without Radix's Dialog and Popover (the bundle budget, #237 R6).
import { ChevronDownIcon } from "lucide-react";
import { lazy, Suspense, useState, type ComponentProps } from "react";

import type { LapRow } from "@/api/hooks";
import { LapTime } from "@/components/lap-time";
import { cn } from "@/lib/utils";

import { LapLetter, type LapSide } from "./lap-swatch";

const loadSheets = () => import("./picker-sheet");
const LapASheet = lazy(() => loadSheets().then((m) => ({ default: m.LapASheet })));
const LapBSheet = lazy(() => loadSheets().then((m) => ({ default: m.LapBSheet })));

/** Starts fetching the sheets' chunk; a failure shows when a sheet is opened. */
function preload() {
  void loadSheets().catch(() => {});
}

function PickerButton({
  side,
  lap,
  sub,
  open,
  onOpen,
}: {
  side: LapSide;
  lap: LapRow | undefined;
  sub?: string;
  open: boolean;
  onOpen: () => void;
}) {
  const name = side === "a" ? "Lap A" : "Lap B";
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      data-picker={side}
      onPointerEnter={preload}
      onFocus={preload}
      onClick={onOpen}
      className={cn(
        "flex min-h-14 w-full min-w-0 flex-col items-start gap-0.5 rounded-md border bg-surface px-3 py-2 text-left hover:border-border-strong",
        side === "a" ? "border-l-4 border-border border-l-lap-a" : "border-dashed border-lap-b",
      )}
    >
      <span className="flex w-full items-center justify-between text-meta tracking-label text-muted uppercase">
        <LapLetter side={side} />
        <ChevronDownIcon aria-hidden="true" className="size-4" />
      </span>
      <span className="flex flex-wrap items-baseline gap-x-2 font-semibold">
        <span className="sr-only">{name}: </span>
        {lap ? (
          <>
            <span>Lap {lap.lap}</span>
            <LapTime ms={lap.time_ms} best={lap.best} invalid={lap.invalid} />
          </>
        ) : (
          <span className="text-muted">Pick a lap</span>
        )}
      </span>
      {sub && <span className="max-w-full truncate text-meta text-muted">{sub}</span>}
    </button>
  );
}

/** Mounts the sheet once it has been opened, so its chunk is fetched no sooner. */
function useEverOpen(open: boolean): boolean {
  const [ever, setEver] = useState(open);
  if (open && !ever) {
    setEver(true);
  }
  return ever || open;
}

type ASheet = ComponentProps<typeof LapASheet>;
type BSheet = ComponentProps<typeof LapBSheet>;

export function LapAPicker(props: ASheet) {
  const mounted = useEverOpen(props.open);
  return (
    <>
      <PickerButton
        side="a"
        lap={props.laps.find((l) => l.lap === props.selected)}
        open={props.open}
        onOpen={() => props.onOpenChange(true)}
      />
      {mounted && (
        <Suspense fallback={null}>
          <LapASheet {...props} />
        </Suspense>
      )}
    </>
  );
}

export function LapBPicker({ bLaps, sub, ...props }: BSheet & { bLaps: readonly LapRow[] | undefined; sub?: string }) {
  const mounted = useEverOpen(props.open);
  const rows = props.bSession === props.sessionId ? props.laps : bLaps;
  return (
    <>
      <PickerButton
        side="b"
        lap={rows?.find((l) => l.lap === props.selected)}
        sub={sub}
        open={props.open}
        onOpen={() => props.onOpenChange(true)}
      />
      {mounted && (
        <Suspense fallback={null}>
          <LapBSheet {...props} />
        </Suspense>
      )}
    </>
  );
}
