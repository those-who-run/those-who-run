// Touch on a uPlot chart (#299 R4, R5). uPlot's cursor follows the mouse only, so a
// finger is mapped onto it here:
//
// - one finger moving sideways scrubs: the cursor follows it (and, through
//   uPlot.sync, every chart in the group);
// - one finger moving up or down is the page scrolling: the chart's `touch-action:
//   pan-y` (styles/charts.css) leaves that to the browser, and this lets go;
// - two fingers pinch the x range;
// - a double tap resets it.
//
// A tap shows the values where it lands. Nothing here reads the DOM at import.
import type uPlot from "uplot";

export type XRange = readonly [number, number];

/** How far a finger moves before the gesture counts as a scrub or a scroll. */
const SLOP_PX = 8;
/** Two taps this close in time and space are a double tap. */
const DOUBLE_TAP_MS = 300;
const DOUBLE_TAP_PX = 30;

export interface Gestures {
  /** The x range the data covers: a pinch never zooms out past it. */
  extent: () => XRange | null;
  /** The smallest x range a pinch may reach. */
  minSpan: number;
  /** A pinch, with the new range; null on a double tap (reset). */
  onXRange: (range: XRange | null) => void;
}

/** The whole of uPlot data's x range (its xs ascend), or null when there is none. */
export function dataExtent(data: uPlot.AlignedData): XRange | null {
  const xs = data[0];
  if (!xs || xs.length === 0) {
    return null;
  }
  const lo = xs[0]!;
  const hi = xs[xs.length - 1]!;
  return hi > lo ? [lo, hi] : null;
}

/** `[min, max]` kept inside `extent` and at least `minSpan` wide; null when it
 * covers the whole extent (no zoom). */
export function clampRange(min: number, max: number, extent: XRange, minSpan: number): XRange | null {
  const [lo, hi] = extent;
  const full = hi - lo;
  if (!(full > 0) || !Number.isFinite(min) || !Number.isFinite(max)) {
    return null;
  }
  const span = Math.max(max - min, Math.min(minSpan, full));
  if (span >= full) {
    return null;
  }
  const a = Math.min(Math.max((min + max) / 2 - span / 2, lo), hi - span);
  return [a, a + span];
}

/** The x range that keeps the values first under two fingers (`v1`, `v2`) under
 * where they are now (`q1`, `q2`, CSS pixels from the plot's left), on a plot
 * `width` pixels wide. */
export function pinchRange(v1: number, v2: number, q1: number, q2: number, width: number): XRange | null {
  if (Math.abs(q2 - q1) < 1 || v1 === v2) {
    return null;
  }
  const perPx = (v2 - v1) / (q2 - q1);
  if (!(perPx > 0)) {
    return null;
  }
  const min = v1 - q1 * perPx;
  return [min, min + width * perPx];
}

/** Listens for touch on `u`'s plot area; returns the cleanup. */
export function attachGestures(u: uPlot, g: Gestures): () => void {
  const over = u.over;
  let mode: "pending" | "scrub" | "scroll" | "pinch" | null = null;
  let start = { x: 0, y: 0 };
  let pinch: { v1: number; v2: number } | null = null;
  let lastTap = { at: 0, x: 0, y: 0 };
  let moved = false;

  const local = (t: Touch) => {
    const r = over.getBoundingClientRect();
    return {
      left: Math.min(Math.max(t.clientX - r.left, 0), r.width),
      top: Math.min(Math.max(t.clientY - r.top, 0), r.height),
    };
  };
  // setCursor's third argument publishes the move to the sync group, as a mouse
  // move does; uPlot's types leave it out.
  const setCursor = u.setCursor as (opts: { left: number; top: number }, fire?: boolean, pub?: boolean) => void;
  const scrubTo = (t: Touch) => setCursor(local(t), true, true);

  const onStart = (e: TouchEvent) => {
    if (e.touches.length >= 2) {
      const [a, b] = [local(e.touches[0]!), local(e.touches[1]!)];
      const [left, right] = a.left <= b.left ? [a, b] : [b, a];
      pinch = { v1: u.posToVal(left.left, "x"), v2: u.posToVal(right.left, "x") };
      mode = "pinch";
      moved = true;
      e.preventDefault();
      return;
    }
    const t = e.touches[0]!;
    start = { x: t.clientX, y: t.clientY };
    mode = "pending";
    moved = false;
    scrubTo(t);
  };

  const onMove = (e: TouchEvent) => {
    if (mode === "pinch" && pinch && e.touches.length >= 2) {
      e.preventDefault();
      const [a, b] = [local(e.touches[0]!), local(e.touches[1]!)];
      const [left, right] = a.left <= b.left ? [a, b] : [b, a];
      const extent = g.extent();
      const next = pinchRange(pinch.v1, pinch.v2, left.left, right.left, over.clientWidth);
      if (extent && next) {
        g.onXRange(clampRange(next[0], next[1], extent, g.minSpan));
      }
      return;
    }
    const t = e.touches[0];
    if (!t || mode === "scroll" || mode === null) {
      return;
    }
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    if (mode === "pending") {
      if (Math.abs(dx) < SLOP_PX && Math.abs(dy) < SLOP_PX) {
        return;
      }
      moved = true;
      mode = Math.abs(dx) > Math.abs(dy) ? "scrub" : "scroll";
      if (mode === "scroll") {
        return; // the browser scrolls the page (touch-action: pan-y)
      }
    }
    if (e.cancelable) {
      e.preventDefault();
    }
    scrubTo(t);
  };

  const onEnd = (e: TouchEvent) => {
    if (e.touches.length > 0) {
      return; // a finger is still down
    }
    if (mode === "pending" && !moved && e.changedTouches[0]) {
      const t = e.changedTouches[0];
      const now = e.timeStamp;
      const near = Math.hypot(t.clientX - lastTap.x, t.clientY - lastTap.y) < DOUBLE_TAP_PX;
      if (now - lastTap.at < DOUBLE_TAP_MS && near) {
        lastTap = { at: 0, x: 0, y: 0 };
        g.onXRange(null);
        e.preventDefault(); // no zoom of the page, no emulated mouse
      } else {
        lastTap = { at: now, x: t.clientX, y: t.clientY };
      }
    }
    mode = null;
    pinch = null;
  };

  const opts: AddEventListenerOptions = { passive: false };
  over.addEventListener("touchstart", onStart, opts);
  over.addEventListener("touchmove", onMove, opts);
  over.addEventListener("touchend", onEnd, opts);
  over.addEventListener("touchcancel", onEnd, opts);
  return () => {
    over.removeEventListener("touchstart", onStart, opts);
    over.removeEventListener("touchmove", onMove, opts);
    over.removeEventListener("touchend", onEnd, opts);
    over.removeEventListener("touchcancel", onEnd, opts);
  };
}
