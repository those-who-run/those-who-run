// Chart colours and type from the design tokens (ADR 0004 point 1, docs/design.md,
// UPlot). A canvas can't take a CSS variable, so the values are read from the
// page when a chart is made; nothing here has a colour of its own.
import type uPlot from "uplot";

export interface ChartTheme {
  /** Axis labels and ticks' text: `--text-muted`. */
  axis: string;
  /** Grid lines and ticks: `--border`. */
  grid: string;
  /** Lap A: `--lap-a` (the accent), solid. */
  lapA: string;
  /** Lap B: `--lap-b` (white), dashed. */
  lapB: string;
  /** Axis type: `text-meta` (13 px) in the UI family. */
  font: string;
}

/** Lap B's dash, so A and B never differ by colour alone (ADR 0004 point 3). */
export const LAP_B_DASH = [6, 4];

function token(style: CSSStyleDeclaration, name: string): string {
  return style.getPropertyValue(name).trim();
}

/** The theme as the page's tokens set it now. */
export function readChartTheme(el: Element = document.documentElement): ChartTheme {
  const style = getComputedStyle(el);
  const family = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";
  return {
    axis: token(style, "--text-muted"),
    grid: token(style, "--border"),
    lapA: token(style, "--lap-a"),
    lapB: token(style, "--lap-b"),
    font: `13px ${family}`,
  };
}

/** An axis in the theme: muted labels, grid lines in the border colour. */
export function themedAxis(theme: ChartTheme, axis: uPlot.Axis = {}): uPlot.Axis {
  return {
    stroke: theme.axis,
    font: theme.font,
    grid: { stroke: theme.grid, width: 1 },
    ticks: { stroke: theme.grid, width: 1, size: 4 },
    ...axis,
  };
}
