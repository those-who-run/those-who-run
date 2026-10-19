// One session (#298): where a results card's link lands, designed for a phone in
// portrait. The result first (the hero), then the stat tiles, then the laps
// table, whose checkboxes pick two laps for compare (#299). While the session is
// the engineer's live one, it asks again every 5 s and new laps land under what
// is being read.
//
// The page, top to bottom: SessionHero, the joined-mid-session note, SessionTiles,
// the race story (#300, with three complete laps or more), LapsTable, PickBar. The
// race story and the table share the picks (`?pick=`) and the highlighted lap.
import { useQueryClient } from "@tanstack/react-query";
import { InfoIcon } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, queryKeys, useEngineStatus, useLaps, useSession, type LapRow, type Session } from "@/api/hooks";
import { usePageTitle } from "@/app/title";
import type { LiveState } from "@/components/live-badge";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SessionMenu } from "@/session/copy-link";
import { SessionHero, SessionHeroSkeleton } from "@/session/hero";
import { LapsTable, LapsTableSkeleton } from "@/session/laps-table";
import { bestAndNext, lapInProgress, parsePicks, togglePick } from "@/session/model";
import { PickBar } from "@/session/pick-bar";
import { raceStory, type Story } from "@/session/story";
import { SessionTiles, SessionTilesSkeleton } from "@/session/tiles";

// The chart carries uPlot: a chunk of its own, asked for only once there is a story.
const RaceStory = lazy(() => import("@/session/race-story").then((m) => ({ default: m.RaceStory })));

/** The engineer's open session when it is this one (#292): its state and lap. */
function useLive(id: string): { state: LiveState; lap: number | null } | null {
  const engine = useEngineStatus();
  if (engine.state !== "online" || engine.status.session?.id !== id) {
    return null;
  }
  return { state: engine.status.activity === "paused" ? "paused" : "live", lap: engine.status.session.lap };
}

/** Once more when the session stops being live, so the page ends on the closed
 * session's values; then no more polling. */
function useLastLook(id: string, live: boolean) {
  const queryClient = useQueryClient();
  const was = useRef(live);
  useEffect(() => {
    if (was.current && !live) {
      // The session's key is the start of its laps' key: both are asked again.
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(id) });
    }
    was.current = live;
  }, [id, live, queryClient]);
}

/** The picks in `?pick=`, and a setter that keeps the scroll where it is. A tick
 * shows at once: the router updates the URL a moment later, so until then the
 * picks are held here (a controlled checkbox would otherwise flick back). */
function usePicks(): [number[], (next: number[]) => void] {
  const [params, setParams] = useSearchParams();
  const param = params.get("pick");
  const [held, setHeld] = useState<{ from: string | null; to: string | null; picks: number[] } | null>(null);
  // Held while the URL is still what it was, or has caught up; anything else (Back,
  // a link) is the URL's own change, and wins.
  const picks = held && (param === held.from || param === held.to) ? held.picks : parsePicks(param);
  const set = (next: number[]) => {
    const p = new URLSearchParams(params);
    if (next.length) {
      p.set("pick", next.join(","));
    } else {
      p.delete("pick");
    }
    setHeld({ from: param, to: p.get("pick"), picks: next });
    setParams(p, { replace: true, preventScrollReset: true });
  };
  return [picks, set];
}

function NoSession({ id }: { id: string }) {
  return (
    <EmptyState
      headingLevel={2}
      title={`No session ${id}.`}
      why="The pit wall has no session with that id. It may have been deleted, or the link is wrong."
      action={
        <Button asChild variant="outline">
          <Link to="/">All sessions</Link>
        </Button>
      }
    />
  );
}

function JoinedNote({ lap }: { lap: number }) {
  return (
    <p data-slot="joined-note" className="flex items-start gap-2 rounded-md border p-3 text-sm">
      <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-info" />
      <span>
        The engineer joined on lap {lap}. Laps before it weren&apos;t seen.
      </span>
    </p>
  );
}

/** While the chart loads: a block its height, under its heading. */
function RaceStorySkeleton() {
  return (
    <div aria-hidden="true" className="space-y-2">
      <p className="text-xl font-semibold">Race story</p>
      <div className="min-h-7" />
      {/* The chart's height: 150 px, 180 px from 600 px of width (race-story.tsx). */}
      <Skeleton className="h-37.5 w-full min-[600px]:h-45" />
    </div>
  );
}

function Laps({
  session,
  laps,
  live,
  picks: known,
  setPicks,
  highlight,
  onHighlight,
}: {
  session: Session;
  laps: LapRow[];
  live: { lap: number | null } | null;
  picks: number[];
  setPicks: (next: number[]) => void;
  highlight: number | null;
  onHighlight: (lap: number | null) => void;
}) {
  if (!laps.length && !live) {
    return (
      <EmptyState
        title="No laps stored for this session."
        why="The session ended before the engineer stored a lap."
      />
    );
  }
  return (
    <>
      <LapsTable
        session={session}
        laps={laps}
        picks={known}
        onPick={(lap) => setPicks(togglePick(known, lap))}
        inProgress={live ? lapInProgress(laps, live.lap) : null}
        highlight={highlight}
        onHighlight={onHighlight}
      />
      <PickBar
        sessionId={session.session_id}
        picks={known}
        fallback={bestAndNext(laps)}
        onClear={() => setPicks([])}
      />
    </>
  );
}

export function Component() {
  const { id = "" } = useParams();
  const engineLive = useLive(id);
  const session = useSession(id, { live: !!engineLive });
  const laps = useLaps(id, { live: !!engineLive });
  useLastLook(id, !!engineLive);
  // A session the store has closed is over, whatever the engineer last said.
  const live = session.data?.closed ? null : engineLive;

  const rows = laps.data?.laps;
  const story = useMemo<Story | null>(
    () => (session.data && rows ? raceStory(session.data, rows) : null),
    [session.data, rows],
  );
  const [picks, setPicks] = usePicks();
  const known = picks.filter((p) => rows?.some((l) => l.lap === p));
  const [highlight, setHighlight] = useState<number | null>(null);

  const missing = session.error instanceof ApiError && session.error.status === 404;
  usePageTitle(session.data?.title ?? (missing ? "Session not found" : `Session ${id}`));

  if (session.isPending) {
    return (
      <div className="space-y-6">
        <SessionHeroSkeleton />
        <SessionTilesSkeleton />
        <LapsTableSkeleton />
      </div>
    );
  }
  if (session.isError) {
    return missing ? (
      <NoSession id={id} />
    ) : (
      <ErrorState
        title="Couldn't read the session store."
        detail={session.error.message}
        onRetry={() => void session.refetch()}
        retrying={session.isFetching}
      />
    );
  }

  const s = session.data;
  const lapRows = rows ?? [];
  return (
    <article className="space-y-6">
      <SessionHero
        session={s}
        live={live?.state}
        lap={lapInProgress(lapRows, live?.lap)}
        menu={<SessionMenu sessionId={s.session_id} />}
      />
      {s.joined_on_lap != null && <JoinedNote lap={s.joined_on_lap} />}
      {laps.isPending ? <SessionTilesSkeleton /> : <SessionTiles session={s} laps={lapRows} />}
      {story && (
        <Suspense fallback={<RaceStorySkeleton />}>
          <RaceStory
            story={story}
            picks={known}
            highlight={highlight}
            onHighlight={setHighlight}
            onPick={(lap) => setPicks(togglePick(known, lap))}
          />
        </Suspense>
      )}
      <section aria-label="Laps">
        {laps.isPending ? (
          <LapsTableSkeleton />
        ) : laps.isError ? (
          <ErrorState
            title="Couldn't load the laps."
            detail={laps.error.message}
            onRetry={() => void laps.refetch()}
            retrying={laps.isFetching}
          />
        ) : (
          <Laps
            session={s}
            laps={lapRows}
            live={live}
            picks={known}
            setPicks={setPicks}
            highlight={highlight}
            onHighlight={setHighlight}
          />
        )}
      </section>
    </article>
  );
}
