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
labels (`text-meta`, 500, letter-spacing 0.04 em, upper case).

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
| Speed | `speedKph(v)` | `287 km/h` |
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
- The cases in `tests/fixtures/format-cases.json` are the definition: Vitest
  checks them all, and pytest checks those with a Python formatter
  (`results.race_time`).
- An unknown number is `—`. It is never 0, `None` or blank.

## Components

The kit is in `web/src/components/`, shown at `/_kit` (#295). Use it before
writing anything new. A new pattern goes into the kit first.

| Component | States |
|---|---|
| `LapTime` | normal, best (`--timing-best`), invalid (`—`), sizes sm, md and xl |
| `Gap` | faster, slower, best; the sign always shown |
| `Position` | `P3/16`, `P1/1`, hidden |
| `KindBadge` | the API's `kind_label` |
| `LapFlag` | Pit, Out, Partial, Restart, each with a tap and keyboard explanation |
| `StatTile` | value, `—`, with a sub-line, loading |
| `SessionCard` | race finished, retired, timed, time trial, unknown track, live; stacked or row by container width |
| `LiveBadge` | live, paused |
| `EmptyState` | title, why, an action |
| `ErrorState` | message, detail disclosure, Retry |
| `Unknown` | "Unknown track", with the reason on tap |
| `UPlot` (charts) | one wrapper for every chart (#299). Tokens: axes `--text-muted`, grid `--border`, lap A `--lap-a`, lap B `--lap-b` dashed |

shadcn/ui primitives sit in `web/src/components/ui/`, restyled only through
tokens. Note here any change from upstream:

- Two of shadcn's colour names mean something else here, and ours win:
  `accent` is Advan red, not shadcn's subtle hover fill, and `muted` is muted
  text, not a muted surface. After `shadcn add`, change `bg-accent` and
  `bg-muted` (and their `hover:` forms) to `bg-surface-raised`, and
  `text-destructive` to `text-accent-text`. The other names
  (`background`, `primary`, `card`, `popover`, `secondary`,
  `muted-foreground`, `destructive`, `input`, `ring`) map onto ours as they
  are.
- `Button`: tokens only (`bg-primary`, `hover:bg-accent-hover`, a
  `border-input` outline, `text-accent-text` links); #295 designs the rest.

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
