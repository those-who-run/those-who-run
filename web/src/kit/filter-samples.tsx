// The filter pattern's states for /_kit (#297 R5, ADR 0004 point 8): the chip idle
// and set, the picker as a bottom sheet and as a popover, the options with their
// counts (one at 0, which can't be picked), and the active filters with "Clear all".
// Kept apart from kit.tsx so the kit's page only places it.
import { useState, type ReactNode } from "react";

import {
  ActiveFilters,
  FilterOptions,
  FilterPicker,
  type ActiveFilter,
  type FilterOption,
} from "@/components/filter-picker";

import { NAMES } from "./samples";

const TRACKS: FilterOption[] = [
  { value: NAMES.gilles, label: NAMES.gilles, count: 12 },
  { value: NAMES.suzuka, label: NAMES.suzuka, count: 3 },
  { value: NAMES.willow, label: NAMES.willow, count: 0 },
];

function State({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div data-state-name={name} className="min-w-0 space-y-1">
      <p className="text-meta text-muted">{name}</p>
      <div className="flex min-h-11 flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

/** A picker with the sample tracks, remembering what was picked. */
function TrackPicker({ label, layout, initial }: { label: string; layout?: "sheet" | "popover"; initial?: string }) {
  const [current, setCurrent] = useState(initial);
  return (
    <FilterPicker label={label} active={current !== undefined} description="Show only one track." layout={layout}>
      {(close) => (
        <FilterOptions
          label={label}
          any="Any track"
          current={current}
          options={TRACKS}
          onPick={(value) => {
            setCurrent(value || undefined);
            close();
          }}
        />
      )}
    </FilterPicker>
  );
}

function Active() {
  const all: ActiveFilter[] = [
    { key: "track", label: NAMES.willow, remove: () => {} },
    { key: "kind", label: "lap race", remove: () => {} },
    { key: "date", label: "17 Oct – 18 Oct", remove: () => {} },
  ];
  const [keys, setKeys] = useState(all.map((f) => f.key));
  const shown = all
    .filter((f) => keys.includes(f.key))
    .map((f) => ({ ...f, remove: () => setKeys((k) => k.filter((x) => x !== f.key)) }));
  return shown.length ? (
    <ActiveFilters filters={shown} onClear={() => setKeys([])} />
  ) : (
    <button
      type="button"
      className="min-h-11 text-sm text-muted underline underline-offset-4"
      onClick={() => setKeys(all.map((f) => f.key))}
    >
      Put them back
    </button>
  );
}

export function FilterSamples() {
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-4">
      <State name="chip">
        <TrackPicker label="Track" />
      </State>
      <State name="chip, set">
        <TrackPicker label="Track" initial={NAMES.suzuka} />
      </State>
      <State name="picker: bottom sheet (below 640 px)">
        <TrackPicker label="Track" layout="sheet" />
      </State>
      <State name="picker: popover (from 640 px)">
        <TrackPicker label="Track" layout="popover" />
      </State>
      <div data-state-name="options, with counts; 0 can't be picked" className="w-full max-w-80 space-y-1">
        <p className="text-meta text-muted">options, with counts; 0 can't be picked</p>
        <div className="rounded-md border border-border-strong bg-popover p-2">
          <FilterOptions label="Track options" any="Any track" current={NAMES.suzuka} options={TRACKS} onPick={() => {}} />
        </div>
      </div>
      <div data-state-name="active filters, Clear all" className="w-full space-y-1">
        <p className="text-meta text-muted">active filters, Clear all</p>
        <Active />
      </div>
    </div>
  );
}
