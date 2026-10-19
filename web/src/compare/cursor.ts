// The shared cursor's x, for the readout (#299 R4). The first chart's setCursor hook
// writes it on every pointer or touch move; React hears of it at most once an
// animation frame, so only the readout re-renders, never the charts.
import { useSyncExternalStore } from "react";

export interface CursorStore {
  /** The cursor's x (seconds into the lap), or null before it has been anywhere. */
  get: () => number | null;
  set: (x: number | null) => void;
  subscribe: (listener: () => void) => () => void;
}

export function createCursorStore(
  frame: (cb: () => void) => unknown = (cb) =>
    typeof requestAnimationFrame === "function" ? requestAnimationFrame(cb) : setTimeout(cb, 16),
): CursorStore {
  let value: number | null = null;
  let pending: number | null = null;
  let scheduled = false;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (x) => {
      pending = x;
      if (scheduled) {
        return;
      }
      scheduled = true;
      frame(() => {
        scheduled = false;
        if (pending !== value) {
          value = pending;
          listeners.forEach((l) => l());
        }
      });
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useCursor(store: CursorStore): number | null {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
