# Design guide

The working reference for the web app: the pit wall and the dashboards. The
rules are in [ADR 0004](adr/0004-design-language.md). This page holds the
values, and a normal PR may change them. When the code and this page disagree,
fix one of them in the same PR.

The look is the brand's, from `brand.py`: **a 90s Japanese track-day shop.
Advan red on black, carbon grey panels, white type.** It is technical, quiet
and dense with numbers. Red is used sparingly, like a livery stripe, not as
paint.

## Colour

### Tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#111111` (brand deep black) | page background |
| `--surface` | `#1A1A1A` | cards, the header, sheets |
| `--surface-raised` | `#242424` | hover, pressed, the selected row, popovers |
| `--border` | `#333333` (brand carbon grey) | card edges, table rules, chart grid |
| `--border-strong` | `#4A4A4A` | inputs, chips |
| `--text` | `#FFFFFF` | primary text and numbers |
| `--text-muted` | `#A3A3A3` | secondary text: car, date, units, `/16` |
| `--text-subtle` | `#737373` | large text and icons only (see pairs) |
| `--accent` | `#D21F1B` (brand Advan red) | primary button, active nav bar, live dot, lap A, the header rule |
| `--accent-hover` | `#DA2A25` | primary button hover and pressed: lighter than `--accent`, so it keeps 3:1 on a dark surface |
| `--on-accent` | `#FFFFFF` | text on `--accent` |
| `--accent-text` | `#FF6B63` | red text: links, errors, the focus ring |
| `--timing-best` | `#C084FC` | the session's best lap |
| `--timing-improve` | `#4ADE80` | faster than the reference |
| `--timing-slower` | `#FBBF24` | slower than the reference |
| `--info` | `#60A5FA` | neutral notices (a deploy rolling out) |
| `--lap-a` | `var(--accent)` | compare: lap A |
| `--lap-b` | `var(--text)` | compare: lap B, dashed |

There are no shadows. Elevation is a lighter surface plus a border. Sheets and
dialogs get one shadow token, `--shadow-overlay` (`0 8px 32px` at 50% black),
over a 60% black scrim (`--scrim`).

The tokens live in `web/src/styles/tokens.css`, the brand's from
`web/src/styles/brand.css` (generated from `brand.py` by `make brand-css`).
Tailwind's own palette is cleared, so the utilities are the tokens:
`bg-bg`, `bg-surface`, `bg-surface-raised`, `border-border`,
`border-border-strong`, `text-fg` (for `--text`), `text-muted`, `text-subtle`,
`bg-accent`, `bg-accent-hover`, `text-on-accent`, `text-accent-text`,
`text-timing-best`, `text-timing-improve`, `text-timing-slower`, `text-info`,
`text-lap-a`, `text-lap-b` and `bg-scrim`.

### Allowed pairs

These ratios were measured with the WCAG 2 formula. The contrast test (#294
R3, `web/src/styles/contrast.test.ts`) checks this table against the tokens,
and each pair against its floor as `web/src/styles/pairs.json` lists it. A new
pair goes in both.

| Foreground | On `--bg` | On `--surface` | On `--surface-raised` | Allowed for |
|---|---|---|---|---|
| `--text` | 18.9 | 17.4 | 15.5 | anything |
| `--text-muted` | 7.5 | 6.9 | 6.2 | anything |
| `--text-subtle` | 4.0 | 3.7 | 3.3 | large text (≥ 24 px, or 19 px bold), icons, disabled |
| `--accent` | 3.6 | 3.3 | 2.9 | non-text on `--bg` and `--surface` (dots, bars, lines, borders); large text on `--bg` only |
| `--accent-hover` | 3.9 | 3.6 | 3.2 | the primary button's hover and pressed fill; never text |
| `--accent-text` | 6.8 | 6.2 | 5.6 | anything |
| `--timing-best` | 7.1 | 6.6 | 5.9 | anything; dashboards on `--bg` |
| `--timing-improve` | 10.8 | 10.0 | 8.9 | anything |
| `--timing-slower` | 11.3 | 10.4 | 9.3 | anything |
| `--info` | 7.4 | 6.8 | 6.1 | anything |
| `--on-accent` on `--accent` | | | | 5.3: button labels |
| `--on-accent` on `--accent-hover` | | | | 4.8: button labels on hover and press |

`--accent` is not allowed on `--surface-raised` (2.9). A hovered or selected
row that carries a red mark (the live dot, the active nav item's bar) shows its
state with a `--border-strong` edge, not the raised fill.

Dashboards need 7:1 for values: `--text`, `--text-muted` (on `--bg`),
`--timing-*` and `--info` on `--bg`.

## Type

- **Families** (self-hosted with `@fontsource`, Latin subset):
  - **Barlow**, weights 400, 500 and 600, for the UI;
  - **Barlow Semi Condensed**, weights 600 and 700, for big numbers and the
    hero.

  The fallback is `system-ui`.
- **Glyphs:** checked in #294 on `@fontsource` 5.3.0's Latin files. Both
  families have a `tnum` feature that sets every digit to one width in each
  weight used (Barlow 527, 533 and 538 units at 400, 500 and 600; Semi
  Condensed 507 and 521 at 600 and 700); their default figures are
  proportional. The Latin subset has the true minus (U+2212) and the em dash
  (U+2014). Playwright measures `1:11.111` and `1:00.000` at the same width
  with `.num` in each weight.
- **Numbers:** `font-variant-numeric: tabular-nums` always, through the
  components and the `.num` utility (`num-lg` and `num-xl` for the big ones).
- **Loading:** `font-display: swap`, and Barlow 400 preloaded. The wordmark
  (`web/src/assets/wordmark.svg`) and the icons are outlines, so no CJK font
  is loaded.

| Token | Size / line | Use |
|---|---|---|
| `text-meta` | 13 / 18 | captions, chart axes, `/16` |
| `text-sm` | 14 / 20 | table cells on a phone, chips |
| `text-base` | 16 / 24 | body, table cells |
| `text-lg` | 18 / 26 | card titles |
| `text-xl` | 20 / 28 | section headings |
| `text-2xl` | 24 / 30 | page titles |
| `num-lg` | 32 / 36, Semi Condensed 600 | stat tile values |
| `num-xl` | 56 / 56, Semi Condensed 700 | the session hero (P1, a best lap) |
| `dash-*` | by viewport height | dashboards (#240): the gear at least 40% of the height |

Headings are sentence case. Small caps are used for one thing: stat tile
labels (`text-meta`, 500, letter-spacing 0.04 em as `tracking-label`, upper
case).

## Space, size and shape

- **The grid is 4 px.** Tailwind's spacing scale is unchanged (1 = 4 px).
- **Gutters:** 16 px on a phone, 24 px from 640 px, 32 px from 1024 px.
- **Widths:** content is at most 72 rem wide. The session list's single column
  on a desktop is at most 48 rem.
- **Radii:** `--radius-sm` 2 px (badges), `--radius-md` 4 px (cards, buttons,
  inputs), `--radius-lg` 8 px (sheets and dialogs). The look is crisp, not
  pillowy.
- **Targets:** at least 44 × 44 px. Small badges get a padded hit area.
- **Shell breakpoints:** 640 px (sheet → popover) and 1024 px (tabs → side
  rail). Components use container queries instead.
- **The livery rule:** a 2 px `--accent` line under the header, and the 3 px
  `--accent` bar on the active nav item. These are the only decorative uses of
  red.

## Motion

| Token | Value |
|---|---|
| `--motion-fast` | 150 ms |
| `--motion-base` | 200 ms |
| `--ease-out` | `cubic-bezier(0.2, 0, 0, 1)` |
| `animate-fade-in` | opacity from 0, `--motion-fast`: popovers, overlays, dialogs |
| `animate-sheet-in` | up from below, `--motion-base`: the bottom sheet |
| `animate-pulse` | the live dot and skeletons, `motion-safe:` only |

- Motion is for state changes only: sheets, expanding rows, the live dot's
  pulse.
- Data never animates.
- Under `prefers-reduced-motion`, the durations are 0 and the pulse stops.

## Numbers

`web/src/lib/format.ts` is the only formatter. Its cases are shared with
Python in `tests/fixtures/format-cases.json`.

| What | Function | Examples |
|---|---|---|
| Lap time | `lapTime(ms)` | `1:27.764`, `49.677` |
| Race time | `raceTime(ms)` | `9:56.826`, `1:02:03.456` |
| Gap | `gap(ms)` | `+0.866`, `−0.312` (U+2212), `Best` |
| Position | `position(p, cars)` | `P3` + muted `/16`; hidden when not shown |
| Fuel level | `fuelPct(v)` | `43%` |
| Fuel per lap | `fuelPerLap(v)` | `3.2%` |
| Fuel in GT7's units | `fuelAmount(v)` | `18.7 units`: only when the session has no `fuel_capacity`; with one, fuel is a share of the tank |
| Speed | `speedKph(v)` | `287 km/h` |
| A chart's whole number (unit beside it) | `whole(v)` | `287`, `6,450` |
| Throttle, brake | `pedalPct(v)` | `44%` |
| Gear | `gear(v)` | `3`, `N` (0: neutral or reverse) |
| Time into a lap | `traceTime(s)` | `48.3`, `1:02.0` |
| Duration | `duration(ms)` | `9 min 57 s`, `1 h 04 min` |
| Session date | `sessionDate(t, now, tz)` | `Today 14:04`, `Yesterday 21:10`, `Sat 17 Oct 14:04`, `Fri 17 Oct 2025 14:04` |
| Missing | `missing()` | `—` (muted) |

Rules:
- A lap time is never rounded differently from the results card.
- Gaps always have a sign.
- "Fuel off" replaces fuel numbers when the session's fuel use is off
  (`fuelPct(v, { fuelUse: false })`).
- `position` returns two parts, `{ position: "P3", of: "/16" }`, so the field
  can be muted. Whether to show it is the API's `position_shown`.
- Fuel percentages round half to even, as Python's `round()` does on the card.
- Fuel is a share of the tank (`100 × amount / fuel_capacity`) when the session
  has a `fuel_capacity`. GT7 sends a level and a capacity, never litres: in all
  25 recordings in `tests/fixtures/` (16 cars) the capacity is 100 while
  driving, so one of GT7's units has been 1% of a tank. With no capacity the
  page shows the raw amount, labelled "units" (#298).
- The cases in `tests/fixtures/format-cases.json` are the definition: Vitest
  checks them all, and pytest checks those with a Python formatter
  (`results.race_time`).
- An unknown number is `—`. It is never 0, `None` or blank.

## Components

The kit is in `web/src/components/`, shown at `/_kit` (#295,
`web/src/routes/kit.tsx`): open it on the pit wall, or on the phone and iPad
through `make web-preview`. Use it before writing anything new. A new pattern goes into the
kit first, with all its states, and `/_kit` shows it. `/_kit` is in every build
but linked from nowhere. Its sample data is `web/src/kit/samples.ts`, typed as
the API's generated types, with real names from the engineer's store. CI screenshots
it at the three widths and runs axe over it (`web/e2e/kit.spec.ts`).

| Component | File | States |
|---|---|---|
| `LapTime` | `lap-time.tsx` | normal, best (`--timing-best`, and "best lap" for a screen reader), invalid (`—`, "No lap time"), sizes sm, md and xl, loading |
| `Gap` | `gap.tsx` | faster (`--timing-improve`), slower (`--timing-slower`), best (`Best`, `--timing-best`), even (`+0.000`), unknown, loading; the sign always shown |
| `Position` | `position.tsx` | `P3/16`, `P1/1`, xl (the hero), hidden (`position_shown` false), unknown, loading; read as "Position 3 of 16" |
| `KindBadge` | `kind-badge.tsx` | the API's `kind_label`; muted for an unknown kind |
| `LapFlag` | `lap-flag.tsx` | Pit, Out, Partial, Restart, each with its explanation in a popover, by tap, click, Enter or Space; Escape closes it |
| `StatTile` | `stat-tile.tsx` | value, best (`--timing-best`), `—`, with a sub-line, loading |
| `SessionCard` | `session-card.tsx` | race finished, retired, timed, time trial, unknown track (and unknown car), live, paused, loading; stacked below 28 rem of its own width, a row above |
| `LiveBadge` | `live-badge.tsx` | live (the red dot, pulsing unless motion is reduced), paused (a still, hollow dot) |
| `EmptyState` | `empty-state.tsx` | title, why, an optional action |
| `ErrorState` | `error-state.tsx` | what failed, what to do, the detail behind a disclosure, Retry and Retrying |
| `Unknown` | `unknown.tsx` | "Unknown track" or "Unknown car", muted, with the reason in a popover on tap; muted text alone when there is no reason |
| `UPlot` (charts) | `web/src/charts/UPlot.tsx` | one wrapper for every chart (see [Charts](#charts)). Tokens: axes `--text-muted`, grid `--border`, lap A `--lap-a`, lap B `--lap-b` dashed |

How they are built:

- **Numbers** go through `format.ts` inside the component; a page passes the
  API's values. Every number is `whitespace-nowrap`, so a figure never breaks.
- **Loading:** each data component has a `…Skeleton` (`LapTimeSkeleton`,
  `GapSkeleton`, `PositionSkeleton`, `StatTileSkeleton`, `SessionCardSkeleton`)
  in its own shape: a number's skeleton is a sample figure ("0:00.000") set in
  the same type, so the value lands on it. `Loading` (`loading.tsx`) keeps the
  space from the start and shows the skeleton after 150 ms.
- **Missing:** `Missing` (`missing.tsx`) is the muted `—` with words for a
  screen reader ("No lap time", "Position unknown").
- **Explanations** (`LapFlag`, `Unknown`) are `Explain` (`explain.tsx`): a
  44 × 44 px button that opens a Popover. A tooltip never carries anything a
  reader needs, because it never opens on tap; the kit uses one only to repeat
  an icon button's accessible name.
- **SessionCard** works from `Session`'s values. It writes "Finished P1/16 in
  9:56.826" and a live "Lap 5 of 12, running P3/16" itself, and takes the
  ending Python words (retired, paused, stopped, "no full lap") from
  `Session.result`, in sentence case (ADR 0004 point 6). The whole card is its
  title's link, through a stretched `::after`; an `Unknown` button sits above
  it. The title wraps to two lines and then ends in an ellipsis, with the full
  name in its `title` and accessible name. Hovered, it gains a
  `--border-strong` edge, not the raised fill, because it may carry the live
  dot. Keyboard focus rings the whole card.
- **Targets:** buttons, toggles, select triggers and items, the explanation
  buttons and the disclosure are at least 44 × 44 px (`min-h-11`). A badge with
  an explanation keeps its small look inside the bigger button.
- **Focus:** one ring for everything, set in `styles/index.css`: 2 px
  `--accent-text`, offset 2 px, on `:focus-visible`.

shadcn/ui primitives sit in `web/src/components/ui/`: Button, Badge, Card,
Sheet, Popover, Select, Toggle, Tooltip, Table, Skeleton, Separator and Dialog,
from the `new-york-v4` registry, restyled only through tokens. Note here any
change from upstream:

- Two of shadcn's colour names mean something else here, and ours win:
  `accent` is Advan red, not shadcn's subtle hover fill, and `muted` is muted
  text, not a muted surface. After `shadcn add`, change `bg-accent` and
  `bg-muted` (and their `hover:` forms) to `bg-surface-raised`, and
  `text-destructive` to `text-accent-text`. The other names
  (`background`, `primary`, `card`, `popover`, `secondary`,
  `muted-foreground`, `destructive`, `input`, `ring`) map onto ours as they
  are.
- **Everywhere:** no `tw-animate-css`. Upstream's `animate-in`, `fade-in-0`,
  `zoom-in-95` and `slide-in-from-*` are replaced by two token animations,
  `animate-fade-in` (`--motion-fast`) and `animate-sheet-in` (`--motion-base`),
  and there are no exit animations. No `shadow-*` but `shadow-overlay`, no
  `ring-[3px]` focus rings (the global focus ring instead), no `dark:`
  variants, and no arbitrary values (the lint rule): `top-[50%]`,
  `min-w-[8rem]`, `w-[var(--x)]` and the like become `top-1/2`, `min-w-32` and
  `w-(--x)`. `text-xs` (12 px) becomes `text-meta` (13 px). Icons are
  `aria-hidden`.
- `Button`: `min-h-11 min-w-11`; variants `default` (`bg-primary`,
  `hover:bg-accent-hover`), `outline` (`border-input`), `ghost` and `link`
  (`text-accent-text`); sizes `default` and `icon` (`size-11`). Upstream's
  `destructive`, `secondary`, `sm` and `lg` are left out until a page needs
  them.
- `Badge`: `rounded-sm` (2 px), not `rounded-full`; `text-meta`; variants
  `default`, `outline` (`border-border-strong`) and `muted` (`text-muted`).
  Upstream's `secondary`, `destructive`, `ghost` and `link` are left out.
- `Card`: `rounded-md`, no shadow, 16 px padding and gap (upstream 24); only
  `CardHeader`, `CardTitle`, `CardDescription`, `CardContent` and
  `CardFooter`.
- `Sheet`: `side` is `bottom` (the default, a bottom sheet) or `right`;
  `bg-surface`, `rounded-t-lg`, `shadow-overlay`, over `bg-scrim`; a 44 px close
  button always.
- `Dialog`: centred with `inset-x-4` and `max-w-lg` in place of upstream's
  calc; `bg-surface`, `rounded-lg`, `shadow-overlay`, over `bg-scrim`; a 44 px
  close button always; `DialogFooter` has no built-in close.
- `Popover`: `bg-popover` (`--surface-raised`) with a `--border-strong` edge
  and no shadow; `collisionPadding` 16; no `PopoverAnchor`, header, title or
  description parts (`Explain` composes its own).
- `Select`: trigger and items `min-h-11`; the trigger has no `size`; the
  content is `position="popper"` by default; the focused item is
  `bg-surface-raised` with a `--border-strong` edge (upstream `bg-accent`).
- `Toggle`: `min-h-11 min-w-11`; off is `text-muted`, on is
  `bg-surface-raised`, `text-fg` and a `--border-strong` edge (upstream
  `bg-accent`); no `size`.
- `Tooltip`: `bg-popover` with a `--border-strong` edge, `text-meta`, no arrow
  (upstream's arrow needs an arbitrary translate); each `Tooltip` brings its
  own provider, with a 300 ms delay.
- `Table`: tabular figures; header cells `text-meta` and `text-muted`; rows
  and cells `h-11`; no `TableFooter`; no hover fill; a selected row
  (`data-state=selected`) is `bg-surface-raised`, or, with `data-marked`, a
  `--border-strong` outline on the plain surface.
- `Skeleton`: `bg-surface-raised` (upstream `bg-accent`), `rounded-sm`, and
  `motion-safe:animate-pulse`.
- `Separator`: unchanged.

## Charts

Every chart is uPlot (ADR 0003 point 2) through one wrapper,
`web/src/charts/UPlot.tsx` (#299 R7). Lap compare uses it first; the session
page's charts (#300), the track map and delta (#117) and corners (#34) reuse
it rather than writing their own. uPlot is about 20 KB gzipped: import the
wrapper only from a lazy route, never from the entry.

```tsx
<UPlot
  options={options}   // (theme: ChartTheme) => uPlot options without width/height; memoise it
  data={data}         // uPlot's AlignedData: [xs ascending, ...series]
  height={140}        // CSS px; the width is the container's
  xRange={zoom}       // [min, max] shown, or null for all of the data
  onXRange={setZoom}  // a drag, a pinch, or null for a double click or tap
  minSpan={1}         // the narrowest range a pinch reaches, in x units
  onCreate={(u) => cleanup}  // the plot, for hooks the options can't reach
  label="Speed, lap 5 solid against lap 6 dashed"  // the chart's accessible name
/>
```

- **Lifecycle.** The plot is made in an effect, and again only when `options`
  changes. New `data` is `setData`, a new width (a ResizeObserver) or `height`
  is `setSize`, and unmount is `destroy`. A render never rebuilds a plot.
- **Theme.** `options` is called with a `ChartTheme` read from the tokens when
  the plot is made (`web/src/charts/theme.ts`): `axis` (`--text-muted`), `grid`
  (`--border`), `lapA` (`--lap-a`), `lapB` (`--lap-b`), `text` (`--text`),
  `best` (`--timing-best`), `background` (`--bg`, the inside of a hollow mark)
  and `font` (`text-meta` in the UI family). `themedAxis(theme, axis)` gives an axis in it, and lap B
  takes `LAP_B_DASH`, so the laps never differ by colour alone. A canvas can't
  take a CSS variable; nothing in `src/charts/` has a colour of its own.
- **Zoom.** The x range is controlled: charts that share a range share the
  state behind `xRange`. A mouse drag selects a range (uPlot never sets its own
  scale), two fingers pinch it, and a double click or double tap asks for null.
  Without `onXRange` the chart doesn't zoom. The element carries the range shown
  as `data-x-range`.
- **Cursor and touch.** Charts that share `cursor.sync.key` (uPlot.sync) share
  one cursor. A finger moving sideways scrubs it (`web/src/charts/gestures.ts`),
  publishing to the group as a mouse move does; a finger moving up or down is
  the page scrolling (`touch-action: pan-y` on the plot), so a chart never traps
  the scroll. uPlot's own legend and tooltip are off: a value the reader needs
  goes in a readout outside the chart, never under the finger.
- **Style.** `web/src/styles/charts.css` follows uPlot's stylesheet: the cursor
  a `--text-muted` hairline, the drag selection a faint veil with
  `--border-strong` edges. Both ship in the chunks that draw charts.
- **Lap compare** (`web/src/routes/compare.tsx`, `web/src/compare/`): one chart
  per channel, about 140 px tall on a phone and 180 px from 600 px of width,
  all with the same 52 px y axis and padding so their plots line up; the x axis's
  labels on the last only. A sticky readout under the header (`top-header`)
  shows the cursor's time and each lap's value at its own nearest sample. Traces
  are asked for at one point per device pixel of the chart's width, at most
  1,500, in steps of 100.
- **Race story** (#300, `web/src/session/race-story.tsx`, its figures in
  `web/src/session/story.ts`): on the session page between the stat tiles and
  the laps table, only with three complete laps or more (no chart and no empty
  box below that, and its chunk, with uPlot, isn't loaded). One point per
  complete lap on the lap-time axis (left), joined by a `--text` line; the best
  lap larger in `--timing-best`; pit and out laps hollow. The y range is the
  other laps' spread plus a tenth of it either side (at least 0.1 s), so a stop
  doesn't flatten the racing laps; a lap past it is a hollow triangle at that
  edge, pointing out. Position, when `position_shown`, is a dashed, stepped
  `--text-muted` line on the right axis, P1 at the top. 150 px tall on a phone,
  180 px from 600 px of width. A hover, a tap or a table row highlights a lap
  both ways (a hairline on the chart, the raised fill on the row) and the
  readout above the chart names it, with its Pit or Out flag; a tap or click
  also picks it for compare, as its checkbox does. Its accessible name is the
  summary: "12 laps, best 1:27.764 on lap 7, P6 to P2".

## The shell

The frame every page sits in (#296), in `web/src/app/`:

- **Header** (`header.tsx`): sticky, `--surface`, 56 px with the 2 px
  `--accent` line, padded below the notch (`pt-safe`). The wordmark links home;
  the page's title shows from 640 px; the live chip sits on the right.
- **Live chip** (`engine-chip.tsx`, `live-chip.tsx`): a 44 px chip with a
  `--border-strong` edge. "Live · <track> · L<lap>" with the pulsing red dot,
  "Paused · <track>" with the hollow dot, "Replay", "Demo", "Idle" or "In the
  menus", and "Engineer offline" in `--text-muted`, never an error colour. The
  track is named only when the detector is sure; otherwise "Unknown track",
  muted. A version mismatch adds a small `--info` dot, and the popover says
  "Engineer 0.7.0, pit wall 0.7.1: a deploy is rolling out". The popover is
  `--surface-raised`, so nothing in it is red. `/_kit` shows every state.
- **Navigation** (`nav.tsx`, `sections.ts`): nothing until there are two
  sections. Then a bottom tab bar (64 px with its top border, plus the home
  indicator's inset) below 1024 px, and a 96 px side rail from 1024 px. The
  active item has the 3 px `--accent` bar (top edge in the tab bar, left edge
  in the rail) and white text; the others are muted. `/_kit` shows it with two
  sample sections.
- **Gutters and safe areas:** `px-gutter` is `--gutter` (16, 24, 32 px) or the
  side's safe-area inset, whichever is larger; `pt-safe`, `pb-safe`,
  `pb-page` and `pb-tab-bar` keep clear of the notch and the home indicator
  (`viewport-fit=cover` in `index.html`).
- **Titles:** each page calls `usePageTitle("<page>")`, giving
  "<page> · Pit wall" in the tab and the header.
- **Errors:** a page that throws shows `ErrorState` in place of the page, with
  the shell working around it; a route chunk gone after a deploy offers
  "Reload to get the new version". An unknown path is "Nothing here" with a
  link home.
- **Back:** `<ScrollRestoration />`, and `BackLink` ("All sessions"), which is
  the browser's Back when the page was opened from the list
  (`state={{ back: true }}`).

## The session list

`/` (#297), in `web/src/routes/sessions.tsx`, its logic in
`web/src/lib/session-list.ts`:

- **Days:** sessions grouped under "Today", "Yesterday", "Sat 17 Oct" in the
  viewer's zone (`sessionDay`), newest first, each heading with its count.
  `SessionCard`s, one column on a phone, two from 768 px, and one row-shaped
  column at most 48 rem (`max-w-list`) from 1280 px.
- **Live:** the engineer's open session is pinned above the days under "On
  track", with the engineer's lap and position. The list asks again every 5 s
  while it is live, and on focus otherwise.
- **Short sessions:** no full lap, hidden by default; each day ends with "3
  sessions with no full lap · Show". `?all=1` and the "No full lap" toggle show
  them.
- **Filters:** Track, Car, Kind and Date chips open a bottom sheet below 640 px
  and a popover from it, each option with its count; active filters are
  removable chips with "Clear all", and "12 of 70 sessions" sums up. All of it
  is in the URL (`track`, `car`, `kind`, `from`, `to`, `all`); the API filters
  (#318), with the browser's zone sent as `tz` and kept out of the URL.
- **Paging:** 25 cards, "Show more" adds 25; how many are shown is kept in the
  history entry, so Back returns to the same cards and scroll.

## States

Every data view designs these five (ADR 0004 point 9):

| State | Design |
|---|---|
| Loading | skeletons shaped like the content, after 150 ms |
| Empty | what is missing and what to do |
| Error | what failed, the detail, Retry; the shell keeps working |
| Unknown | muted, with the reason on tap |
| Live | refresh every 5 s while live, with nothing moving under the reader |

## Information architecture

What the app will hold, and when each part arrives. Sections appear in the nav
only once they exist (ADR 0004 point 7).

| Section | Routes | Release |
|---|---|---|
| Sessions | `/`, `/sessions/:id`, `/sessions/:id/compare` | 0.7.2, 0.7.3 |
| Sessions, more | track map and delta (#117), corners (#34), the debrief (#102) | 0.18, 0.21 |
| Live | `/dash/:layout` (#240), the live session | 0.11 |
| Progress | personal bests (#103), goals (#104), growth (#118), export (#36) | 0.22, 0.23 |
| Setup | PlayStation (#138), Discord (#139), engineer settings (#135) | 0.15, 0.16 |
| Kit | `/_kit` (not in the nav) | 0.7.1 |
| Old card links | `/?session=:id` redirects to `/sessions/:id`, so every results card posted since #116 still opens its session | 0.7.0 |

The primary journey: a results card in Discord, then the session page, then
compare. It is designed for a phone in portrait first.

## Writing

- Sentence case and British English. Write "lap", "stint", "box", "pit" and
  "out lap", as the engineer says them.
- No exclamation marks, and no "Oops".
- Errors say what happened, then what to do: "Couldn't read the session store.
  Retry, or check the engineer's logs."
- Empty states say why, and the next step.
