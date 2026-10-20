// Lap compare (#299): two laps over each other, speed, throttle, brake, gear and
// RPM, as stacked uPlot charts with one shared cursor. A finger dragged across any
// chart scrubs, and the readout pinned above the charts shows both laps' values
// there. Pinch or drag zooms every chart; double-tap resets. Lap B can come from
// another session at the same track. A track map (#350) beside or above the charts
// shows where on the track the cursor is, and a tap on it moves the cursor.
//
// The URL is the view (`?a`, `?b`, `?b_session`, `?zoom`); hidden channels are the
// viewer's own, in localStorage. uPlot comes in with this route's chunk only.
import { ArrowLeftIcon, RotateCcwIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams, useSearchParams } from "react-router";

import {
  isNotFound,
  TRACE_MAX_POINTS,
  useLaps,
  useSameTrack,
  useSession,
  useTrace,
  type LapRow,
} from "@/api/hooks";
import { BackLink } from "@/app/back-link";
import { usePageTitle } from "@/app/title";
import type { XRange } from "@/charts/gestures";
import { align } from "@/compare/align";
import { ChannelChart } from "@/compare/channel-chart";
import { CHANNELS, type ChannelId } from "@/compare/channels";
import { createCursorStore } from "@/compare/cursor";
import { LapLetter } from "@/compare/lap-swatch";
import type { MapMode } from "@/compare/map";
import { LapAPicker, LapBPicker } from "@/compare/picker";
import { formatZoom, parseZoom, resolvePicks } from "@/compare/picks";
import { readHiddenChannels, readMapMode, takeSidewaysHint, writeHiddenChannels, writeMapMode } from "@/compare/prefs";
import { Readout } from "@/compare/readout";
import { seekCharts } from "@/compare/sync";
import { TrackMap } from "@/compare/track-map";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LapTime } from "@/components/lap-time";
import { Loading } from "@/components/loading";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { lapTime, sessionDate } from "@/lib/format";

/** A chart's height: about 140 px on a phone, 180 px wider (R3). */
const PHONE_CHART_PX = 140;
const WIDE_CHART_PX = 180;
const WIDE_FROM_PX = 600;

const MISSING_LAP = "A lap file is missing or still being written.";

/** A ref for an element, and its content width, kept up to date (0 until it mounts). */
function useWidth(): [(el: HTMLElement | null) => void, number] {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!el) {
      return;
    }
    const observer = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);
  return [setEl, width];
}

/** How many points to ask a trace for (R8): one per device pixel of the chart's
 * width, at most 1,500, in steps of 100 so a small resize asks nothing new. It only
 * grows: a narrower chart draws the points it has. */
function usePoints(width: number): number {
  const [points, setPoints] = useState(0);
  const want =
    width > 0
      ? Math.min(TRACE_MAX_POINTS, Math.ceil(((typeof window === "undefined" ? 1 : window.devicePixelRatio) * width) / 100) * 100)
      : 0;
  if (want > points) {
    setPoints(want);
  }
  return Math.max(points, want);
}

/** "A 2:27.764 · B 2:28.337 · A faster by 0.573" (R2). */
function Summary({ a, b }: { a: LapRow | undefined; b: LapRow | undefined }) {
  const ta = a && !a.invalid ? a.time_ms : null;
  const tb = b && !b.invalid ? b.time_ms : null;
  let verdict: string | null = null;
  if (ta && tb) {
    const diff = tb - ta;
    verdict = diff === 0 ? "level" : `${diff > 0 ? "A" : "B"} faster by ${lapTime(Math.abs(diff))}`;
  }
  return (
    <p data-slot="summary" className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="inline-flex items-center gap-1.5">
        <LapLetter side="a" />
        <LapTime ms={ta} best={a?.best} invalid={!ta} />
      </span>
      <span aria-hidden="true" className="text-muted">
        ·
      </span>
      <span className="inline-flex items-center gap-1.5">
        <LapLetter side="b" />
        <LapTime ms={tb} best={b?.best} invalid={!tb} />
      </span>
      {verdict && (
        <>
          <span aria-hidden="true" className="text-muted">
            ·
          </span>
          <span className="num whitespace-nowrap">{verdict}</span>
        </>
      )}
    </p>
  );
}

function ChartSkeleton({ height }: { height: number }) {
  return (
    <Loading label="Loading the traces">
      <Skeleton className="w-full" style={{ height }} />
    </Loading>
  );
}

function PageSkeleton() {
  return (
    <Loading label="Loading the laps" className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
      {CHANNELS.slice(0, 3).map((c) => (
        <Skeleton key={c.id} className="h-36 w-full" />
      ))}
    </Loading>
  );
}

export function Component() {
  const { id = "" } = useParams();
  usePageTitle("Lap compare");
  const [params, setParams] = useSearchParams();
  // Kept through every pick, so "Back to the session" stays the browser's Back.
  const location = useLocation();
  const session = useSession(id);
  const laps = useLaps(id);
  const sameTrack = useSameTrack(id);

  const asked = { a: params.get("a"), b: params.get("b"), bSession: params.get("b_session") };
  const otherId = asked.bSession && asked.bSession !== id ? asked.bSession : "";
  // Lap B's session's laps when it is another; with none, this session's again
  // (the same query, so nothing more is asked), unused.
  const otherQuery = useLaps(otherId || id);
  const otherLaps = otherId ? otherQuery : { data: undefined, isError: false };

  const picks = laps.data
    ? resolvePicks(
        id,
        asked,
        laps.data.laps,
        otherLaps.isError ? [] : otherLaps.data?.laps,
        sameTrack.data?.sessions.map((s) => s.session_id),
      )
    : null;

  const [charts, width] = useWidth();
  const points = usePoints(width);
  const chartHeight = width >= WIDE_FROM_PX ? WIDE_CHART_PX : PHONE_CHART_PX;

  const traceA = useTrace(id, points > 0 ? (picks?.a ?? null) : null, points);
  const traceB = useTrace(picks?.bSession ?? id, points > 0 ? (picks?.b ?? null) : null, points);
  const aData = traceA.data ?? null;
  const bData = traceB.data ?? null;
  const aligned = useMemo(() => align(aData, bData), [aData, bData]);

  const [cursor] = useState(createCursorStore);
  const [hidden, setHidden] = useState<ChannelId[]>(readHiddenChannels);
  const [mapMode, setMapMode] = useState<MapMode>(readMapMode);
  const [sideways, setSideways] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(pointer: coarse) and (orientation: portrait)").matches &&
      takeSidewaysHint(),
  );
  const [aOpen, setAOpen] = useState(false);
  // Lap B's picker starts open when there is no other lap to compare with (R9).
  const [bOpenAsked, setBOpen] = useState<boolean | null>(null);
  const bOpen = bOpenAsked ?? picks?.alone ?? false;

  // The x range every chart shares (R5), from `?zoom`, written back to it.
  const [zoom, setZoom] = useState<XRange | null>(() => parseZoom(params.get("zoom")));
  useEffect(() => {
    const timer = setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (zoom) {
            next.set("zoom", formatZoom(zoom));
          } else {
            next.delete("zoom");
          }
          return next.toString() === prev.toString() ? prev : next;
        },
        { replace: true, preventScrollReset: true, state: location.state },
      );
    }, 300);
    return () => clearTimeout(timer);
  }, [zoom, setParams, location.state]);

  /** A pick: into the URL, replacing the entry, so Back still leaves compare. */
  const pick = (changes: Record<string, string | null>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(changes)) {
          if (v === null) {
            next.delete(k);
          } else {
            next.set(k, v);
          }
        }
        return next;
      },
      { replace: true, preventScrollReset: true, state: location.state },
    );
  };

  const toggleChannel = (channel: ChannelId, shown: boolean) => {
    const next = shown ? hidden.filter((c) => c !== channel) : [...hidden, channel];
    setHidden(next);
    writeHiddenChannels(next);
  };

  const back = (
    <BackLink
      to={`/sessions/${encodeURIComponent(id)}`}
      className="inline-flex min-h-11 items-center gap-1.5 text-accent-text hover:text-fg"
    >
      <ArrowLeftIcon aria-hidden="true" className="size-4" />
      Back to the session
    </BackLink>
  );

  const heading = (
    <header className="space-y-1">
      {back}
      <h2 className="text-2xl font-semibold">Lap compare</h2>
      {session.data && <p className="break-words text-muted">{session.data.title}</p>}
    </header>
  );

  if (laps.isError) {
    return (
      <article className="space-y-4">
        {heading}
        {isNotFound(laps.error) ? (
          <EmptyState title="No such session" why="It may have been removed from the store." headingLevel={3} />
        ) : (
          <ErrorState
            title="Couldn't load this session's laps."
            detail={laps.error.message}
            onRetry={() => void laps.refetch()}
            retrying={laps.isFetching}
          />
        )}
      </article>
    );
  }

  if (!laps.data || !picks) {
    return (
      <article className="space-y-4">
        {heading}
        <PageSkeleton />
      </article>
    );
  }

  if (laps.data.laps.length === 0) {
    return (
      <article className="space-y-4">
        {heading}
        <EmptyState
          title="No laps to compare"
          why="This session has no laps yet. Drive a lap with the engineer running."
          headingLevel={3}
        />
      </article>
    );
  }

  const own = picks.bSession === id;
  const bRows = own ? laps.data.laps : otherLaps.data?.laps;
  const aRow = laps.data.laps.find((l) => l.lap === picks.a);
  const bRow = bRows?.find((l) => l.lap === picks.b);
  const bSession = own ? undefined : sameTrack.data?.sessions.find((s) => s.session_id === picks.bSession);
  const bSub = own
    ? undefined
    : bSession
      ? `${sessionDate(bSession.started_at)} · ${bSession.car ?? "Unknown car"}`
      : "Another session";

  const visible = CHANNELS.filter((c) => !hidden.includes(c.id));
  const missingA = traceA.isError && isNotFound(traceA.error);
  const missingB = traceB.isError && isNotFound(traceB.error);
  const failed = [traceA, traceB].find((t) => t.isError && !isNotFound(t.error));
  const loading = points === 0 || (picks.a !== null && traceA.isPending) || (picks.b !== null && traceB.isPending);
  const anything = aData !== null || bData !== null;
  const chartLabel = (label: string) =>
    `${label}, lap ${picks.a ?? "none"} solid against lap ${picks.b ?? "none"} dashed`;

  return (
    <article className="space-y-3">
      {heading}

      {(picks.notices.length > 0 || picks.alone) && (
        <div role="status" className="space-y-1 rounded-md border border-border-strong bg-surface p-3 text-sm">
          {picks.notices.map((n) => (
            <p key={n}>{n}</p>
          ))}
          {picks.alone && <p>Pick another lap, or one from another session.</p>}
        </div>
      )}

      {sideways && (
        <div
          role="status"
          className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface pl-3 text-sm"
        >
          <p>Turn sideways for a wider view.</p>
          <Button variant="ghost" size="icon" onClick={() => setSideways(false)}>
            <XIcon aria-hidden="true" />
            <span className="sr-only">Dismiss</span>
          </Button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <LapAPicker
          laps={laps.data.laps}
          selected={picks.a}
          onPick={(n) => pick({ a: String(n) })}
          open={aOpen}
          onOpenChange={setAOpen}
        />
        <LapBPicker
          laps={laps.data.laps}
          bLaps={otherLaps.data?.laps}
          selected={picks.b}
          bSession={picks.bSession}
          sessionId={id}
          sameTrack={sameTrack.data?.sessions}
          onPick={(n, s) => pick({ b: String(n), b_session: s === id ? null : s })}
          open={bOpen}
          onOpenChange={setBOpen}
          sub={bSub}
        />
      </div>

      <Summary a={aRow} b={bRow} />

      {/* On a phone, one column: the readout pinned, the chips, the map, then the
          charts (#350 R6); the left column is `contents` there, so `order` places
          the map. From 56 rem of width the map sits beside the charts, pinned. */}
      <div className="@container">
        <div className="flex flex-col gap-3 @4xl:flex-row @4xl:items-start @4xl:gap-6">
          <div className="contents @4xl:block @4xl:min-w-0 @4xl:flex-1 @4xl:space-y-3">
            <Readout
              cursor={cursor}
              a={aData}
              b={bData}
              channels={visible}
              className="sticky top-header z-10 order-1 @4xl:order-none"
            />

            <div className="order-2 flex flex-wrap items-center gap-2 @4xl:order-none" role="group" aria-label="Channels">
              {CHANNELS.map((c) => (
                <Toggle
                  key={c.id}
                  variant="outline"
                  pressed={!hidden.includes(c.id)}
                  onPressedChange={(on) => toggleChannel(c.id, on)}
                >
                  {c.label}
                </Toggle>
              ))}
              {zoom && (
                <Button variant="outline" onClick={() => setZoom(null)} className="ml-auto">
                  <RotateCcwIcon aria-hidden="true" />
                  Reset zoom
                </Button>
              )}
            </div>

            {(missingA || missingB) && (
              <div
                role="status"
                className="order-2 space-y-1 rounded-md border border-border-strong bg-surface p-3 text-sm @4xl:order-none"
              >
                {missingA && (
                  <p data-missing="a" className="flex flex-wrap items-center gap-x-2">
                    <LapLetter side="a" /> Lap {picks.a}: {MISSING_LAP}
                  </p>
                )}
                {missingB && (
                  <p data-missing="b" className="flex flex-wrap items-center gap-x-2">
                    <LapLetter side="b" /> Lap {picks.b}: {MISSING_LAP}
                  </p>
                )}
              </div>
            )}

            {failed && (
              <ErrorState
                className="order-2 @4xl:order-none"
                title="Couldn't load a lap's trace."
                detail={failed.error?.message}
                onRetry={() => {
                  void traceA.refetch();
                  void traceB.refetch();
                }}
                retrying={traceA.isFetching || traceB.isFetching}
              />
            )}

            <div
              ref={charts}
              data-slot="charts"
              data-points={points || undefined}
              className="order-4 w-full min-w-0 space-y-3 @4xl:order-none"
            >
              {visible.length === 0 && (
                <EmptyState title="Every channel is hidden" why="Show one with the buttons above." headingLevel={3} />
              )}
              {visible.map((c, i) => (
                <figure key={c.id} data-channel={c.id} className="space-y-1">
                  <figcaption className="text-meta text-muted">
                    {c.label}
                    {c.unit && ` (${c.unit})`}
                  </figcaption>
                  {loading ? (
                    <ChartSkeleton height={chartHeight} />
                  ) : anything ? (
                    <ChannelChart
                      channel={c}
                      aligned={aligned}
                      height={chartHeight}
                      showX={i === visible.length - 1}
                      xRange={zoom}
                      onXRange={setZoom}
                      cursor={cursor}
                      label={chartLabel(c.label)}
                    />
                  ) : (
                    <div className="rounded-md border border-dashed" style={{ height: chartHeight }} />
                  )}
                </figure>
              ))}
            </div>

            <p className="order-4 text-meta text-muted @4xl:order-none">
              Drag sideways across a chart to read both laps. Pinch, or drag with a mouse, to zoom; double-tap or
              double-click to reset. Tap the map to read both laps at that point on the track.
            </p>
          </div>
          <TrackMap
            a={aData}
            b={bData}
            lapA={picks.a}
            track={session.data?.track?.sure ? session.data.track.name : null}
            cursor={cursor}
            onSeek={(x) => seekCharts(cursor, x)}
            mode={mapMode}
            onMode={(m) => {
              setMapMode(m);
              writeMapMode(m);
            }}
            loading={loading}
            className="order-3 @4xl:sticky @4xl:top-header @4xl:order-none @4xl:w-96 @4xl:shrink-0"
          />
        </div>
      </div>
    </article>
  );
}
