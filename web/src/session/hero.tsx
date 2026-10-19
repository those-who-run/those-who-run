// The top of the session page (#298 R1): back to the list, the track, the kind,
// the date and the car, and the answer to "how did it go?" in big type. It fits on
// a 390 × 844 phone above the fold, with the tiles' first row under it.
import { ArrowLeftIcon } from "lucide-react";
import { type ReactNode } from "react";

import type { Session } from "@/api/hooks";
import { BackLink } from "@/app/back-link";
import { KindBadge } from "@/components/kind-badge";
import { LapTime } from "@/components/lap-time";
import { LiveBadge, type LiveState } from "@/components/live-badge";
import { Loading, SkeletonText } from "@/components/loading";
import { Position } from "@/components/position";
import { Unknown } from "@/components/unknown";
import { raceTime, sessionDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { headline, sentence } from "./model";

/** The track detector's evidence as a sentence, or a plain reason when it gave none. */
function trackReason(evidence: string | null): string {
  if (!evidence) {
    return "The engineer couldn't match the drive to a track.";
  }
  const text = sentence(evidence.trim());
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** The big answer, by what kind of session it was. */
function Headline({ s, live, lap }: { s: Session; live?: LiveState; lap: number }) {
  const shown = s.position_shown && s.final_position != null;
  const position = (
    <p>
      <Position position={s.final_position} cars={s.total_cars} size="xl" />
    </p>
  );
  const line = (children: ReactNode, muted = false) => (
    <p className={cn("text-lg", muted && "text-muted")}>{children}</p>
  );
  switch (headline(s).kind) {
    case "live":
      return live ? (
        <p className="num-lg">
          Lap {s.total_laps ? Math.min(lap, s.total_laps) : lap}
          {s.total_laps ? <span className="text-muted"> of {s.total_laps}</span> : null}
        </p>
      ) : (
        line(sentence(s.result))
      );
    case "finished":
      return (
        <>
          {shown && position}
          {line(
            <>
              Finished
              {s.total_time_ms != null && (
                <>
                  {" "}
                  in <span className="num whitespace-nowrap">{raceTime(s.total_time_ms)}</span>
                </>
              )}
            </>,
          )}
        </>
      );
    case "ended":
      return (
        <>
          {shown && position}
          {line(sentence(s.result), s.laps_completed < 1)}
        </>
      );
    case "timed":
      return (
        <>
          {shown && position}
          {line(
            <>
              {plural(s.laps_completed, "lap")}
              {s.finished && s.total_time_ms != null && (
                <>
                  {" "}
                  in <span className="num whitespace-nowrap">{raceTime(s.total_time_ms)}</span>
                </>
              )}
            </>,
          )}
        </>
      );
    default:
      return s.best_lap_ms != null ? (
        <>
          <LapTime ms={s.best_lap_ms} best size="xl" className="block" />
          {line(<>Best lap{s.best_lap_no != null && `, lap ${s.best_lap_no}`}</>)}
        </>
      ) : (
        line("No full lap", true)
      );
  }
}

export function SessionHero({
  session: s,
  live,
  lap,
  menu,
}: {
  session: Session;
  /** The engineer's state when this is its open session. */
  live?: LiveState;
  /** The lap being driven, while live. */
  lap: number;
  /** The page's overflow menu ("Copy link"). */
  menu?: ReactNode;
}) {
  return (
    <header data-slot="session-hero" className="space-y-3">
      <div className="-mt-2 flex items-center justify-between gap-2">
        <BackLink to="/" className="flex min-h-11 items-center text-accent-text underline-offset-4 hover:underline">
          <ArrowLeftIcon aria-hidden="true" className="mr-1 size-4" />
          All sessions
        </BackLink>
        {menu}
      </div>
      <div className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <h2 className="min-w-0 text-2xl font-semibold break-words">
            {s.track.sure ? (
              s.track.name
            ) : (
              <Unknown label={s.track.name} reason={trackReason(s.track.evidence)} className="-my-2.5" />
            )}
          </h2>
          {live && <LiveBadge state={live} className="mt-1.5 shrink-0" />}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
          <KindBadge label={s.kind_label} kind={s.kind} />
          <time className="whitespace-nowrap" dateTime={new Date(s.started_at * 1000).toISOString()}>
            {sessionDate(s.started_at)}
          </time>
          <span aria-hidden="true">·</span>
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
              className="-my-2.5"
            />
          )}
        </div>
      </div>
      <div data-slot="headline" className="space-y-1">
        <Headline s={s} live={live} lap={lap} />
      </div>
    </header>
  );
}

/** The hero while the session loads: the same lines, in grey. */
export function SessionHeroSkeleton() {
  return (
    <Loading label="Loading session" className="space-y-3">
      <p className="flex min-h-11 items-center">
        <SkeletonText sample="All sessions" />
      </p>
      <p className="text-2xl">
        <SkeletonText sample="Circuit Gilles Villeneuve" className="max-w-full" />
      </p>
      <p className="text-sm">
        <SkeletonText sample="12-lap race · Today 14:04 · Porsche 911 GT3 RS" className="max-w-full" />
      </p>
      <p className="num-xl">
        <SkeletonText sample="P1/16" />
      </p>
      <p className="text-lg">
        <SkeletonText sample="Finished in 9:56.826" />
      </p>
    </Loading>
  );
}
