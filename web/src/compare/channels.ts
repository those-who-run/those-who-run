// What lap compare draws (#299 R3): one chart per channel of the trace route, and
// the x axis they share. Everything here is plain data, so a test can read it.
import type { Trace } from "@/api/hooks";
import { gear, pedalPct, traceTime, whole } from "@/lib/format";

export type ChannelId = "speed" | "throttle" | "brake" | "gear" | "rpm";

export interface Channel {
  id: ChannelId;
  /** The trace's field. */
  field: "speed_kph" | "throttle_pct" | "brake_pct" | "gear" | "rpm";
  /** The chip's and the chart's name. */
  label: string;
  /** Beside the name in the chart's caption and the readout's heading. */
  unit: string;
  /** The readout's column heading. */
  short: string;
  /** A value in the readout and on the y axis. */
  format: (v: number | null | undefined) => string;
  /** Gear changes are steps, not slopes. */
  stepped?: boolean;
  /** A fixed y range; otherwise it fits the data. */
  range?: readonly [number, number];
}

export const CHANNELS: readonly Channel[] = [
  { id: "speed", field: "speed_kph", label: "Speed", short: "km/h", unit: "km/h", format: whole },
  { id: "throttle", field: "throttle_pct", label: "Throttle", short: "Thr", unit: "%", format: pedalPct, range: [0, 100] },
  { id: "brake", field: "brake_pct", label: "Brake", short: "Brk", unit: "%", format: pedalPct, range: [0, 100] },
  { id: "gear", field: "gear", label: "Gear", short: "Gear", unit: "", format: gear, stepped: true },
  { id: "rpm", field: "rpm", label: "RPM", short: "RPM", unit: "rpm", format: whole },
];

export const CHANNEL_IDS: readonly ChannelId[] = CHANNELS.map((c) => c.id);

/** The x axis, as a function of the trace (R11): time from the lap's first frame
 * today; distance when #15 brings it. */
export const X_AXIS = {
  label: "Time from the lap's start",
  unit: "s",
  of: (trace: Trace): readonly number[] => trace.t,
  format: traceTime,
  /** A pinch stops at this much of a lap. */
  minSpan: 1,
} as const;
