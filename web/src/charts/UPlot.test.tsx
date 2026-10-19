// The chart wrapper's lifecycle (#299 R7): the plot is made in an effect, new data
// is setData and a new size setSize (never a new plot), and unmount destroys it.
// uPlot itself needs a canvas, which jsdom lacks, so it is a stand-in here.
import { cleanup, render } from "@testing-library/react";
import type uPlot from "uplot";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clampRange, dataExtent, pinchRange } from "./gestures";

const made: FakePlot[] = [];

class FakePlot {
  opts: Record<string, unknown>;
  data: unknown[][];
  width: number;
  height: number;
  scales: { x: { min?: number; max?: number } } = { x: {} };
  over = document.createElement("div");
  select = { left: 0, top: 0, width: 0, height: 0 };
  setData = vi.fn((data: unknown[][]) => {
    this.data = data;
  });
  setSize = vi.fn(({ width, height }: { width: number; height: number }) => {
    this.width = width;
    this.height = height;
  });
  setScale = vi.fn((_key: string, { min, max }: { min: number; max: number }) => {
    this.scales.x = { min, max };
  });
  setSelect = vi.fn();
  setCursor = vi.fn();
  posToVal = vi.fn((px: number) => px / 10);
  destroy = vi.fn();

  constructor(opts: Record<string, unknown>, data: unknown[][]) {
    this.opts = opts;
    this.data = data;
    this.width = opts.width as number;
    this.height = opts.height as number;
    made.push(this);
  }
}

vi.mock("uplot", () => ({ default: FakePlot }));

class FakeResizeObserver {
  static last: FakeResizeObserver | null = null;
  cb: () => void;
  constructor(cb: () => void) {
    this.cb = cb;
    FakeResizeObserver.last = this;
  }
  observe = vi.fn();
  disconnect = vi.fn();
}

beforeEach(() => {
  made.length = 0;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const { UPlot } = await import("./UPlot");

const options = () => ({ series: [{}, { label: "A" }] });
const DATA: uPlot.AlignedData = [
  [0, 1, 2],
  [5, 6, 7],
];

describe("UPlot", () => {
  it("makes one plot, themed from the tokens, with the size it is given", () => {
    document.documentElement.style.setProperty("--lap-a", "red-ish");
    const theme = vi.fn<(theme: unknown) => ReturnType<typeof options>>(options);
    render(<UPlot options={theme} data={DATA} height={140} label="Speed" />);
    expect(made).toHaveLength(1);
    expect(theme.mock.calls[0]![0]).toMatchObject({ lapA: "red-ish" });
    expect(made[0]!.height).toBe(140);
    expect(made[0]!.opts.legend).toMatchObject({ show: false });
  });

  it("names the chart for a screen reader", () => {
    const { getByRole } = render(<UPlot options={options} data={DATA} height={140} label="Speed, laps 1 and 2" />);
    expect(getByRole("img", { name: "Speed, laps 1 and 2" })).toBeTruthy();
  });

  it("calls setData for new data and setSize for a new height, never making a new plot", () => {
    const { rerender } = render(<UPlot options={options} data={DATA} height={140} label="Speed" />);
    const next: uPlot.AlignedData = [
      [0, 1],
      [3, 4],
    ];
    rerender(<UPlot options={options} data={next} height={140} label="Speed" />);
    rerender(<UPlot options={options} data={next} height={180} label="Speed" />);
    expect(made).toHaveLength(1);
    expect(made[0]!.setData).toHaveBeenCalledWith(next, true);
    expect(made[0]!.setSize).toHaveBeenCalledWith({ width: made[0]!.width, height: 180 });
  });

  it("calls setSize when the container's width changes", () => {
    render(<UPlot options={options} data={DATA} height={140} label="Speed" />);
    const plot = made[0]!;
    const box = document.querySelector<HTMLElement>("[data-slot=chart]")!;
    Object.defineProperty(box, "clientWidth", { value: 358, configurable: true });
    FakeResizeObserver.last!.cb();
    expect(plot.setSize).toHaveBeenCalledWith({ width: 358, height: 140 });
    expect(made).toHaveLength(1);
  });

  it("destroys the plot on unmount", () => {
    const { unmount } = render(<UPlot options={options} data={DATA} height={140} label="Speed" />);
    unmount();
    expect(made[0]!.destroy).toHaveBeenCalledTimes(1);
  });

  it("shows the x range asked for, and all of the data for null", () => {
    const { rerender } = render(<UPlot options={options} data={DATA} height={140} xRange={[0.5, 1.5]} label="S" />);
    expect(made[0]!.setScale).toHaveBeenLastCalledWith("x", { min: 0.5, max: 1.5 });
    rerender(<UPlot options={options} data={DATA} height={140} xRange={null} label="S" />);
    expect(made[0]!.setScale).toHaveBeenLastCalledWith("x", { min: 0, max: 2 });
  });

  it("turns a drag's selection into a request for that x range", () => {
    const onXRange = vi.fn();
    render(<UPlot options={options} data={DATA} height={140} onXRange={onXRange} label="S" />);
    const plot = made[0]!;
    plot.select = { left: 10, top: 0, width: 30, height: 100 };
    const hooks = plot.opts.hooks as { setSelect: ((u: FakePlot) => void)[] };
    hooks.setSelect.forEach((h) => h(plot));
    expect(onXRange).toHaveBeenCalledWith([1, 4]);
    expect(plot.setSelect).toHaveBeenCalledWith({ left: 0, top: 0, width: 0, height: 0 }, false);
  });
});

describe("the gestures' arithmetic", () => {
  it("keeps the values under two fingers under them", () => {
    // 10 and 20 s first under 100 and 200 px; the fingers move to 50 and 250 px.
    const r = pinchRange(10, 20, 50, 250, 300)!;
    expect(r[0]).toBeCloseTo(7.5);
    expect(r[1]).toBeCloseTo(22.5);
  });

  it("keeps a range inside the data, no narrower than the smallest span", () => {
    expect(clampRange(-5, 10, [0, 100], 1)).toEqual([0, 15]);
    expect(clampRange(50, 50.2, [0, 100], 1)).toEqual([49.6, 50.6]);
    expect(clampRange(-10, 200, [0, 100], 1)).toBeNull();
  });

  it("finds the data's extent", () => {
    expect(dataExtent([[1, 2, 5]])).toEqual([1, 5]);
    expect(dataExtent([[]])).toBeNull();
  });
});
