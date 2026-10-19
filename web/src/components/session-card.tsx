// One session in a list: the session list, same-track sessions, the live session.
// Built from the API's Session values and format.ts, never from its card strings,
// except `result` for the endings Python words (retired, paused, stopped, no full
// lap; ADR 0004 point 6).
//
// It lays out by its own width (a container query), not the viewport's: stacked
// below 28 rem, a row above, so the same card works in a phone list, an iPad grid
// and a desktop column. The whole card is the link to the session; an Unknown's
// reason button sits above it. The track name wraps to two lines, then ends in an
// ellipsis, with the full name in its title and its accessible name.
import { Link } from "react-router";

import type { components } from "@/api/schema";
import { KindBadge } from "@/components/kind-badge";
import { LapTime } from "@/components/lap-time";
import { LiveBadge, type LiveState } from "@/components/live-badge";
import { Loading, SkeletonText } from "@/components/loading";
import { Position } from "@/components/position";
import { Unknown } from "@/components/unknown";
import { raceTime, sessionDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Session = components["schemas"]["Session"];

const FRAME =
  "@container relative w-full rounded-md border bg-surface p-4 transition-colors duration-fast hover:border-border-strong";
const LAYOUT = "flex flex-col gap-3 @md:flex-row @md:items-start @md:justify-between @md:gap-6";
const ASIDE = "flex shrink-0 flex-wrap items-baseline gap-x-4 gap-y-1 @md:flex-col @md:items-end @md:text-right";

function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The track detector's evidence ("3 layouts near the start still fit, line not yet
 * crossed") as a sentence, or a plain reason when it gave none. */
function trackReason(evidence: string | null): string {
  if (!evidence) {
    return "The engineer couldn't match the drive to a track.";
  }
  const text = sentence(evidence.trim());
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** How it ended, or where it is now: from the values where the browser can say it
 * exactly, from Python's line where Python owns the wording. */
function Result({ s, live }: { s: Session; live?: LiveState }) {
  const position = (
    <Position position={s.final_position} cars={s.total_cars} shown={s.position_shown && s.final_position != null} />
  );
  if (live) {
    const lap = s.laps_completed + 1;
    return (
      <p className="text-base">
        <span className="num whitespace-nowrap">
          Lap {s.total_laps ? Math.min(lap, s.total_laps) : lap}
          {s.total_laps ? ` of ${s.total_laps}` : ""}
        </span>
        {s.position_shown && s.final_position != null && <>, running {position}</>}
      </p>
    );
  }
  if (s.finished) {
    return (
      <p className="text-base">
        Finished {position}
        {s.total_time_ms != null && (
          <>
            {" "}
            in <span className="num whitespace-nowrap">{raceTime(s.total_time_ms)}</span>
          </>
        )}
      </p>
    );
  }
  return <p className={cn("text-base", s.laps_completed < 1 && "text-muted")}>{sentence(s.result)}</p>;
}

export function SessionCard({
  session: s,
  to,
  live,
  now,
  tz,
  headingLevel = 3,
  className,
}: {
  session: Session;
  /** Where the card goes: `/sessions/<id>`. */
  to: string;
  /** The engineer's state when this is the open session (#292). */
  live?: LiveState;
  /** For the date, "Today 14:04": Unix seconds, and the zone; the viewer's by default. */
  now?: number;
  tz?: string;
  headingLevel?: 2 | 3 | 4;
  className?: string;
}) {
  const Heading = `h${headingLevel}` as const;
  const name = s.track.name;
  const linkClass = "after:absolute after:inset-0 after:rounded-md focus-visible:outline-none";
  return (
    <article
      data-slot="session-card"
      data-live={live}
      className={cn(
        FRAME,
        "has-[[data-card-link]:focus-visible]:outline-2 has-[[data-card-link]:focus-visible]:outline-offset-2 has-[[data-card-link]:focus-visible]:outline-ring has-[[data-card-link]:focus-visible]:outline-solid",
        className,
      )}
    >
      <div className={LAYOUT}>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-3">
            <Heading className="min-w-0 text-lg font-semibold break-words">
              {s.track.sure ? (
                <Link to={to} data-card-link="" title={name} className={cn("line-clamp-2", linkClass)}>
                  {name}
                </Link>
              ) : (
                <>
                  <Link to={to} data-card-link="" aria-label={name} className={linkClass} />
                  <Unknown label={name} reason={trackReason(s.track.evidence)} className="relative z-10 -my-2.5" />
                </>
              )}
            </Heading>
            {live && <LiveBadge state={live} className="mt-1 shrink-0" />}
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            <KindBadge label={s.kind_label} kind={s.kind} />
            {s.car ? (
              <span className="min-w-0 break-words">{s.car}</span>
            ) : (
              <Unknown
                label="Unknown car"
                reason={
                  s.car_code != null
                    ? `GT7 sent car code ${s.car_code}, which isn't in the engineer's car list.`
                    : "GT7 sent no car code."
                }
                className="relative z-10 -my-2.5"
              />
            )}
            <span aria-hidden="true">·</span>
            <time className="whitespace-nowrap" dateTime={new Date(s.started_at * 1000).toISOString()}>
              {sessionDate(s.started_at, now, tz)}
            </time>
          </div>
        </div>
        <div className={ASIDE}>
          <Result s={s} live={live} />
          {s.best_lap_ms != null && (
            <p className="text-sm text-muted">
              Best <LapTime ms={s.best_lap_ms} best size="sm" />
              {s.best_lap_no != null && <span className="whitespace-nowrap"> (lap {s.best_lap_no})</span>}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}

/** A session card while the list loads: the same frame and lines, in grey. */
export function SessionCardSkeleton({ className }: { className?: string }) {
  return (
    <Loading label="Loading session" className={cn(FRAME, "hover:border-border", className)}>
      <div className={LAYOUT}>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-lg">
            <SkeletonText sample="Circuit Gilles Villeneuve" className="max-w-full" />
          </p>
          <p className="text-sm">
            <SkeletonText sample="12-lap race · Porsche 911 GT3 RS · Today 14:04" className="max-w-full" />
          </p>
        </div>
        <div className={ASIDE}>
          <p className="text-base">
            <SkeletonText sample="Finished P1/16 in 9:56.826" />
          </p>
          <p className="text-sm">
            <SkeletonText sample="Best 1:27.764 (lap 4)" />
          </p>
        </div>
      </div>
    </Loading>
  );
}
