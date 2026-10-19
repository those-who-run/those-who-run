// The race story (#300): one point per complete lap between the stat tiles and the
// laps table, so a race reads as a shape before its numbers. Lap time on the left
// axis, joined by a line, the best lap larger in `--timing-best`, pit and out laps
// hollow; for a race, position on the right axis, inverted and stepped (dashed, so
// the two lines never differ by colour alone).
//
// A lap is highlighted from here or from its table row, both ways, through the
// session page's state; tapping a point picks it for compare as its checkbox does.
// The readout above the chart names the lap under the finger, never the chart
// itself. The figures are in ./story.ts; this file is a lazy chunk (it carries
// uPlot), loaded only once the page has three complete laps.
import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import uPlot from "uplot";

import { LAP_B_DASH, themedAxis, type ChartTheme } from "@/charts/theme";
import { UPlot } from "@/charts/UPlot";
import { LapTime } from "@/components/lap-time";
import { Position } from "@/components/position";
import { badgeVariants } from "@/components/ui/badge";
import { traceTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { Story, StoryPoint } from "./story";

/** At most 160 px on a phone (R5); taller from 600 px of width. */
const PHONE_CHART_PX = 150;
const WIDE_CHART_PX = 180;
const WIDE_QUERY = "(min-width: 600px)";
/** The lap axis's height, the lap-time axis's width, and the position axis's. */
const X_AXIS_PX = 30;
const Y_AXIS_PX = 48;
const POS_AXIS_PX = 36;
/** A tap that moved further than this was a scroll or a scrub, not a pick. */
const TAP_SLOP_PX = 8;

function useWide(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== "function") {
        return () => {};
      }
      const q = window.matchMedia(WIDE_QUERY);
      q.addEventListener("change", onChange);
      return () => q.removeEventListener("change", onChange);
    },
    () => typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches,
    () => false,
  );
}

const FLAG_LABEL = { pit: "Pit", out: "Out" } as const;

/** The swatch for a line in the key: solid for lap time, dashed for position. */
function Swatch({ dashed }: { dashed?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block w-4 border-t-2 align-middle", dashed ? "border-dashed border-muted" : "border-fg")}
    />
  );
}

/** Above the chart: the highlighted lap's time, flags and position, or the key. */
function Readout({ point, positions }: { point: StoryPoint | null; positions: Story["positions"] }) {
  if (!point) {
    return (
      <p data-slot="story-key" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Swatch /> Lap time
        </span>
        {positions && (
          <span className="inline-flex items-center gap-1.5">
            <Swatch dashed /> Position
          </span>
        )}
        <span>Tap a lap to pick it.</span>
      </p>
    );
  }
  return (
    <p data-slot="story-readout" data-lap={point.lap} className="flex flex-wrap items-center gap-x-3 text-sm">
      <span className="font-semibold">Lap {point.lap}</span>
      <LapTime ms={point.ms} best={point.best} size="sm" />
      {point.flags.map((f) => (
        <span key={f} data-flag={f} className={badgeVariants({ variant: "outline" })}>
          {FLAG_LABEL[f]}
        </span>
      ))}
      {positions && <Position position={point.position} cars={positions.cars} size="sm" />}
    </p>
  );
}

interface Marks {
  story: Story;
  picks: number[];
  highlight: number | null;
}

/** The points, drawn over uPlot's lines: the best larger and in its colour, pit and
 * out laps hollow, an out-of-range lap a hollow triangle at the edge it passed, a
 * ring round each pick, and a hairline through the highlighted lap. */
function drawMarks(u: uPlot, theme: ChartTheme, { story, picks, highlight }: Marks) {
  const ctx = u.ctx;
  const px = uPlot.pxRatio;
  const { top, height } = u.bbox;
  ctx.save();
  // uPlot leaves the position line's dash set.
  ctx.setLineDash([]);
  if (highlight != null && story.points.some((p) => p.lap === highlight)) {
    const x = Math.round(u.valToPos(highlight, "x", true)) + 0.5;
    ctx.strokeStyle = theme.axis;
    ctx.lineWidth = px;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + height);
    ctx.stroke();
  }
  for (const p of story.points) {
    const x = u.valToPos(p.lap, "x", true);
    const y = u.valToPos(p.drawnMs, "y", true);
    const r = (p.best ? 5 : 3.5) * px;
    const colour = p.best ? theme.best : theme.text;
    ctx.lineWidth = 1.5 * px;
    ctx.strokeStyle = colour;
    ctx.fillStyle = p.hollow ? theme.background : colour;
    ctx.beginPath();
    if (p.edge) {
      // A triangle pointing past the edge: the lap is slower (or quicker) than shown.
      const s = 5 * px;
      const dir = p.edge === "above" ? -1 : 1;
      ctx.moveTo(x, y + dir * s);
      ctx.lineTo(x - s, y - dir * s * 0.6);
      ctx.lineTo(x + s, y - dir * s * 0.6);
      ctx.closePath();
    } else {
      ctx.arc(x, y, r, 0, 2 * Math.PI);
    }
    ctx.fill();
    ctx.stroke();
    if (picks.includes(p.lap)) {
      ctx.strokeStyle = theme.text;
      ctx.beginPath();
      ctx.arc(x, y, r + 3.5 * px, 0, 2 * Math.PI);
      ctx.stroke();
    }
  }
  ctx.restore();
}

export function RaceStory({
  story,
  picks,
  highlight,
  onHighlight,
  onPick,
}: {
  story: Story;
  /** The laps picked for compare (`?pick=`). */
  picks: number[];
  /** The lap highlighted here or in the table. */
  highlight: number | null;
  onHighlight: (lap: number | null) => void;
  /** A tap on a point: picks or unpicks its lap, as its checkbox does. */
  onPick: (lap: number) => void;
}) {
  const wide = useWide();
  const latest = useRef({ story, picks, highlight, onHighlight, onPick });
  useEffect(() => {
    latest.current = { story, picks, highlight, onHighlight, onPick };
  });

  const hasPos = story.positions != null;
  const data = useMemo<uPlot.AlignedData>(() => {
    const xs = story.points.map((p) => p.lap);
    const ys = story.points.map((p) => p.drawnMs);
    return hasPos ? [xs, ys, story.points.map((p) => p.position)] : [xs, ys];
  }, [story, hasPos]);
  // A little room either side of the first and last laps, so their points clear the
  // axes.
  const first = story.points[0]!.lap;
  const last = story.points[story.points.length - 1]!.lap;
  const xRange = useMemo(() => [first - 0.4, last + 0.4] as const, [first, last]);

  const options = useMemo(
    () =>
      (theme: ChartTheme): Omit<uPlot.Options, "width" | "height"> => ({
        // The highlight is a lap, not a pixel: no cursor lines and no drag; the
        // marks hook draws the hairline at the lap.
        cursor: { x: false, y: false, points: { show: false }, drag: { x: false, y: false } },
        padding: [12, hasPos ? 4 : 12, 0, 4],
        scales: {
          x: { time: false },
          y: { range: () => latest.current.story.yRange },
          ...(hasPos
            ? {
                pos: {
                  dir: -1,
                  range: () => [0.5, (latest.current.story.positions?.cars ?? 1) + 0.5] as uPlot.Range.MinMax,
                },
              }
            : {}),
        },
        axes: [
          themedAxis(theme, {
            size: X_AXIS_PX,
            incrs: [1, 2, 5, 10, 20],
            values: (_u, splits) => splits.map((v) => (Number.isInteger(v) ? String(v) : "")),
          }),
          themedAxis(theme, {
            size: Y_AXIS_PX,
            values: (_u, splits) => splits.map((v) => traceTime(v / 1000)),
          }),
          ...(hasPos
            ? [
                themedAxis(theme, {
                  scale: "pos",
                  side: 1,
                  size: POS_AXIS_PX,
                  grid: { show: false },
                  incrs: [1, 2, 5, 10],
                  values: (_u, splits) => splits.map((v) => (Number.isInteger(v) ? `P${v}` : "")),
                }),
              ]
            : []),
        ],
        series: [
          {},
          { label: "Lap time", scale: "y", stroke: theme.text, width: 1.5, points: { show: false } },
          ...(hasPos
            ? [
                {
                  label: "Position",
                  scale: "pos",
                  stroke: theme.axis,
                  width: 1.5,
                  dash: LAP_B_DASH,
                  spanGaps: true,
                  paths: uPlot.paths.stepped?.({ align: 1 }),
                  points: { show: false },
                },
              ]
            : []),
        ],
        hooks: {
          draw: [(u) => drawMarks(u, theme, latest.current)],
          // The lap under the mouse or finger, for the table and the readout. The
          // cursor leaving is not a lap: a mouse leaving clears the highlight (below),
          // but a finger lifting keeps it, so the tapped lap stays named.
          setCursor: [
            (u) => {
              const i = u.cursor.idx;
              const lap = i == null ? null : (u.data[0][i] ?? null);
              if (lap != null && lap !== latest.current.highlight) {
                latest.current.onHighlight(lap);
              }
            },
          ],
        },
      }),
    [hasPos],
  );

  // A tap or click on the plot picks the nearest lap; a drag or a scroll doesn't.
  const plot = useRef<uPlot | null>(null);
  const onCreate = useCallback((u: uPlot) => {
    plot.current = u;
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => {
      down = { x: e.clientX, y: e.clientY };
    };
    const onClick = (e: MouseEvent) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > TAP_SLOP_PX) {
        return;
      }
      const i = u.posToIdx(e.clientX - u.over.getBoundingClientRect().left);
      const lap = u.data[0][i];
      if (lap != null) {
        latest.current.onHighlight(lap);
        latest.current.onPick(lap);
      }
    };
    // Only a mouse: after a tap the browser sends a mouseleave of its own.
    const onLeave = (e: PointerEvent) => {
      if (e.pointerType === "mouse") {
        latest.current.onHighlight(null);
      }
    };
    u.over.addEventListener("pointerdown", onDown);
    u.over.addEventListener("click", onClick);
    u.over.addEventListener("pointerleave", onLeave);
    return () => {
      u.over.removeEventListener("pointerdown", onDown);
      u.over.removeEventListener("click", onClick);
      u.over.removeEventListener("pointerleave", onLeave);
      if (plot.current === u) {
        plot.current = null;
      }
    };
  }, []);

  // A new pick or highlight (from the table, too) redraws the marks only.
  useEffect(() => {
    plot.current?.redraw(false, false);
  }, [picks, highlight]);

  const point = story.points.find((p) => p.lap === highlight) ?? null;
  return (
    // What the canvas draws is on the section too, for tests and the curious, as
    // UPlot puts its x range on the chart.
    <section
      aria-labelledby="race-story-title"
      data-slot="race-story"
      data-points={story.points.map((p) => p.lap).join(",")}
      data-best={story.points.find((p) => p.best)?.lap}
      data-hollow={story.points
        .filter((p) => p.hollow)
        .map((p) => p.lap)
        .join(",")}
      data-edges={story.points
        .filter((p) => p.edge)
        .map((p) => `${p.lap}:${p.edge}`)
        .join(",")}
      data-positions={story.positions ? story.points.map((p) => p.position ?? "").join(",") : undefined}
      data-y-range={story.yRange.map((v) => Math.round(v)).join("-")}
      className="space-y-2"
    >
      <h2 id="race-story-title" className="text-xl font-semibold">
        Race story
      </h2>
      <div className="min-h-7">
        <Readout point={point} positions={story.positions} />
      </div>
      <UPlot
        options={options}
        data={data}
        height={wide ? WIDE_CHART_PX : PHONE_CHART_PX}
        xRange={xRange}
        onCreate={onCreate}
        label={story.summary}
        className="cursor-pointer"
      />
    </section>
  );
}
