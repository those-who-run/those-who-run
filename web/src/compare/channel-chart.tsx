// One channel's chart in lap compare (#299 R3): lap A solid in the accent, lap B
// dashed in white, gear stepped, axes muted and the grid in the border colour,
// all from the tokens through UPlot. Every chart shares one cursor (uPlot.sync)
// and one x range.
import { useMemo } from "react";
import uPlot from "uplot";

import { themedAxis, LAP_B_DASH, type ChartTheme } from "@/charts/theme";
import { UPlot, type XRange } from "@/charts/UPlot";

import type { Aligned } from "./align";
import { X_AXIS, type Channel } from "./channels";
import type { CursorStore } from "./cursor";
import { SYNC_KEY } from "./sync";
/** The y axis's width, the same on every chart, so their x positions line up. */
const Y_AXIS_PX = 52;

export function ChannelChart({
  channel,
  aligned,
  height,
  showX,
  xRange,
  onXRange,
  cursor,
  label,
}: {
  channel: Channel;
  aligned: Aligned;
  height: number;
  /** The x axis's labels: on the last chart only. */
  showX: boolean;
  xRange: XRange | null;
  onXRange: (range: XRange | null) => void;
  cursor: CursorStore;
  label: string;
}) {
  const data = useMemo<uPlot.AlignedData>(
    () => [aligned.xs, ...aligned.series[channel.id]],
    [aligned, channel.id],
  );

  const options = useMemo(
    () =>
      (theme: ChartTheme): Omit<uPlot.Options, "width" | "height"> => {
        const paths = channel.stepped ? uPlot.paths.stepped?.({ align: 1 }) : undefined;
        return {
          // uPlot's own tooltip-free cursor: a vertical line only; the readout holds
          // the values.
          cursor: {
            sync: { key: SYNC_KEY, setSeries: false },
            y: false,
            points: { show: false },
          },
          // The same padding on every chart, with or without the x axis's labels, so
          // their plot areas, and the cursor lines in them, line up.
          padding: [8, 24, showX ? 0 : 8, 0],
          scales: {
            x: { time: false },
            y: channel.range ? { range: [channel.range[0], channel.range[1]] } : {},
          },
          axes: [
            themedAxis(theme, {
              show: showX,
              values: (_u, splits) => splits.map((v) => X_AXIS.format(v)),
            }),
            themedAxis(theme, {
              size: Y_AXIS_PX,
              values: (_u, splits) => splits.map((v) => channel.format(v)),
              ...(channel.stepped ? { incrs: [1, 2, 5] } : {}),
            }),
          ],
          series: [
            {},
            { label: "Lap A", stroke: theme.lapA, width: 2, spanGaps: true, paths },
            { label: "Lap B", stroke: theme.lapB, width: 1.5, dash: LAP_B_DASH, spanGaps: true, paths },
          ],
          hooks: {
            // Every chart in the group hears the cursor; the store keeps one value.
            setCursor: [
              (u) => {
                const left = u.cursor.left ?? -1;
                if (left >= 0) {
                  cursor.set(u.posToVal(left, "x"));
                }
              },
            ],
          },
        };
      },
    [channel, showX, cursor],
  );

  return (
    <UPlot
      options={options}
      data={data}
      height={height}
      xRange={xRange}
      onXRange={onXRange}
      minSpan={X_AXIS.minSpan}
      label={label}
    />
  );
}
