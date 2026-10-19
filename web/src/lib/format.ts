// The only place a number becomes text (ADR 0004 point 5, docs/design.md, Numbers).
// Its cases are tests/fixtures/format-cases.json, which pytest checks against the
// Python formatters too (results.race_time), so the results card and the page never
// show the same lap differently.
//
// Every function takes what the API sends, null and undefined included, and never
// returns "null", "NaN" or "undefined": an unknown value is missing() ("—").

type Num = number | null | undefined;

/** The true minus sign, U+2212: a hyphen is too short beside tabular figures. */
const MINUS = "−";
const MISSING = "—";

/** "—", for a value that is unknown. Never 0, blank or "None". */
export function missing(): string {
  return MISSING;
}

function known(v: Num): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function pad(n: number, width = 2): string {
  return String(n).padStart(width, "0");
}

/** Python's round(): halves to even, so a figure the card also writes rounds the same. */
function roundHalfEven(v: number, digits = 0): number {
  const scale = 10 ** digits;
  const x = v * scale;
  const r = Math.round(x);
  return (Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r) / scale;
}

/** results.race_time, line for line: whole milliseconds, truncated. */
function clock(ms: number): string {
  const whole = Math.trunc(ms);
  const millis = whole % 1000;
  let seconds = Math.trunc(whole / 1000);
  let minutes = Math.trunc(seconds / 60);
  seconds %= 60;
  const hours = Math.trunc(minutes / 60);
  minutes %= 60;
  if (hours) {
    return `${hours}:${pad(minutes)}:${pad(seconds)}.${pad(millis, 3)}`;
  }
  if (!minutes) {
    return `${seconds}.${pad(millis, 3)}`;
  }
  return `${minutes}:${pad(seconds)}.${pad(millis, 3)}`;
}

/** A lap time: `1:27.764`, `49.677`. No time (null, 0 or less) is missing. */
export function lapTime(ms: Num): string {
  return known(ms) && ms > 0 ? clock(ms) : MISSING;
}

/** A race time: `9:56.826`, `1:02:03.456`. */
export function raceTime(ms: Num): string {
  return known(ms) && ms > 0 ? clock(ms) : MISSING;
}

/** A gap, always signed: `+0.866`, `−0.312`, `+0.000`; "Best" for the best lap itself. */
export function gap(ms: Num, opts?: { best?: boolean } | null): string {
  if (opts?.best) {
    return "Best";
  }
  if (!known(ms)) {
    return MISSING;
  }
  const whole = Math.trunc(ms);
  return `${whole < 0 ? MINUS : "+"}${clock(Math.abs(whole))}`;
}

/** A position in two parts, so the field can be muted: `P3` and `/16`. An unknown
 * position is missing; an unknown field size is an empty `of`. Whether a position is
 * shown at all is the API's `position_shown`, not this. */
export function position(p: Num, cars?: Num): { position: string; of: string } {
  if (!known(p) || p < 1) {
    return { position: MISSING, of: "" };
  }
  return { position: `P${Math.trunc(p)}`, of: known(cars) && cars >= 1 ? `/${Math.trunc(cars)}` : "" };
}

/** Fuel use off: the fuel figures mean nothing, so none is shown. */
const FUEL_OFF = "Fuel off";

/** Fuel left, as a share of the tank in per cent: `43%`. Rounded as the card rounds. */
export function fuelPct(v: Num, opts?: { fuelUse?: boolean | null } | null): string {
  if (opts?.fuelUse === false) {
    return FUEL_OFF;
  }
  return known(v) && v >= 0 ? `${roundHalfEven(v)}%` : MISSING;
}

/** Fuel used per lap, in per cent of the tank: `3.2%`. A refuelled lap (below 0) is missing. */
export function fuelPerLap(v: Num, opts?: { fuelUse?: boolean | null } | null): string {
  if (opts?.fuelUse === false) {
    return FUEL_OFF;
  }
  return known(v) && v >= 0 ? `${roundHalfEven(v, 1).toFixed(1)}%` : MISSING;
}

/** An amount of fuel in GT7's own units, for when the tank's size is unknown:
 * `18.7 units`. GT7 sends a level and a capacity, not litres; in every recording
 * so far the capacity is 100, so a unit has been 1% of a full tank, but GT7
 * doesn't promise it (#298). Below 0 (a refuel) is missing. */
export function fuelAmount(v: Num, opts?: { fuelUse?: boolean | null } | null): string {
  if (opts?.fuelUse === false) {
    return FUEL_OFF;
  }
  return known(v) && v >= 0 ? `${roundHalfEven(v, 1).toFixed(1)} units` : MISSING;
}

/** A speed: `287 km/h`. */
export function speedKph(v: Num): string {
  return known(v) && v >= 0 ? `${Math.round(v)} km/h` : MISSING;
}

/** A whole number on a chart or its readout, with the unit beside it: `287`, `6,450`. */
export function whole(v: Num): string {
  if (!known(v)) {
    return MISSING;
  }
  const n = Math.round(v);
  const text = Math.abs(n).toLocaleString("en-GB");
  return n < 0 ? `${MINUS}${text}` : text;
}

/** A pedal, 0 to 100: `44%`. */
export function pedalPct(v: Num): string {
  return known(v) && v >= 0 ? `${Math.round(v)}%` : MISSING;
}

/** A gear: `3`, and `N` for GT7's 0 (neutral, or reverse). */
export function gear(v: Num): string {
  if (!known(v) || v < 0) {
    return MISSING;
  }
  return v === 0 ? "N" : String(Math.round(v));
}

/** A moment in a lap, from its start, to the tenth of a second: `48.3`, `1:02.0`. */
export function traceTime(s: Num): string {
  if (!known(s) || s < 0) {
    return MISSING;
  }
  const tenths = Math.round(s * 10);
  const minutes = Math.trunc(tenths / 600);
  const rest = tenths - minutes * 600;
  const secs = `${Math.trunc(rest / 10)}.${rest % 10}`;
  return minutes ? `${minutes}:${secs.padStart(4, "0")}` : secs;
}

/** A duration, to the second under an hour and to the minute from one:
 * `42 s`, `9 min 57 s`, `1 h 04 min`. */
export function duration(ms: Num): string {
  if (!known(ms) || ms < 0) {
    return MISSING;
  }
  const s = Math.round(ms / 1000);
  if (s < 60) {
    return `${s} s`;
  }
  if (s < 3600) {
    return `${Math.trunc(s / 60)} min ${pad(s % 60)} s`;
  }
  const minutes = Math.round(s / 60);
  return `${Math.trunc(minutes / 60)} h ${pad(minutes % 60)} min`;
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface Civil {
  y: number;
  m: number;
  d: number;
  hh: number;
  mm: number;
}

/** The calendar date and wall-clock time of a Unix time in a time zone. */
function civil(epochS: number, tz: string | undefined): Civil {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    hourCycle: "h23",
  }).formatToParts(new Date(epochS * 1000));
  const part = (type: string) => Number(parts.find((x) => x.type === type)?.value);
  return { y: part("year"), m: part("month"), d: part("day"), hh: part("hour"), mm: part("minute") };
}

/** Days since 1970-01-01 of a calendar date: whole days between two dates, DST or not. */
function dayNumber(c: Civil): number {
  return Math.round(Date.UTC(c.y, c.m - 1, c.d) / 86_400_000);
}

/** When a session started, in the viewer's time zone: `Today 14:04`, `Yesterday 21:10`,
 * `Sat 17 Oct 14:04`, and the year when it isn't this one: `Fri 17 Oct 2025 14:04`.
 * `epoch` and `now` are Unix times in seconds, as the API sends them. */
export function sessionDate(epoch: Num, now: number = Date.now() / 1000, tz?: string): string {
  if (!known(epoch) || epoch <= 0) {
    return MISSING;
  }
  const at = civil(epoch, tz);
  return `${dayName(at, civil(now, tz))} ${pad(at.hh)}:${pad(at.mm)}`;
}

/** "Today", "Yesterday", "Sat 17 Oct", "Fri 17 Oct 2025": the day `at` is, seen from `today`. */
function dayName(at: Civil, today: Civil): string {
  const days = dayNumber(today) - dayNumber(at);
  if (days === 0) {
    return "Today";
  }
  if (days === 1) {
    return "Yesterday";
  }
  const weekday = DAYS[new Date(Date.UTC(at.y, at.m - 1, at.d)).getUTCDay()];
  const year = at.y === today.y ? "" : ` ${at.y}`;
  return `${weekday} ${at.d} ${MONTHS[at.m - 1]}${year}`;
}

/** The day a session started, as the session list heads it, in the viewer's time
 * zone: `Today`, `Yesterday`, `Sat 17 Oct`, `Fri 17 Oct 2025` (#297 R1). */
export function sessionDay(epoch: Num, now: number = Date.now() / 1000, tz?: string): string {
  if (!known(epoch) || epoch <= 0) {
    return MISSING;
  }
  return dayName(civil(epoch, tz), civil(now, tz));
}

/** The calendar date of a Unix time in a time zone, as the API's `from` and `to`
 * take it: `2026-10-17`. Unknown is missing. */
export function isoDay(epoch: Num, tz?: string): string {
  if (!known(epoch) || epoch <= 0) {
    return MISSING;
  }
  const at = civil(epoch, tz);
  return `${at.y}-${pad(at.m)}-${pad(at.d)}`;
}

/** A `YYYY-MM-DD` day as a filter chip says it: `17 Oct`, or `17 Oct 2025` when it
 * isn't in `thisYear`. Anything else is missing. */
export function shortDay(iso: string, thisYear?: number): string {
  const m = typeof iso === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
  if (!m) {
    return MISSING;
  }
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  return `${d} ${MONTHS[mo - 1]}${thisYear === undefined || thisYear === y ? "" : ` ${y}`}`;
}
