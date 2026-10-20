// The track map on lap compare (#350): lap A's line in plan, coloured by the pedals
// or by speed, lap B dashed over it, and both cars where the compare cursor is. A
// tap, a click or the arrow keys move the cursor, so the charts and the readout
// follow (R4). Two canvases: the lines, drawn when the laps, the colours or the
// size change, and the cursor's marks over them, drawn as the cursor moves.
//
// A canvas can't take a CSS variable, so the colours are read from the tokens when
// the lines are drawn (readChartTheme); nothing here has a colour of its own.
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import type { Trace } from "@/api/hooks";
import { LAP_B_DASH, readChartTheme, type ChartTheme } from "@/charts/theme";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { speedKph, traceTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { sampleAt } from "./align";
import { useCursor, type CursorStore } from "./cursor";
import { LapSwatch } from "./lap-swatch";
import {
  extentOf,
  fitBox,
  lineOf,
  MAP_MODES,
  mapSummary,
  nearestPoint,
  project,
  speedRange,
  strokeAt,
  unionExtent,
  type MapColours,
  type MapMode,
  type Projection,
} from "./map";

/** CSS pixels round the line inside the box. */
const PAD_PX = 12;
/** The map is at most this share of the screen's height (R6). */
const MAX_HEIGHT_SHARE = 0.4;
const LAP_B_WIDTH = 1.5;
/** PageUp and PageDown step this share of the lap's points. */
const PAGE_SHARE = 0.05;

const MODE_LABELS: Record<MapMode, string> = {
  pedals: "Pedals",
  speed: "Speed",
};

function coloursOf(theme: ChartTheme): MapColours {
  return {
    brake: theme.brake,
    throttle: theme.throttle,
    coast: theme.coast,
    speed: theme.speed,
  };
}

/** The container's width, and the most the map may be tall: 40% of the screen. */
function useRoom(): [(el: HTMLElement | null) => void, number, number] {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState(0);
  const [maxHeight, setMaxHeight] = useState(0);
  useEffect(() => {
    if (!el) {
      return;
    }
    const measure = () => {
      setWidth(Math.floor(el.clientWidth));
      setMaxHeight(Math.floor(window.innerHeight * MAX_HEIGHT_SHARE));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [el]);
  return [setEl, width, maxHeight];
}

/** A canvas sized for the screen's pixels, cleared, drawing in CSS pixels. */
function prepare(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D | null {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  return ctx;
}

function drawLapA(ctx: CanvasRenderingContext2D, a: Trace, proj: Projection, mode: MapMode, colours: MapColours) {
  const line = lineOf(a);
  const range = speedRange(a);
  const n = a.x.length;
  // Runs of steps with one stroke are one path, so a 1,500-point lap is a few
  // hundred strokes, not 1,500.
  const steps: [number, number][] = line.segments.flatMap((s) =>
    Array.from({ length: s.end - s.start }, (_, k): [number, number] => [s.start + k, s.start + k + 1]),
  );
  if (line.closed) {
    steps.push([n - 1, 0]);
  }
  let run: { colour: string; width: number } | null = null;
  let last = -1;
  const flush = () => {
    if (run) {
      ctx.strokeStyle = run.colour;
      ctx.lineWidth = run.width;
      ctx.stroke();
    }
  };
  for (const [i, j] of steps) {
    const s = strokeAt(a, i, mode, colours, range);
    const [x0, y0] = proj.toPx(a.x[i]!, a.z[i]!);
    const [x1, y1] = proj.toPx(a.x[j]!, a.z[j]!);
    if (!run || run.colour !== s.colour || run.width !== s.width || last !== i) {
      flush();
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      run = s;
    }
    ctx.lineTo(x1, y1);
    last = j;
  }
  flush();
}

function drawLapB(ctx: CanvasRenderingContext2D, b: Trace, proj: Projection, colour: string) {
  const line = lineOf(b);
  ctx.save();
  ctx.setLineDash(LAP_B_DASH);
  ctx.strokeStyle = colour;
  ctx.lineWidth = LAP_B_WIDTH;
  for (const s of line.segments) {
    ctx.beginPath();
    for (let i = s.start; i <= s.end; i++) {
      const [x, y] = proj.toPx(b.x[i]!, b.z[i]!);
      if (i === s.start) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    if (line.closed) {
      ctx.closePath();
    }
    ctx.stroke();
  }
  ctx.restore();
}

function Legend({ mode, a }: { mode: MapMode; a: Trace | null }) {
  const range = a ? speedRange(a) : null;
  return (
    <div data-slot="map-legend" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-muted">
      {mode === "pedals" ? (
        <ul aria-label="Line colours" className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-1.25 w-5 rounded-sm bg-pedal-brake" />
            Brake
          </li>
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-0.75 w-5 rounded-sm bg-pedal-throttle" />
            Throttle
          </li>
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-0.5 w-5 bg-pedal-coast" />
            Coasting
          </li>
        </ul>
      ) : (
        <p className="inline-flex items-center gap-2">
          <span className="num whitespace-nowrap">{range ? speedKph(range[0]) : "Slow"}</span>
          <span aria-hidden="true" className="inline-block h-1.5 w-20 rounded-sm bg-speed-scale" />
          <span className="num whitespace-nowrap">{range ? speedKph(range[1]) : "Fast"}</span>
          <span className="sr-only">: slow to fast</span>
        </p>
      )}
      <p className="inline-flex items-center gap-1.5">
        <LapSwatch side="b" />
        Lap B
      </p>
    </div>
  );
}

export interface TrackMapProps {
  a: Trace | null;
  b: Trace | null;
  /** Lap A's number and the track's name, for the summary. */
  lapA: number | null;
  track: string | null;
  cursor: CursorStore;
  /** Move the compare cursor to `x` (seconds into the lap): charts and readout follow. */
  onSeek: (x: number) => void;
  mode: MapMode;
  onMode: (mode: MapMode) => void;
  loading?: boolean;
  className?: string;
}

export function TrackMap({
  a,
  b,
  lapA,
  track,
  cursor,
  onSeek,
  mode,
  onMode,
  loading = false,
  className,
}: TrackMapProps) {
  const [room, width, maxHeight] = useRoom();
  const base = useRef<HTMLCanvasElement>(null);
  const marks = useRef<HTMLCanvasElement>(null);
  const target = useRef<HTMLDivElement>(null);
  const x = useCursor(cursor);
  const summaryId = useId();

  const extent = useMemo(() => unionExtent(a ? extentOf(a) : null, b ? extentOf(b) : null), [a, b]);
  const box = useMemo(
    () => (extent && width > 0 && maxHeight > 0 ? fitBox(extent, width, maxHeight, PAD_PX) : null),
    [extent, width, maxHeight],
  );
  const proj = useMemo(() => (extent && box ? project(extent, box, PAD_PX) : null), [extent, box]);
  const summary = a && lapA !== null ? mapSummary(a, lapA, track) : null;

  // The lines: on new laps, colours or size.
  useEffect(() => {
    const canvas = base.current;
    if (!canvas || !box || !proj) {
      return;
    }
    const ctx = prepare(canvas, box.width, box.height);
    if (!ctx) {
      return;
    }
    const theme = readChartTheme();
    if (a) {
      drawLapA(ctx, a, proj, mode, coloursOf(theme));
    }
    if (b) {
      drawLapB(ctx, b, proj, theme.lapB);
    }
  }, [a, b, mode, box, proj]);

  // The cursor's marks: a dot for lap A, a ring for lap B (R3).
  useEffect(() => {
    const canvas = marks.current;
    const el = target.current;
    if (!canvas || !el || !box || !proj) {
      return;
    }
    const ctx = prepare(canvas, box.width, box.height);
    if (!ctx) {
      return;
    }
    const theme = readChartTheme();
    const atA = sampleAt(a, x);
    const atB = sampleAt(b, x);
    if (b && atB) {
      const [px, py] = proj.toPx(b.x[atB.index]!, b.z[atB.index]!);
      ctx.beginPath();
      ctx.arc(px, py, 7, 0, 2 * Math.PI);
      ctx.lineWidth = 4;
      ctx.strokeStyle = theme.background;
      ctx.stroke();
      ctx.lineWidth = 2;
      ctx.strokeStyle = theme.lapB;
      ctx.stroke();
    }
    if (a && atA) {
      const [px, py] = proj.toPx(a.x[atA.index]!, a.z[atA.index]!);
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, 2 * Math.PI);
      ctx.fillStyle = theme.lapA;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = theme.text;
      ctx.stroke();
      el.dataset.dotA = `${Math.round(px)},${Math.round(py)}`;
    } else {
      delete el.dataset.dotA;
    }
    el.dataset.cursorA = atA ? String(atA.index) : "";
    el.dataset.cursorB = atB ? String(atB.index) : "";
  }, [a, b, x, box, proj]);

  // The point the map last moved the cursor to. The cursor's value reaches React a
  // frame later, so two quick key presses step from here, not from a stale cursor;
  // the cursor moving anywhere else (a chart scrub) forgets it.
  const sought = useRef<number | null>(null);
  useEffect(() => {
    if (sought.current !== null && (!a || a.t[sought.current] !== x)) {
      sought.current = null;
    }
  }, [a, x]);

  const seekIndex = (i: number) => {
    if (a && a.t.length > 0) {
      const at = Math.min(a.t.length - 1, Math.max(0, i));
      sought.current = at;
      onSeek(a.t[at]!);
    }
  };

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!a || !proj) {
      return;
    }
    const r = e.currentTarget.getBoundingClientRect();
    const i = nearestPoint(a, proj, e.clientX - r.left, e.clientY - r.top);
    if (i !== null) {
      seekIndex(i);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!a || a.t.length === 0) {
      return;
    }
    const at = sought.current ?? sampleAt(a, x)?.index;
    const page = Math.max(1, Math.round(a.t.length * PAGE_SHARE));
    const steps: Record<string, number> = {
      ArrowRight: 1,
      ArrowUp: 1,
      ArrowLeft: -1,
      ArrowDown: -1,
      PageUp: page,
      PageDown: -page,
    };
    if (e.key === "Home") {
      seekIndex(0);
    } else if (e.key === "End") {
      seekIndex(a.t.length - 1);
    } else if (e.key in steps) {
      seekIndex(at === undefined ? 0 : at + steps[e.key]!);
    } else {
      return;
    }
    e.preventDefault();
  };

  const modes = (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Map colours">
      {/* Speed is a chart's chip too: this row says it colours the map. */}
      <span aria-hidden="true" className="text-meta text-muted">
        Map by
      </span>
      {MAP_MODES.map((m) => (
        <Toggle key={m} variant="outline" pressed={mode === m} onPressedChange={(on) => on && onMode(m)}>
          {MODE_LABELS[m]}
        </Toggle>
      ))}
    </div>
  );

  const end = a && a.t.length > 0 ? a.t[a.t.length - 1]! : 0;
  const now = a ? sampleAt(a, x) : null;

  return (
    <figure data-slot="track-map" data-mode={mode} className={cn("min-w-0 space-y-2", className)}>
      {modes}
      <div ref={room} className="w-full min-w-0">
        {loading ? (
          <Skeleton className="h-48 w-full" />
        ) : a && box ? (
          <div
            ref={target}
            role="slider"
            tabIndex={0}
            aria-label="Track map: the cursor on lap A"
            aria-valuemin={0}
            aria-valuemax={end}
            aria-valuenow={now ? now.x : 0}
            aria-valuetext={now ? `${traceTime(now.x)} s into lap ${lapA}` : "No point picked"}
            aria-describedby={summary ? summaryId : undefined}
            data-slot="map"
            onClick={onClick}
            onKeyDown={onKeyDown}
            className="relative mx-auto cursor-crosshair touch-manipulation rounded-md"
            style={{ width: box.width, height: box.height }}
          >
            <canvas ref={base} role="img" aria-label={summary ?? "Track map"} className="absolute inset-0 size-full" />
            <canvas ref={marks} aria-hidden="true" className="absolute inset-0 size-full" />
          </div>
        ) : (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted">No map without lap A&apos;s trace.</p>
        )}
      </div>
      {!loading && a && <Legend mode={mode} a={a} />}
      {summary && (
        <figcaption id={summaryId} className="text-meta text-muted">
          {summary}
        </figcaption>
      )}
    </figure>
  );
}
