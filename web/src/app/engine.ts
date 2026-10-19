// What the live chip and its popover say for each engineer state (#296 R2, R3), as
// plain values, so the words are tested apart from the markup.
import type { EngineStatus, EngineView } from "@/api/hooks";

export type ChipTone = "live" | "paused" | "plain" | "muted";

export interface ChipText {
  tone: ChipTone;
  /** "Live", "Paused", "Replay", "Demo", "Idle", "In the menus", "Engineer offline". */
  word: string;
  /** The track: its name when the detector is sure, null for "Unknown track"
   * (muted), absent when the chip doesn't name one. */
  track?: string | null;
  /** The lap, when the chip shows one. */
  lap?: number;
}

/** The track as the chip names it: only when the detector is sure (decided on #296,
 * 2026-10-19); naming an unknown one from the pit wall is #319. */
function trackName(session: NonNullable<EngineStatus["session"]>): string | null {
  return session.track?.sure && session.track.name ? session.track.name : null;
}

export function chipText(view: EngineView): ChipText {
  if (view.state === "checking") {
    return { tone: "muted", word: "Checking the engineer" };
  }
  if (view.state === "offline") {
    return { tone: "muted", word: "Engineer offline" };
  }
  const { activity, session, telemetry } = view.status;
  switch (activity) {
    case "driving":
      if (!session) {
        return { tone: "live", word: "Live" };
      }
      // GT7 says lap 0 on the grid: no lap until the first one starts.
      return session.lap
        ? { tone: "live", word: "Live", track: trackName(session), lap: session.lap }
        : { tone: "live", word: "Live", track: trackName(session) };
    case "paused":
      return session
        ? { tone: "paused", word: "Paused", track: trackName(session) }
        : { tone: "paused", word: "Paused" };
    case "replay":
      return { tone: "plain", word: "Replay" };
    case "demo":
      return { tone: "plain", word: "Demo" };
    default:
      return { tone: "plain", word: telemetry.connected ? "In the menus" : "Idle" };
  }
}

/** The chip's text as one line: "Live · Suzuka Circuit · L3". */
export function chipLine(text: ChipText): string {
  const parts = [text.word];
  if (text.track !== undefined) {
    parts.push(text.track ?? "Unknown track");
  }
  if (text.lap !== undefined) {
    parts.push(`L${text.lap}`);
  }
  return parts.join(" · ");
}

/** The popover's first line: what the engineer is doing, in a sentence's words. */
export function activityLine(view: EngineView): string {
  if (view.state !== "online") {
    return view.state === "offline" ? "Engineer offline" : "Checking the engineer";
  }
  const { activity, telemetry } = view.status;
  return {
    driving: "Driving",
    paused: "Paused",
    replay: "Watching a replay",
    demo: "Running a demo",
    idle: telemetry.connected ? "In the menus" : "Idle",
  }[activity];
}

/** The engineer and the pit wall on different versions: a deploy is rolling out
 * (R3, ADR 0004 point 10). Unknown when either version is unknown. */
export function versionsDiffer(view: EngineView, pitwall: string | null | undefined): boolean {
  return view.state === "online" && !!pitwall && view.status.version !== pitwall;
}
