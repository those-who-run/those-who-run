// The one wrapper for every chart (#299 R7, ADR 0003 point 2; docs/design.md,
// UPlot). Lap compare uses it now; the session page's charts (#300), the track map
// and delta (#117) and corners (#34) reuse it.
//
// - The plot is made in an effect, from `options(theme)`, with the theme read from
//   the design tokens (./theme.ts). It is made again only when `options` changes,
//   so the caller memoises it.
// - New `data` is `setData`, and a new width (a ResizeObserver on the container) or
//   `height` is `setSize`: a render never rebuilds the plot.
// - The plot is destroyed on unmount.
// - The x range is controlled: `xRange` sets it (null is the whole of the data),
//   and a drag (mouse), a pinch, a double click or a double tap asks for a new one
//   through `onXRange`. Charts that share a range share the state that feeds it.
// - Touch scrubs the cursor (./gestures.ts); `cursor.sync` in `options` shares the
//   cursor across a group (`uPlot.sync`).
//
// uPlot is about 50 KB: import this only from a lazy route, never from the entry.
import "uplot/dist/uPlot.min.css";
import "@/styles/charts.css";

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import { cn } from "@/lib/utils";

import { attachGestures, dataExtent, type XRange } from "./gestures";
import { readChartTheme, type ChartTheme } from "./theme";

export type { XRange } from "./gestures";
export type { ChartTheme } from "./theme";

export interface UPlotProps {
  /** The plot's options without its size, from the theme. Memoise it: a new
   * function makes a new plot. */
  options: (theme: ChartTheme) => Omit<uPlot.Options, "width" | "height">;
  /** uPlot's aligned data: `[xs, ...series]`, with xs ascending. */
  data: uPlot.AlignedData;
  /** CSS pixels; the width is the container's. */
  height: number;
  /** The x range shown; null or absent shows all of the data. */
  xRange?: XRange | null;
  /** Asked for a new x range: a drag, a pinch, or null for a double click or tap.
   * Without it the chart doesn't zoom. */
  onXRange?: (range: XRange | null) => void;
  /** The smallest x range a pinch may reach, in x units (default: 1). */
  minSpan?: number;
  /** Called with the plot once it is made (and again if it is made anew); may
   * return a cleanup. For hooks the options can't reach, such as a readout. */
  onCreate?: (u: uPlot) => void | (() => void);
  /** What the chart shows, for a screen reader: "Speed, lap 5 against lap 6". */
  label: string;
  className?: string;
}

function sameRange(u: uPlot, r: XRange): boolean {
  const { min, max } = u.scales.x ?? {};
  return min === r[0] && max === r[1];
}

/** Shows `range` (or all of the data) if it isn't shown already. */
function applyRange(u: uPlot, range: XRange | null | undefined) {
  const r = range ?? dataExtent(u.data);
  if (r && !sameRange(u, r)) {
    u.setScale("x", { min: r[0], max: r[1] });
  }
}

export function UPlot({
  options,
  data,
  height,
  xRange = null,
  onXRange,
  minSpan = 1,
  onCreate,
  label,
  className,
}: UPlotProps) {
  const box = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  // The latest props, for the plot's hooks and listeners, which outlive a render.
  const latest = useRef({ data, height, xRange, onXRange, minSpan, onCreate });
  useEffect(() => {
    latest.current = { data, height, xRange, onXRange, minSpan, onCreate };
  });

  // Make the plot: on mount and when the options change.
  useEffect(() => {
    const el = box.current;
    if (!el) {
      return;
    }
    const base = options(readChartTheme());
    const zoomable = () => latest.current.onXRange !== undefined;
    const opts: uPlot.Options = {
      ...base,
      width: Math.max(1, Math.floor(el.clientWidth)),
      height: latest.current.height,
      legend: { show: false, ...base.legend },
      cursor: {
        ...base.cursor,
        // A drag selects a range, which becomes the x range through onXRange, never
        // by uPlot setting its own scale: the range stays controlled.
        drag: { x: true, y: false, setScale: false, ...base.cursor?.drag },
        bind: {
          ...base.cursor?.bind,
          dblclick: () => () => {
            if (zoomable()) {
              latest.current.onXRange?.(null);
            }
            return null;
          },
        },
      },
      hooks: {
        ...base.hooks,
        // The x range shown, on the element, for tests and the curious.
        setScale: [
          ...(base.hooks?.setScale ?? []),
          (u, key) => {
            const { min, max } = u.scales.x ?? {};
            if (key === "x" && min !== undefined && max !== undefined) {
              el.dataset.xRange = `${min}-${max}`;
            }
          },
        ],
        setSelect: [
          ...(base.hooks?.setSelect ?? []),
          (u) => {
            const { left, width } = u.select;
            if (width > 2 && zoomable()) {
              const min = u.posToVal(left, "x");
              const max = u.posToVal(left + width, "x");
              latest.current.onXRange?.([min, max]);
            }
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
          },
        ],
      },
    };
    const u = new uPlot(opts, latest.current.data, el);
    plot.current = u;
    applyRange(u, latest.current.xRange);
    const detach = attachGestures(u, {
      extent: () => dataExtent(u.data),
      get minSpan() {
        return latest.current.minSpan;
      },
      onXRange: (r) => {
        if (zoomable()) {
          latest.current.onXRange?.(r);
        }
      },
    });
    const cleanup = latest.current.onCreate?.(u);

    // A new width: setSize, never a new plot.
    const resize = new ResizeObserver(() => {
      const width = Math.max(1, Math.floor(el.clientWidth));
      if (width !== u.width) {
        u.setSize({ width, height: u.height });
      }
    });
    resize.observe(el);

    return () => {
      resize.disconnect();
      cleanup?.();
      detach();
      u.destroy();
      if (plot.current === u) {
        plot.current = null;
      }
    };
  }, [options]);

  // New data: setData, keeping the x range asked for.
  useEffect(() => {
    const u = plot.current;
    if (u && u.data !== data) {
      u.setData(data, true);
      applyRange(u, latest.current.xRange);
    }
  }, [data]);

  // A new height: setSize.
  useEffect(() => {
    const u = plot.current;
    if (u && u.height !== height) {
      u.setSize({ width: u.width, height });
    }
  }, [height]);

  // A new x range.
  useEffect(() => {
    const u = plot.current;
    if (u) {
      applyRange(u, xRange);
    }
  }, [xRange]);

  return (
    <div
      ref={box}
      role="img"
      aria-label={label}
      data-slot="chart"
      className={cn("twr-chart w-full min-w-0 overflow-hidden", className)}
    />
  );
}
