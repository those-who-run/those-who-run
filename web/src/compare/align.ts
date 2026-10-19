// Two laps' traces on one x axis, as uPlot wants them (#299 R3, R4). uPlot draws
// every series against one array of xs, and two laps are sampled at different
// moments, so the xs are both laps' merged, each lap's values null where it has
// no sample (its line spans the gap). The readout reads each lap at its own
// nearest sample instead, so what it shows is a value the lap really had.
import type { Trace } from "@/api/hooks";

import { CHANNELS, X_AXIS, type ChannelId } from "./channels";

type Column = (number | null)[];

export interface Aligned {
  xs: number[];
  /** Per channel, lap A's and lap B's values against `xs`. */
  series: Record<ChannelId, [Column, Column]>;
}

/** Both laps (either may be missing) against their merged xs. */
export function align(a: Trace | null, b: Trace | null): Aligned {
  const xa = a ? X_AXIS.of(a) : [];
  const xb = b ? X_AXIS.of(b) : [];
  const xs: number[] = [];
  const ia: (number | null)[] = [];
  const ib: (number | null)[] = [];
  let i = 0;
  let j = 0;
  while (i < xa.length || j < xb.length) {
    const va = i < xa.length ? xa[i]! : Infinity;
    const vb = j < xb.length ? xb[j]! : Infinity;
    if (va === vb) {
      xs.push(va);
      ia.push(i++);
      ib.push(j++);
    } else if (va < vb) {
      xs.push(va);
      ia.push(i++);
      ib.push(null);
    } else {
      xs.push(vb);
      ia.push(null);
      ib.push(j++);
    }
  }
  const series = {} as Aligned["series"];
  for (const c of CHANNELS) {
    const ca = a ? a[c.field] : [];
    const cb = b ? b[c.field] : [];
    series[c.id] = [ia.map((k) => (k === null ? null : (ca[k] ?? null))), ib.map((k) => (k === null ? null : (cb[k] ?? null)))];
  }
  return { xs, series };
}

/** The index of the sample nearest `x` in ascending `xs`, or null when there are none. */
export function nearestIndex(xs: readonly number[], x: number): number | null {
  if (xs.length === 0 || !Number.isFinite(x)) {
    return null;
  }
  let lo = 0;
  let hi = xs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid]! <= x) {
      lo = mid;
    } else {
      hi = mid;
    }
  }
  return Math.abs(xs[hi]! - x) < Math.abs(xs[lo]! - x) ? hi : lo;
}

/** Past a lap's ends by more than this, it has no value to show. */
const BEYOND = 0.5;

/** One lap's sample nearest `x`: what the readout shows. Null past the lap's ends
 * (the other lap ran longer) or with no lap. */
export function sampleAt(trace: Trace | null, x: number | null): { x: number; index: number } | null {
  if (!trace || x === null) {
    return null;
  }
  const xs = X_AXIS.of(trace);
  const index = nearestIndex(xs, x);
  if (index === null || x < xs[0]! - BEYOND || x > xs[xs.length - 1]! + BEYOND) {
    return null;
  }
  return { x: xs[index]!, index };
}
