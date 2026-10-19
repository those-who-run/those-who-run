// /_kit: every component in the kit, in every state (#295, ADR 0004 point 8). It is
// in production builds but linked from nowhere: it is where the look is reviewed, on
// the phone and iPad through `make web-preview`, and where CI screenshots and runs
// axe (web/e2e/kit.spec.ts). A new visual pattern lands here before a page uses it.
// The sample data is web/src/kit/samples.ts.
import { LinkIcon, SlidersHorizontalIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Unknown } from "@/components/unknown";
import { KIT_NOW, KIT_TZ, LAPS, NAMES, SESSIONS } from "@/kit/samples";
import { duration, fuelPerLap, lapTime, missing, raceTime, speedKph } from "@/lib/format";

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

export function Component() {
  const [shortSessions, setShortSessions] = useState(false);
  return (
    <article className="space-y-10 pb-16">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold">Component kit</h2>
        <p className="text-muted">
          Every component in every state, with real names from the NUC&apos;s store. The pages are built from these
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

      <Section id="kit-primitives" title="Primitives" note="shadcn/ui, restyled only through the tokens.">
        <State name="Button: default, outline, ghost, link, icon, disabled" wide>
          <Button>Compare laps</Button>
          <Button variant="outline">All sessions</Button>
          <Button variant="ghost">Clear</Button>
          <Button variant="link">Open the results card</Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Copy link">
                <LinkIcon aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Copy link</TooltipContent>
          </Tooltip>
          <Button disabled>Compare laps</Button>
        </State>
        <State name="Badge: default, outline, muted" wide>
          <Badge>New best</Badge>
          <Badge variant="outline">12-lap race</Badge>
          <Badge variant="muted">session</Badge>
        </State>
        <State name="Select" wide>
          <Select defaultValue={NAMES.willow}>
            <SelectTrigger aria-label="Track" className="max-w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[NAMES.willow, NAMES.tokyo, NAMES.gilles, NAMES.suzuka].map((n) => (
                <SelectItem key={n} value={n}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </State>
        <State name="Toggle: off and on" wide>
          <Toggle variant="outline" pressed={shortSessions} onPressedChange={setShortSessions}>
            Show short sessions
          </Toggle>
          <Toggle variant="outline" defaultPressed>
            Fuel
          </Toggle>
        </State>
        <State name="Sheet (from the bottom) and Dialog" wide>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline">
                <SlidersHorizontalIcon aria-hidden="true" />
                Filters
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Filters</SheetTitle>
                <SheetDescription>Narrow the list by track, car and kind.</SheetDescription>
              </SheetHeader>
              <SheetFooter>
                <SheetClose asChild>
                  <Button>Show 12 sessions</Button>
                </SheetClose>
              </SheetFooter>
            </SheetContent>
          </Sheet>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">About this session</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>About this session</DialogTitle>
                <DialogDescription>
                  Driven for {duration(596_826)} at {NAMES.willow}.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">Close</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </State>
        <State name="Card and Separator" wide>
          <Card className="w-full">
            <CardHeader>
              <CardTitle>Engineer</CardTitle>
              <CardDescription>Version 0.7.1, up 3 h 12 min</CardDescription>
            </CardHeader>
            <Separator />
            <CardContent className="text-sm text-muted">Telemetry connected. Voice joined.</CardContent>
          </Card>
        </State>
        <State name="Skeleton" wide>
          <Skeleton className="h-6 w-48" />
        </State>
      </Section>
    </article>
  );
}
