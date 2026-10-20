// The session list, the pit wall's home page (#297): sessions grouped by day,
// newest first, the live session pinned above them, and filters held in the URL so
// Back, a reload and a shared link keep the view. Sessions with no full lap are
// tucked away unless `?all=1`. Filtering happens in the API (#318); this page only
// groups and pages what it is sent.
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { useEngineStatus, useLiveSession, useSessionList, type SessionFilters } from "@/api/hooks";
import type { components } from "@/api/schema";
import { usePageTitle } from "@/app/title";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ActiveFilters, FilterOptions, FilterPicker, type ActiveFilter } from "@/components/filter-picker";
import type { LiveState } from "@/components/live-badge";
import { SessionCard, SessionCardSkeleton } from "@/components/session-card";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { isoDay, shortDay } from "@/lib/format";
import {
  FILTER_KEYS,
  groupByDay,
  liveCardSession,
  PAGE_SIZE,
  parseView,
  restartNote,
  sessions as countSessions,
  withParams,
  type Day,
  type FilterKey,
} from "@/lib/session-list";
import { cn } from "@/lib/utils";

type Session = components["schemas"]["Session"];
type SessionList = components["schemas"]["SessionList"];

/** The cards on the page, kept in the history entry rather than the URL, so Back to
 * the list brings back as many as were shown, and the scroll with them (R6). A new
 * filter is a new entry, and starts from one page again. */
function useShown(): [number, () => void] {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as { shown?: number } | null;
  const shown = state?.shown ?? PAGE_SIZE;
  // A second click can land before the first one's navigation has rendered, while
  // `shown` is still the old count; it builds on what the first asked for, so each
  // click is a page (#379). Every navigation is a new key, so this resets itself.
  const asked = useRef<{ key: string; shown: number } | null>(null);
  const more = () => {
    const from = asked.current?.key === location.key ? asked.current.shown : shown;
    const next = from + PAGE_SIZE;
    asked.current = { key: location.key, shown: next };
    void navigate(
      { search: location.search },
      { replace: true, state: { ...state, shown: next }, preventScrollReset: true },
    );
  };
  return [shown, more];
}

/** The list's view in the URL (R4, R5): reading it, and changing it as a new
 * history entry, so Back undoes a filter. */
function useSessionFilters() {
  const [params, setParams] = useSearchParams();
  const view = useMemo(() => parseView(params), [params]);
  const set = (changes: Partial<Record<FilterKey | "all", string | null>>) =>
    setParams(withParams(params, changes), { preventScrollReset: true });
  return { ...view, set };
}

type SetView = ReturnType<typeof useSessionFilters>["set"];

export function Component() {
  usePageTitle("Sessions");
  const { filters, all, set } = useSessionFilters();
  const engine = useEngineStatus();
  const live = engine.state === "online" ? engine.status.session : null;
  const liveState: LiveState = engine.state === "online" && engine.status.activity === "paused" ? "paused" : "live";
  const list = useSessionList(filters, { live: live !== null });
  const liveInList = live ? list.data?.sessions.find((s) => s.session_id === live.id) : undefined;
  // Filtered out of the list: the live card asks for its session by itself.
  const liveFetched = useLiveSession(live && list.data && !liveInList ? live.id : null);
  const [shown, showMore] = useShown();

  // When the live session ends, the list is asked again at once, so it lands in
  // Today closed rather than on the next focus.
  const liveId = live?.id ?? null;
  const lastLive = useRef(liveId);
  const { refetch } = list;
  useEffect(() => {
    if (lastLive.current !== null && lastLive.current !== liveId) {
      void refetch();
    }
    lastLive.current = liveId;
  }, [liveId, refetch]);

  const [now] = useState(() => Date.now() / 1000);
  const liveSession = live
    ? liveCardSession(
        live,
        liveInList ?? liveFetched.data,
        list.data?.options.kind.find((k) => k.value === live.kind)?.label,
        now,
      )
    : null;

  return (
    <div className="mx-auto w-full space-y-6 xl:max-w-list">
      <h2 className="sr-only">Sessions</h2>
      {liveSession && (
        <section aria-labelledby="sessions-live" className="space-y-2">
          <h3 id="sessions-live" className="text-xl font-semibold">
            On track
          </h3>
          <SessionCard
            session={liveSession}
            live={liveState}
            to={`/sessions/${encodeURIComponent(liveSession.session_id)}`}
            state={{ back: true }}
            headingLevel={4}
          />
        </section>
      )}
      {list.data ? (
        <Listing
          data={list.data}
          filters={filters}
          all={all}
          set={set}
          liveId={liveId}
          shown={shown}
          showMore={showMore}
          busy={list.isPlaceholderData}
        />
      ) : list.isError ? (
        <ErrorState
          title="Couldn't read the session store."
          hint="Retry, or check the pit wall's logs."
          detail={list.error.message}
          onRetry={() => void list.refetch()}
          retrying={list.isFetching}
        />
      ) : (
        <ListSkeleton />
      )}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-3">
      <SessionCardSkeleton />
      <SessionCardSkeleton />
      <SessionCardSkeleton />
    </div>
  );
}

function Listing({
  data,
  filters,
  all,
  set,
  liveId,
  shown,
  showMore,
  busy,
}: {
  data: SessionList;
  filters: SessionFilters;
  all: boolean;
  set: SetView;
  liveId: string | null;
  shown: number;
  showMore: () => void;
  busy: boolean;
}) {
  if (data.total === 0) {
    return (
      <EmptyState
        headingLevel={3}
        title="No sessions yet"
        why={
          <>
            Drive a lap with the engineer running and it appears here.
            <span className="mt-2 block text-sm">
              The pit wall reads the engineer's data directory, <code className="font-mono">GT7_DATA_DIR</code>.
            </span>
          </>
        }
      />
    );
  }
  const clear = () => set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])));
  const { days, more } = groupByDay(data.sessions, { all, limit: shown, liveId });
  return (
    <div className="space-y-6" aria-busy={busy || undefined}>
      <Filters data={data} filters={filters} all={all} set={set} clear={clear} />
      {data.matched === 0 ? (
        <EmptyState
          headingLevel={3}
          title="No sessions match these filters"
          why="Remove a filter, or clear them all."
          action={
            <Button variant="outline" onClick={clear}>
              Clear filters
            </Button>
          }
        />
      ) : (
        <div className={cn("space-y-8 transition-opacity", busy && "opacity-60")}>
          <ul aria-label="Sessions" className="space-y-8">
            {days.map((day) => (
              <li key={day.key}>
                <DaySection day={day} showShort={() => set({ all: "1" })} />
              </li>
            ))}
          </ul>
          {more && (
            <Button variant="outline" className="w-full" onClick={showMore}>
              Show more
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function DaySection({ day, showShort }: { day: Day; showShort: () => void }) {
  const id = `day-${day.key}`;
  return (
    <section aria-labelledby={id} data-day={day.key} className="space-y-3">
      <h3 id={id} className="flex items-baseline gap-2 text-xl font-semibold">
        {day.label}
        <span className="num text-sm font-normal text-muted">{countSessions(day.count)}</span>
      </h3>
      {day.sessions.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
          {day.sessions.map((s) => (
            <li key={s.session_id} className="flex">
              <Card session={s} />
            </li>
          ))}
        </ul>
      )}
      {day.short > 0 && (
        <Button variant="ghost" className="-ml-4 text-muted" onClick={showShort}>
          {countSessions(day.short)} with no full lap{" "}
          <span className="text-accent-text">Show</span>
        </Button>
      )}
    </section>
  );
}

function Card({ session: s }: { session: Session }) {
  const note = restartNote(s);
  return (
    <SessionCard
      session={s}
      to={`/sessions/${encodeURIComponent(s.session_id)}`}
      state={{ back: true }}
      headingLevel={4}
      note={note}
    />
  );
}

/** The day range as its chip says it: "17 Oct", "17 Oct – 18 Oct", "From 17 Oct". */
function dateSummary(from: string | undefined, to: string | undefined): string {
  const year = new Date().getFullYear();
  if (from && to) {
    return from === to ? shortDay(from, year) : `${shortDay(from, year)} – ${shortDay(to, year)}`;
  }
  if (from) {
    return `From ${shortDay(from, year)}`;
  }
  return to ? `Until ${shortDay(to, year)}` : "";
}

function Filters({
  data,
  filters,
  all,
  set,
  clear,
}: {
  data: SessionList;
  filters: SessionFilters;
  all: boolean;
  set: SetView;
  clear: () => void;
}) {
  const kindLabel = (value: string) => data.options.kind.find((k) => k.value === value)?.label ?? value;
  const chips: ActiveFilter[] = [];
  if (filters.track) {
    chips.push({ key: "track", label: filters.track, remove: () => set({ track: null }) });
  }
  if (filters.car) {
    chips.push({ key: "car", label: filters.car, remove: () => set({ car: null }) });
  }
  if (filters.kind) {
    chips.push({ key: "kind", label: kindLabel(filters.kind), remove: () => set({ kind: null }) });
  }
  if (filters.from || filters.to) {
    chips.push({
      key: "date",
      label: dateSummary(filters.from, filters.to),
      remove: () => set({ from: null, to: null }),
    });
  }
  const summary =
    data.matched === data.total
      ? countSessions(data.total)
      : `${data.matched} of ${countSessions(data.total)}`;
  return (
    <div className="space-y-3">
      <div role="group" aria-label="Filters" className="flex flex-wrap gap-2">
        <OptionFilter
          name="track"
          label="Track"
          any="Any track"
          current={filters.track}
          options={data.options.track.map((o) => ({ ...o, label: o.value }))}
          set={set}
        />
        <OptionFilter
          name="car"
          label="Car"
          any="Any car"
          current={filters.car}
          options={data.options.car.map((o) => ({ ...o, label: o.value }))}
          set={set}
        />
        <OptionFilter
          name="kind"
          label="Kind"
          any="Any kind"
          current={filters.kind}
          options={data.options.kind}
          set={set}
        />
        <DateFilter from={filters.from} to={filters.to} set={set} />
        <Toggle variant="outline" pressed={all} onPressedChange={(on) => set({ all: on ? "1" : null })}>
          No full lap
        </Toggle>
      </div>
      <ActiveFilters filters={chips} onClear={clear} />
      <p className="num text-sm text-muted" aria-live="polite">
        {summary}
      </p>
    </div>
  );
}

function OptionFilter({
  name,
  label,
  any,
  current,
  options,
  set,
}: {
  name: "track" | "car" | "kind";
  label: string;
  any: string;
  current: string | undefined;
  options: { value: string; label: string; count: number }[];
  set: SetView;
}) {
  return (
    <FilterPicker label={label} active={current !== undefined} description={`Show only one ${label.toLowerCase()}.`}>
      {(close) => (
        <FilterOptions
          label={label}
          any={any}
          current={current}
          options={options}
          onPick={(value) => {
            set({ [name]: value || null });
            close();
          }}
        />
      )}
    </FilterPicker>
  );
}

const DAY_S = 86_400;

function DateFilter({ from, to, set }: { from: string | undefined; to: string | undefined; set: SetView }) {
  return (
    <FilterPicker label="Date" active={!!(from || to)} description="Show the sessions from these days.">
      {(close) => <DatePanel from={from} to={to} set={set} close={close} />}
    </FilterPicker>
  );
}

function DatePanel({
  from,
  to,
  set,
  close,
}: {
  from: string | undefined;
  to: string | undefined;
  set: SetView;
  close: () => void;
}) {
  const [now] = useState(() => Date.now() / 1000);
  const today = isoDay(now);
  const [start, setStart] = useState(from ?? "");
  const [end, setEnd] = useState(to ?? "");
  const pick = (a: string | null, b: string | null) => {
    set({ from: a, to: b });
    close();
  };
  const quick: [string, string, string][] = [
    ["Today", today, today],
    ["Yesterday", isoDay(now - DAY_S), isoDay(now - DAY_S)],
    ["Last 7 days", isoDay(now - 6 * DAY_S), today],
  ];
  const input =
    "min-h-11 w-full rounded-md border border-input bg-bg px-3 text-base text-fg focus-visible:outline-2 focus-visible:outline-ring";
  return (
    <div className="space-y-3 p-2">
      <div className="flex flex-wrap gap-2">
        {quick.map(([label, a, b]) => (
          <Button
            key={label}
            variant="outline"
            aria-pressed={from === a && to === b}
            onClick={() => pick(a, b)}
          >
            {label}
          </Button>
        ))}
      </div>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          pick(start || null, end || null);
        }}
      >
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1 text-sm text-muted">
            <span className="block">From</span>
            <input type="date" className={input} value={start} max={end || today} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-muted">
            <span className="block">To</span>
            <input type="date" className={input} value={end} min={start || undefined} max={today} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit">Apply</Button>
          <Button type="button" variant="ghost" onClick={() => pick(null, null)}>
            Any date
          </Button>
        </div>
      </form>
    </div>
  );
}
