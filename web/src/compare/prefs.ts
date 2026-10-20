// Lap compare's per-viewer preferences in localStorage (#299 R6, R10; ADR 0004
// point 7): the hidden channels, the track map's colours, and whether the "turn
// sideways" hint has been shown. Storage can be missing, full or blocked (a private window), so every
// read and write is guarded, and the page works without it.
import { CHANNEL_IDS, type ChannelId } from "./channels";
import { MAP_MODES, type MapMode } from "./map";

export const HIDDEN_CHANNELS_KEY = "twr.compare.hidden-channels";
export const MAP_MODE_KEY = "twr.compare.map-mode";
export const SIDEWAYS_HINT_KEY = "twr.compare.sideways-hint-shown";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function read(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    storage()?.setItem(key, value);
  } catch {
    // Not remembered, then: the page carries on.
  }
}

/** The channels this viewer hid; none when nothing (or nothing readable) is stored. */
export function readHiddenChannels(): ChannelId[] {
  try {
    const parsed: unknown = JSON.parse(read(HIDDEN_CHANNELS_KEY) ?? "[]");
    return Array.isArray(parsed) ? CHANNEL_IDS.filter((id) => parsed.includes(id)) : [];
  } catch {
    return [];
  }
}

export function writeHiddenChannels(hidden: readonly ChannelId[]): void {
  write(HIDDEN_CHANNELS_KEY, JSON.stringify(hidden));
}

/** The track map's colours (#350 R2): pedals unless this viewer picked speed. */
export function readMapMode(): MapMode {
  const stored = read(MAP_MODE_KEY);
  return MAP_MODES.find((m) => m === stored) ?? "pedals";
}

export function writeMapMode(mode: MapMode): void {
  write(MAP_MODE_KEY, mode);
}

/** True the first time it is asked on this browser, then false. */
export function takeSidewaysHint(): boolean {
  if (read(SIDEWAYS_HINT_KEY) !== null) {
    return false;
  }
  write(SIDEWAYS_HINT_KEY, "1");
  return true;
}
