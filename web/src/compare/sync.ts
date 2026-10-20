// The cursor group every compare chart is in (uPlot.sync), and a way to move its
// cursor from outside the charts, as the track map does (#350 R4).
import uPlot from "uplot";

import type { CursorStore } from "./cursor";

export const SYNC_KEY = "twr-compare";

/** Moves the shared cursor to `x` (seconds into the lap): one chart's cursor is
 * set and published to the group, as a pointer move is, and the store gets `x`
 * itself, so the readout follows even with every chart hidden or `x` outside the
 * zoomed range. */
export function seekCharts(cursor: CursorStore, x: number): void {
  const u = uPlot.sync(SYNC_KEY).plots[0];
  if (u) {
    // setCursor's third argument publishes to the sync group; uPlot's types leave it out.
    const setCursor = u.setCursor as (opts: { left: number; top: number }, fire?: boolean, pub?: boolean) => void;
    setCursor({ left: u.valToPos(x, "x"), top: u.over.clientHeight / 2 }, true, true);
  }
  cursor.set(x);
}
