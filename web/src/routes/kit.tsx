// /_kit: every component in the kit, in every state (#295, ADR 0004 point 8). It is
// in production builds but linked from nowhere: it is where the look is reviewed, on
// the phone and iPad through `make web-preview`, and where CI screenshots and runs
// axe (web/e2e/kit.spec.ts). A new visual pattern lands here before a page uses it.
// The sample data is web/src/kit/samples.ts.
import { GaugeIcon, ListIcon } from "lucide-react";
import { lazy, Suspense, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import type { EngineStatus, EngineView } from "@/api/hooks";
import { EngineChip } from "@/app/engine-chip";
import { Nav } from "@/app/nav";
import type { Section as NavSection } from "@/app/sections";
import { usePageTitle } from "@/app/title";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Gap, GapSkeleton } from "@/components/gap";
import { KindBadge } from "@/components/kind-badge";
import { LapFlag, type LapFlagKind } from "@/components/lap-flag";
import { LapTime, LapTimeSkeleton } from "@/components/lap-time";
import { LiveBadge } from "@/components/live-badge";
import { Position, PositionSkeleton } from "@/components/position";
import { SessionCard, SessionCardSkeleton } from "@/components/session-card";
import { StatTile, StatTileSkeleton } from "@/components/stat-tile";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Unknown } from "@/components/unknown";
import { engine, KIT_NOW, KIT_TZ, KIT_VERSION, LAPS, liveSession, NAMES, SESSIONS } from "@/kit/samples";
import { fuelPerLap, lapTime, missing, raceTime, speedKph } from "@/lib/format";

// The filter pattern (#297) and the primitives (#299) are chunks of their own: the
// kit's stays under the route ceiling.
const FilterSamples = lazy(() => import("@/kit/filter-samples").then((m) => ({ default: m.FilterSamples })));
const PrimitiveSamples = lazy(() =>
  import("@/kit/primitive-samples").then((m) => ({ default: m.PrimitiveSamples })),
);

function Section({ id, title, note, children }: { id: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={id} data-kit={id} className="space-y-3">
      <div>
        <h3 id={id} className="text-xl font-semibold">
          {title}
        </h3>
        {note && <p className="text-sm text-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

/** One state of a component, labelled. */
function State({ name, children, wide = false }: { name: string; children: ReactNode; wide?: boolean }) {
  return (
    <div data-state-name={name} className={wide ? "w-full space-y-1" : "min-w-0 space-y-1"}>
      <p className="text-meta text-muted">{name}</p>
      <div className="flex min-h-11 flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-x-8 gap-y-4">{children}</div>;
}

const BEST = LAPS.find((l) => l.best)!.time_ms!;

const online = (status: EngineStatus): EngineView => ({ state: "online", status });

/** The live chip in every state: its name, the engineer, the pit wall's version. */
const CHIPS: [string, EngineView, string | null][] = [
  ["driving", online(engine({ activity: "driving", idle_secs: 0, session: liveSession() })), KIT_VERSION],
  [
    "unknown track",
    online(engine({ activity: "driving", idle_secs: 0, session: liveSession({ track: null, lap: 1 }) })),
    KIT_VERSION,
  ],
  ["no session", online(engine({ activity: "driving", idle_secs: 0 })), KIT_VERSION],
  [
    "paused",
    online(engine({ activity: "paused", session: liveSession({ track: { id: 2, name: NAMES.suzuka, sure: true } }) })),
    KIT_VERSION,
  ],
  ["replay", online(engine({ activity: "replay" })), KIT_VERSION],
  ["demo", online(engine({ activity: "demo" })), KIT_VERSION],
  ["idle", online(engine()), KIT_VERSION],
  ["in the menus", online(engine({ telemetry: { connected: true, last_packet_age_s: 0.1 } })), KIT_VERSION],
  ["offline", { state: "offline" }, KIT_VERSION],
  ["checking", { state: "checking" }, null],
  ["deploy rolling out", online(engine({ version: "0.7.0" })), KIT_VERSION],
];

/** Two sections, so the navigation shows: the first is this page. */
const NAV_SAMPLE: NavSection[] = [
  { id: "sessions", label: "Sessions", to: "/_kit", icon: ListIcon, prefixes: [] },
  { id: "live", label: "Live", to: "/_kit?section=live", icon: GaugeIcon, prefixes: [] },
];

function flags(l: (typeof LAPS)[number]): LapFlagKind[] {
  const out: LapFlagKind[] = [];
  if (l.pit) out.push("pit");
  if (l.out_lap) out.push("out");
  if (l.invalid) out.push("partial");
  if (l.restart) out.push("restart");
  return out;
}

function Retry() {
  const [retrying, setRetrying] = useState(false);
  return (
    <ErrorState
      title="Couldn't read the session store."
      detail="GET /api/v1/sessions: 503 the index is busy, try again"
      retrying={retrying}
      onRetry={() => {
        setRetrying(true);
        setTimeout(() => setRetrying(false), 1500);
      }}
    />
  );
}

/** `/_kit?throw`: a page that fails as it renders, to show the route error state
 * inside the shell (#296 R6, web/e2e/shell.spec.ts). */
function useThrowOnRequest() {
  const [params] = useSearchParams();
  if (params.has("throw")) {
    throw new Error("/_kit?throw: the kit failed on purpose");
  }
}

export function Component() {
  useThrowOnRequest();
  usePageTitle("Component kit");
  return (
    <article className="space-y-10 pb-16">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold">Component kit</h2>
        <p className="text-muted">
          Every component in every state, with real names from the engineer&apos;s store. The pages are built from these
          parts; a new pattern lands here first. See docs/design.md, Components.
        </p>
      </header>

      <Section id="kit-lap-time" title="LapTime" note="A lap time, from lapTime(). The best lap is purple and said.">
        <Row>
          <State name="normal">
            <LapTime ms={98_630} />
          </State>
          <State name="best">
            <LapTime ms={BEST} best />
          </State>
          <State name="invalid">
            <LapTime ms={null} invalid />
          </State>
          <State name="sm">
            <LapTime ms={49_677} size="sm" />
          </State>
          <State name="md">
            <LapTime ms={49_677} size="md" />
          </State>
          <State name="xl">
            <LapTime ms={BEST} best size="xl" />
          </State>
          <State name="loading">
            <LapTimeSkeleton />
          </State>
        </Row>
      </Section>

      <Section id="kit-gap" title="Gap" note="A gap to the reference, from gap(). The sign is always shown.">
        <Row>
          <State name="faster">
            <Gap ms={-312} />
          </State>
          <State name="slower">
            <Gap ms={866} />
          </State>
          <State name="best">
            <Gap ms={0} best />
          </State>
          <State name="even">
            <Gap ms={0} />
          </State>
          <State name="unknown">
            <Gap ms={null} />
          </State>
          <State name="loading">
            <GapSkeleton />
          </State>
        </Row>
      </Section>

      <Section id="kit-position" title="Position" note="From position(); hidden when the API's position_shown is false.">
        <Row>
          <State name="P3/16">
            <Position position={3} cars={16} />
          </State>
          <State name="P1/1">
            <Position position={1} cars={1} />
          </State>
          <State name="xl">
            <Position position={1} cars={16} size="xl" />
          </State>
          <State name="hidden">
            <Position position={3} cars={16} shown={false} />
            <span className="text-meta text-muted">(nothing drawn)</span>
          </State>
          <State name="unknown">
            <Position position={null} cars={16} />
          </State>
          <State name="loading">
            <PositionSkeleton />
          </State>
        </Row>
      </Section>

      <Section id="kit-kind-badge" title="KindBadge" note="The API's kind_label, as the results card names it.">
        <Row>
          <KindBadge label="12-lap race" kind="lap_race" />
          <KindBadge label="timed race" kind="timed_field" />
          <KindBadge label="time trial" kind="solo_timed" />
          <KindBadge label="6-lap run" kind="solo_laps" />
          <KindBadge label="session" kind="unknown" />
        </Row>
      </Section>

      <Section id="kit-lap-flag" title="LapFlag" note="Tap, click or Enter for what it means; Escape closes it.">
        <Row>
          <LapFlag flag="pit" />
          <LapFlag flag="out" />
          <LapFlag flag="partial" />
          <LapFlag flag="restart" />
        </Row>
      </Section>

      <Section id="kit-stat-tile" title="StatTile">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatTile label="Best lap" value={lapTime(BEST)} sub="lap 4" tone="best" />
          <StatTile label="Race time" value={raceTime(596_826)} sub="6 laps" />
          <StatTile label="Fuel per lap" value={fuelPerLap(3.2)} />
          <StatTile label="Fuel per lap" value={fuelPerLap(3.2, { fuelUse: false })} sub="fuel use is off" />
          <StatTile label="Top speed" value={missing()} sub="no lap file" />
          <StatTileSkeleton label="Driving time" />
        </div>
      </Section>

      <Section
        id="kit-session-card"
        title="SessionCard"
        note="Stacked below 28 rem of its own width, a row above. The whole card opens the session."
      >
        <div className="space-y-3">
          <State name="race finished" wide>
            <SessionCard session={SESSIONS.raceFinished} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="retired" wide>
            <SessionCard session={SESSIONS.retired} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="timed" wide>
            <SessionCard session={SESSIONS.timed} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="time trial" wide>
            <SessionCard session={SESSIONS.timeTrial} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="unknown track" wide>
            <SessionCard session={SESSIONS.unknownTrack} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="live" wide>
            <SessionCard session={SESSIONS.live} to="/_kit" live="live" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="paused" wide>
            <SessionCard session={SESSIONS.live} to="/_kit" live="paused" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
          </State>
          <State name="loading" wide>
            <SessionCardSkeleton className="w-full" />
          </State>
          <State name="in a 16 rem column: two lines, then an ellipsis" wide>
            <div className="w-64 max-w-full" data-kit="narrow">
              <SessionCard session={SESSIONS.raceFinished} to="/_kit" now={KIT_NOW} tz={KIT_TZ} headingLevel={4} />
            </div>
          </State>
        </div>
      </Section>

      <Section id="kit-live-badge" title="LiveBadge" note="The dot pulses, except under reduced motion.">
        <Row>
          <State name="live">
            <LiveBadge state="live" />
          </State>
          <State name="paused">
            <LiveBadge state="paused" />
          </State>
        </Row>
      </Section>

      <Section
        id="kit-live-chip"
        title="LiveChip"
        note="The header's engineer chip (app/live-chip.tsx). Tap for the engineer's version, telemetry and voice."
      >
        <Row>
          {CHIPS.map(([name, view, pitwall]) => (
            <State key={name} name={name}>
              <EngineChip engine={view} pitwall={pitwall} />
            </State>
          ))}
        </Row>
      </Section>

      <Section
        id="kit-navigation"
        title="Navigation"
        note="With two sections or more: a tab bar below 1024 px, a side rail from there. The app has one, so it shows neither."
      >
        <div data-kit="nav-preview" className="overflow-hidden rounded-md border">
          <Nav sections={NAV_SAMPLE} contained label="Sections (sample)" />
        </div>
      </Section>

      <Section id="kit-empty-state" title="EmptyState">
        <EmptyState
          headingLevel={4}
          title={`No sessions at ${NAMES.tokyo} yet`}
          why="Sessions appear here once the engineer has seen a full lap."
          action={<Button variant="outline">Show all tracks</Button>}
        />
      </Section>

      <Section id="kit-error-state" title="ErrorState" note="Retry shows its pressed state for a moment here.">
        <Retry />
        <ErrorState title="A lap file is missing or still being written." hint="Retry in a moment." />
      </Section>

      <Section id="kit-unknown" title="Unknown" note="Muted, never guessed; the reason is a tap away.">
        <Row>
          <State name="with a reason">
            <Unknown label="Unknown track" reason="3 layouts near the start still fit, line not yet crossed." />
          </State>
          <State name="no reason given">
            <Unknown label="Unknown car" />
          </State>
        </Row>
      </Section>

      <Section
        id="kit-lap-table"
        title="Lap table"
        note="Table, LapTime, Gap, Position and LapFlag together. Lap 4, the best, is the selected row. On a phone the table scrolls sideways inside its frame; the page doesn't."
      >
        <Table>
          <TableCaption>Laps, with gaps to the best lap</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Lap</TableHead>
              <TableHead scope="col">Time</TableHead>
              <TableHead scope="col">Gap</TableHead>
              <TableHead scope="col">Pos</TableHead>
              <TableHead scope="col">Fuel</TableHead>
              <TableHead scope="col">Top speed</TableHead>
              <TableHead scope="col">Flags</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {LAPS.map((l) => (
              <TableRow key={l.lap} data-state={l.best ? "selected" : undefined}>
                <TableCell>{l.lap}</TableCell>
                <TableCell>
                  <LapTime ms={l.time_ms} best={l.best} invalid={l.invalid} size="sm" />
                </TableCell>
                <TableCell>
                  <Gap ms={l.time_ms == null ? null : l.time_ms - BEST} best={l.best} size="sm" />
                </TableCell>
                <TableCell>
                  <Position position={l.position} cars={16} size="sm" />
                </TableCell>
                <TableCell>{fuelPerLap(l.fuel_used, { fuelUse: l.fuel_use })}</TableCell>
                <TableCell>{speedKph(l.top_speed_kph)}</TableCell>
                <TableCell className="py-0">
                  <div className="flex gap-1">
                    {flags(l).map((f) => (
                      <LapFlag key={f} flag={f} />
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      <Section
        id="kit-filters"
        title="Filters"
        note="A list's filters: a sheet below 640 px, a popover from 640 px; the URL holds what is set."
      >
        <Suspense fallback={null}>
          <FilterSamples />
        </Suspense>
      </Section>

      <Section id="kit-primitives" title="Primitives" note="shadcn/ui, restyled only through the tokens.">
        <Suspense fallback={null}>
          <PrimitiveSamples />
        </Suspense>
      </Section>
    </article>
  );
}
