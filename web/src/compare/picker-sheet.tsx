// The lap pickers' sheets (#299 R1): the laps with their times and flags. Lap B's
// also has "From another session": the sessions at this track, by date and car,
// each opening its own laps.
//
// A chunk of its own, loaded when a picker is first pointed at or opened
// (./picker.tsx): it brings Radix's Dialog and Popover, which drawing the
// charts doesn't need (the bundle budget, #237 R6).
import { ChevronDownIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useLaps, type LapRow, type Session } from "@/api/hooks";
import { LapFlag, type LapFlagKind } from "@/components/lap-flag";
import { LapTime } from "@/components/lap-time";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { sessionDate } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A lap's flags, as the lap table shows them. */
function flags(lap: LapRow): LapFlagKind[] {
  const out: LapFlagKind[] = [];
  if (lap.pit) out.push("pit");
  if (lap.out_lap) out.push("out");
  if (lap.invalid) out.push("partial");
  if (lap.restart) out.push("restart");
  return out;
}

function LapList({
  laps,
  selected,
  onPick,
  label,
}: {
  laps: readonly LapRow[];
  selected: number | null;
  onPick: (lap: number) => void;
  label: string;
}) {
  return (
    <ul aria-label={label} className="divide-y divide-border">
      {laps.map((lap) => {
        const on = lap.lap === selected;
        return (
          <li key={lap.lap} className="flex items-center gap-2 px-4">
            <button
              type="button"
              aria-pressed={on}
              data-lap={lap.lap}
              onClick={() => onPick(lap.lap)}
              className={cn(
                "flex min-h-11 flex-1 items-center justify-between gap-3 rounded-md border border-transparent px-2 text-left hover:border-border-strong",
                on && "border-border-strong bg-surface-raised",
              )}
            >
              <span>Lap {lap.lap}</span>
              <LapTime ms={lap.time_ms} best={lap.best} invalid={lap.invalid} />
            </button>
            <span className="flex w-32 shrink-0 flex-wrap justify-end gap-1">
              {flags(lap).map((f) => (
                <LapFlag key={f} flag={f} />
              ))}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function PickerSheet({
  title,
  description,
  open,
  onOpenChange,
  children,
}: SheetProps & { title: string; description: string; children: ReactNode }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:mx-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
}

export function LapASheet({
  laps,
  selected,
  onPick,
  open,
  onOpenChange,
}: SheetProps & {
  laps: readonly LapRow[];
  selected: number | null;
  onPick: (lap: number) => void;
}) {
  return (
    <PickerSheet title="Lap A" description="Drawn solid, in red." open={open} onOpenChange={onOpenChange}>
      <LapList
        laps={laps}
        selected={selected}
        label="Laps in this session"
        onPick={(n) => {
          onPick(n);
          onOpenChange(false);
        }}
      />
    </PickerSheet>
  );
}

/** One same-track session in lap B's sheet: its date and car, and its laps once opened. */
function OtherSession({
  session,
  selected,
  onPick,
}: {
  session: Session;
  selected: number | null;
  onPick: (lap: number) => void;
}) {
  const [open, setOpen] = useState(selected !== null);
  const name = `${sessionDate(session.started_at)} · ${session.car ?? "Unknown car"}`;
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center justify-between gap-2 px-4 py-1 text-left hover:bg-surface-raised"
      >
        <span className="min-w-0">
          <span className="block truncate">{name}</span>
          <span className="block truncate text-meta text-muted">{session.kind_label}</span>
        </span>
        <ChevronDownIcon aria-hidden="true" className={cn("size-4 shrink-0", open && "rotate-180")} />
      </button>
      {open && <OtherSessionLaps id={session.session_id} name={name} selected={selected} onPick={onPick} />}
    </li>
  );
}

/** An opened same-track session's laps: asked for only once it is opened. */
function OtherSessionLaps({
  id,
  name,
  selected,
  onPick,
}: {
  id: string;
  name: string;
  selected: number | null;
  onPick: (lap: number) => void;
}) {
  const laps = useLaps(id);
  if (laps.data) {
    return <LapList laps={laps.data.laps} selected={selected} onPick={onPick} label={`Laps in ${name}`} />;
  }
  if (laps.isError) {
    return <p className="px-4 py-2 text-sm text-muted">Couldn't load that session's laps.</p>;
  }
  return <Skeleton className="mx-4 my-2 h-11" />;
}

export function LapBSheet({
  laps,
  selected,
  bSession,
  sessionId,
  sameTrack,
  onPick,
  open,
  onOpenChange,
}: SheetProps & {
  laps: readonly LapRow[];
  selected: number | null;
  bSession: string;
  sessionId: string;
  sameTrack: readonly Session[] | undefined;
  onPick: (lap: number, session: string) => void;
}) {
  const pick = (session: string) => (n: number) => {
    onPick(n, session);
    onOpenChange(false);
  };
  return (
    <PickerSheet title="Lap B" description="Drawn dashed, in white." open={open} onOpenChange={onOpenChange}>
      <section aria-labelledby="lap-b-this">
        <h3 id="lap-b-this" className="px-4 text-meta tracking-label text-muted uppercase">
          This session
        </h3>
        <LapList
          laps={laps}
          selected={bSession === sessionId ? selected : null}
          label="Laps in this session"
          onPick={pick(sessionId)}
        />
      </section>
      <section aria-labelledby="lap-b-other">
        <h3 id="lap-b-other" className="px-4 pt-2 text-meta tracking-label text-muted uppercase">
          From another session
        </h3>
        {sameTrack === undefined ? (
          <Skeleton className="mx-4 my-2 h-11" />
        ) : sameTrack.length === 0 ? (
          <p className="px-4 py-2 text-sm text-muted">No other session at this track yet.</p>
        ) : (
          <ul aria-label="Sessions at this track" className="divide-y divide-border">
            {sameTrack.map((s) => (
              <OtherSession
                key={s.session_id}
                session={s}
                selected={s.session_id === bSession ? selected : null}
                onPick={pick(s.session_id)}
              />
            ))}
          </ul>
        )}
      </section>
    </PickerSheet>
  );
}
