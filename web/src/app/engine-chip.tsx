// The live engineer chip in the header (#296 R2, R3, R9; ADR 0004 point 10): what
// the engineer is doing right now. "Live · Suzuka Circuit · L3" with the pulsing
// red dot, "Paused · …", "Replay", "Demo", "Idle" or "In the menus", and "Engineer
// offline", muted and never in an error colour: the pages carry on without it.
// A tap opens a popover with the engineer's version, telemetry and voice, a link
// to the live session, and the pit wall's own version. When the two versions
// differ, the chip carries a small blue marker and the popover says a deploy is
// rolling out.
//
// The chip sits on `--surface` (the header), so its red dot is allowed; the
// popover is `--surface-raised`, so nothing in it is red (docs/design.md, Allowed
// pairs).
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import type { EngineView } from "@/api/hooks";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { activityLine, chipLine, chipText, versionsDiffer, type ChipText } from "./engine";

function Dot({ tone }: { tone: ChipText["tone"] }) {
  if (tone === "live") {
    return <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full bg-accent motion-safe:animate-pulse" />;
  }
  if (tone === "paused") {
    return <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full border-2 border-muted" />;
  }
  return null;
}

function Label({ text }: { text: ChipText }) {
  if (text.word === "Checking the engineer") {
    return (
      <>
        <span aria-hidden="true" className="h-4 w-16 rounded-sm bg-surface-raised motion-safe:animate-pulse" />
        <span className="sr-only">{text.word}</span>
      </>
    );
  }
  return (
    <span className={`flex min-w-0 items-center ${text.tone === "muted" ? "text-muted" : ""}`}>
      <span className="shrink-0">{text.word}</span>
      {text.track !== undefined && (
        <>
          <span className="shrink-0 whitespace-pre text-muted">{" · "}</span>
          <span className={`min-w-0 truncate ${text.track === null ? "text-muted" : ""}`}>
            {text.track ?? "Unknown track"}
          </span>
        </>
      )}
      {text.lap !== undefined && (
        <>
          <span className="shrink-0 whitespace-pre text-muted">{" · "}</span>
          <span className="num shrink-0">L{text.lap}</span>
        </>
      )}
    </span>
  );
}

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted">{term}</dt>
      <dd className="min-w-0 text-right break-words">{children}</dd>
    </div>
  );
}

function Panel({
  engine,
  pitwall,
  onNavigate,
}: {
  engine: EngineView;
  pitwall: string | null;
  onNavigate: () => void;
}) {
  const status = engine.state === "online" ? engine.status : null;
  const session = status?.session ?? null;
  return (
    <div className="space-y-3" data-slot="engine-panel">
      <p className="font-semibold">{activityLine(engine)}</p>
      {engine.state === "offline" && (
        <p className="text-muted">
          The engineer isn&apos;t answering. The sessions still work, and this checks again every 5 seconds.
        </p>
      )}
      {status && (
        <dl className="space-y-1">
          <Row term="Engineer">
            <span className="num">{status.version}</span>
          </Row>
          <Row term="Telemetry">{status.telemetry.connected ? "Connected" : "Not connected"}</Row>
          <Row term="Voice">{status.voice_connected ? "In the voice channel" : "Not in the voice channel"}</Row>
          {session && (
            <Row term="Track">
              {session.track?.sure && session.track.name ? (
                session.track.name
              ) : (
                <span className="text-muted">Unknown track</span>
              )}
            </Row>
          )}
        </dl>
      )}
      {versionsDiffer(engine, pitwall) && (
        <p className="text-info" data-slot="deploy-notice">
          Engineer {status?.version}, pit wall {pitwall}: a deploy is rolling out
        </p>
      )}
      {session && (
        <Link
          to={`/sessions/${encodeURIComponent(session.id)}`}
          onClick={onNavigate}
          className="inline-flex min-h-11 items-center text-accent-text underline underline-offset-4"
        >
          Open the live session
        </Link>
      )}
      <p className="border-t border-border-strong pt-2 text-meta text-muted">
        Pit wall <span className="num">{pitwall ?? "version unknown"}</span> · Read-only
      </p>
    </div>
  );
}

/** The chip for a given engineer state: what the header shows, and what /_kit
 * shows in each state. */
export function EngineChip({ engine, pitwall }: { engine: EngineView; pitwall: string | null }) {
  const [open, setOpen] = useState(false);
  const text = chipText(engine);
  const rolling = versionsDiffer(engine, pitwall);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={rolling ? `${chipLine(text)}, a deploy is rolling out` : chipLine(text)}
        data-slot="live-chip"
        data-tone={text.tone}
        className="inline-flex min-h-11 max-w-full min-w-0 items-center gap-2 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium whitespace-nowrap transition-colors duration-fast hover:border-muted data-[state=open]:border-muted"
      >
        <Dot tone={text.tone} />
        <Label text={text} />
        {rolling && (
          <span aria-hidden="true" data-slot="deploy-marker" className="size-2 shrink-0 rounded-full bg-info" />
        )}
      </PopoverTrigger>
      <PopoverContent align="end" aria-label="The engineer" className="w-80">
        <Panel engine={engine} pitwall={pitwall} onNavigate={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}
