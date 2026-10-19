# 0004: Design language for the web app

**Status:** Accepted, 2026-10-18. Asked for by #291. Builds on
[0003](0003-ui-stack.md), which picks the stack; this record decides how the
app looks and behaves. The values (colours, sizes, formats) live in
[`docs/design.md`](../design.md) and can change in a normal PR. The rules here
need a new record to change.

## Context

ADR 0003 makes the pit wall and the dashboards a React app styled with
Tailwind and shadcn/ui. It says nothing about the look, or about how pages
behave. 0.7 builds the first ten UI issues (#236 to #238, #292 to #300). The
first pages would set those things by accident, and every later page would copy
them.

What there is to build on:

- **A brand.** `brand.py` describes it: "a 90s Japanese track-day shop: Advan
  red on black, carbon grey for secondary panels, white type". It sets
  `ADVAN_RED #D21F1B`, `DEEP_BLACK #111111`, `CARBON_GREY #333333`, `WHITE`
  and the kanji 走り屋. The Discord results cards and the Streamlit page use it.
- **The brand's contrast.** Advan red on deep black is 3.55:1. That passes for
  large text and UI parts (3:1), but fails body text (4.5:1). White on Advan
  red is 5.31:1.
- **The data is noisy.** On 2026-10-18 the NUC held 70 sessions:
  - 18 with no full lap;
  - 21 on "Unknown track";
  - 23 of unknown kind;
  - 25 from that one day.

  The median session had 1.5 laps.
- **The data API was going to send strings.** `SessionRow` carries the card's
  strings ("🚩 Finished P1 of 16 in 9:56.826"), while the index and
  `summary.json` hold the values.
- **How the app is used.** On a phone, straight after a race, from a results
  card's link (#116). On an iPad on the sofa, and on a desktop. Dashboards on a
  phone or tablet by the wheel (#240).
- **HTTPS is live** (#252), so the web manifest, the wake lock and the
  clipboard all work.

## Decision

### 1. Tokens are the only source of style

- Every colour, size, radius, shadow and duration in the app is a design
  token: a CSS variable that Tailwind's theme maps to utilities.
- Components use tokens, never literals. A lint check in `make web-check`
  fails on a colour literal or an arbitrary Tailwind value outside
  `web/src/styles/`.
- The brand colours are generated from `brand.py` into
  `web/src/styles/brand.css`, so the cards and the app can't drift. `make
  check` fails when the generated file is stale.
- shadcn/ui's variables map onto ours, so its components take the brand with
  no edits.

Settles: #294 R1, R2.

### 2. Dark first, and dark only for now

- The app ships one theme, dark: the brand is black, and the pit wall is read
  in a dim room after a VR session.
- Tokens are semantic (`surface`, `text-muted`, `timing-best`), not
  descriptive (`grey-800`). A light theme is a second set of values, not a
  rewrite. It needs an issue, not a new record.
- The dashboards stay dark always.

Settles: #237 R10 (removed), #294 R8.

### 3. Colour carries meaning

| Role | Used for | Never used for |
|---|---|---|
| **Brand accent** (Advan red) | identity, the primary action, the active nav item, lap A in compare, the live dot | "bad", "slower" or decoration |
| **Accent text** (a lighter red) | red text, links and errors on dark surfaces | |
| **Timing** | purple for the session best, green for an improvement, amber for slower | anything but timing |
| **Neutrals** | surfaces from deep black up through carbon grey; text in white and muted greys | |

- These are the conventions of motorsport timing screens, so a lap time's
  colour means what a driver expects.
- **Colour is never alone.** A gap has its sign, a flag has its word, and lap
  B in compare is dashed as well as white.
- **Contrast floors:**
  - 4.5:1 for text;
  - 3:1 for large text (24 px, or 19 px bold) and UI parts;
  - 7:1 for dashboard values.

  A test checks every pair `docs/design.md` allows, and Advan red is allowed
  only where 3:1 is enough.

Settles: #294 R3, #295 R2, #299 R3, #240 R7.

### 4. Type: self-hosted, with tabular figures

- **Fonts are served by the pit wall.** There is no font CDN: the app works
  with the internet down, and the browser asks nothing of anyone else.
- **The UI family has tabular figures**, and every number uses them, so lap
  times line up and live values don't jitter. The starting choice is Barlow,
  with Barlow Semi Condensed for big numbers (SIL OFL). If the kit finds its
  tabular figures wanting, #294 swaps it, and the guide records the change.
- **The kanji wordmark is an SVG**, so no CJK font is loaded.
- **Sizes:** body text is at least 16 px on a phone, and no text is below 13 px.

Settles: #294 R4, R5.

### 5. One formatter, shared with Python

- Numbers become text only through `web/src/lib/format.ts`. It writes:
  - lap and race times;
  - gaps, with a true minus sign;
  - positions;
  - fuel, speed, durations and dates;
  - "—" for a missing value.
- Its cases are a fixture file, `tests/fixtures/format-cases.json`, that both
  pytest (against `results.race_time`, and any other Python formatter that
  has a case) and Vitest check. The results card and the page never show the
  same lap differently.
- The page never shows `null`, `NaN`, `undefined`, `None` or a bare 0 standing
  in for "unknown".

Settles: #294 R6, R7.

### 6. The API gives values; names Python owns stay in Python

- The data API returns values (`final_position`, `total_cars`,
  `best_lap_ms`, `finished`…), and the browser formats them (point 5). The UI
  never parses "P4 of 18".
- Labels whose logic lives in Python come from Python, as strings beside the
  values: the session kind's label (`kind_label`), the track's name, and
  whether a position is shown. The browser doesn't re-derive them.
- The card strings (`title`, `result`) stay in the API for the results cards
  and as a fallback.

Settles: #236 R1a, #297, #298.

### 7. Layout and navigation

- **Mobile first.** Components lay out by their own width (container
  queries). Only the shell uses viewport breakpoints.
- **The shell holds the sections:** Sessions now; Live, Progress and Setup as
  their releases come.
  - On a phone, a bottom tab bar.
  - From 1024 px, a side rail.
  - Neither until there are two sections. There is never a tab for something
    not built.
- **The URL is the view's state.** Filters, picked laps, compare's laps and
  "show short sessions" are all in the URL. Back, reload and a shared link all
  keep the view. Per-viewer preferences, such as hidden chart channels, go in
  `localStorage`, read defensively.
- **Every interactive part is at least 44 × 44 px.** Nothing depends on
  hover: a tooltip has a tap equivalent.

Settles: #295 R6, #296 R4, R7, #297 R5, #298 R5, #299 R1.

### 8. A component kit, and `/_kit` as the review surface

- Pages are put together from the kit: shadcn/ui primitives styled by tokens,
  and our components (`LapTime`, `Gap`, `Position`, `LapFlag`, `StatTile`,
  `SessionCard`, `LiveBadge`, `EmptyState`, `ErrorState`, `Unknown`). They
  are not styled one by one.
- A new visual pattern lands in the kit first, with all its states.
- `/_kit` shows every component in every state. It is in production builds
  but not linked. CI screenshots it at phone, iPad and desktop widths and runs
  axe over it. It is where the look is reviewed, on the real devices through
  `make web-preview` (#237).

Settles: #295.

### 9. Every view designs five states

Each data view has an explicit design for each of these:

| State | Design |
|---|---|
| **Loading** | skeletons shaped like the content, shown only after 150 ms, so nothing jumps |
| **Empty** | what is missing and what to do ("Drive a lap with the engineer running") |
| **Error** | what failed, the detail behind a disclosure, and Retry. The shell keeps working. An engineer that is down never blocks a data page |
| **Unknown** | an unknown track, car or position is shown as unknown, muted, with the reason on tap; never guessed, never hidden |
| **Live** | see point 10 |

- **Short sessions** (no full lap) are tucked away, not deleted, the same way
  the results cards skip them.

Settles: #295 R2, R3, #297 R4, R7, #298 R7, #299 R9.

### 10. Live when the car is live

- The shell always shows what the engineer is doing (#292, #296): live, with
  track and lap; paused; replay; demo; idle; or offline.
- While a session is live, the list and the session page refresh every 5 s
  with ETags. A new lap appears without a reload, and without moving what you
  are reading. When nothing is live, they refresh on focus only.
- Values update in place, with no count-up animations. A live dot pulses,
  except under reduced motion.
- When the engineer and the pit wall versions differ, the shell says a deploy
  is rolling out.

Settles: #296 R2, R3, #297 R3, #298 R6.

### 11. Accessibility is checked, not hoped for

- WCAG 2.2 AA is the target.
- `@axe-core/playwright` runs on every route at every width in `make check`,
  with no serious or critical violations allowed.
- Tables are `<table>`, with captions and header cells. Focus is visible. Every
  action can be done from the keyboard.
- `lang="en-GB"`. Charts have a text summary.

Settles: #295 R5, and an AC in each page issue.

### 12. Motion and icons

- **Motion:** 150 to 200 ms, ease-out, for state changes only (a sheet
  opening, a row expanding), never for data. `prefers-reduced-motion` turns it
  off.
- **Icons:** Lucide (shadcn/ui's set), at one size and stroke. Emoji stay on
  the Discord cards and are not used in the web app.

Settles: #294 R9, #295.

### 13. Writing

- Sentence case, British English and plain words: the same voice as the
  engineer and the docs.
- No exclamation marks.
- An error says what happened and what to do next.
- Numbers follow point 5.

### 14. Review on real devices

- Every UI PR links its CI screenshots at the three widths, plus `/_kit`'s.
- The NUC runs one pit wall. It stays Streamlit until the cut-over (#238)
  switches it in place. Until then, `make web-preview` (#237) serves the new
  app from the laptop, over a read-only copy of the NUC's store, to the phone
  and iPad on the home Wi-Fi. Each page issue has an acceptance check on the
  user's phone or iPad after a real drive.

Settles: the device ACs in #295 to #299.

## Consequences

- `docs/design.md` is the working reference: token values, the type scale,
  the format table, the kit and the information architecture. It changes in
  normal PRs. Changing a rule here needs a new record.
- `make web-check` gains the literal lint, the contrast test, the brand
  freshness check, the shared format cases and axe. A design mistake fails CI
  the way a type error does.
- #236 sends more fields than the Streamlit page used (point 6).
- The 0.7 pages are designed, not ported. #238 shrinks to the cut-over and the
  clean-up.
- The dashboards (#240) use the same tokens and formatter, with the 7:1 floor
  and their own big-number scale.

## What each affected issue does because of this

| Issue | Change |
|---|---|
| #236 | R1a: values plus Python-owned labels; R1b: same-track route; R9: ETag a MUST, gzip |
| #237 | R5: an unstyled proof page only; R10: no theme work (it moves to #294); `make web-build` |
| #238 | The cut-over and clean-up only; the pages are #297 to #300 |
| #240 | The tokens, `format.ts` and the 7:1 floor; HTTPS is live |
| #241 | Layouts use the same tokens; the designer is a kit consumer |
| #292 to #300 | Built to these points; each links this record |
| #117, #34, #118 | Charts on #299's `UPlot.tsx`, pages from the kit |
| #138, #139 | Forms from the kit, in the shell |

## Alternatives considered

- **A light theme from the start** (#237 R10 as first written).
  - For: daylight rooms, and the system setting.
  - Against: twice the screenshots to review, and contrast pairs to keep, for
    a pit wall read after VR in a dim room. Point 2 keeps the option.
- **Styling pages directly with Tailwind classes, without a kit.**
  - For: faster to the first page.
  - Against: the first page's choices become the pattern by copying. A kit
    with `/_kit` makes the look one reviewable thing.
- **A ready-made dashboard theme** (Tremor, or a Material theme).
  - For: polish out of the box.
  - Against: they look like every SaaS dashboard. The brand is a track-day
    shop, not an admin panel, and shadcn/ui is meant to be restyled.
- **Formatting numbers on the server** (the API sends strings).
  - For: one formatter, in Python.
  - Against: the dashboards format 20 to 30 frames a second in the browser,
    and charts need values. Shared cases (point 5) keep two formatters equal.

## References

- WCAG 2.2: https://www.w3.org/TR/WCAG22/
- Tailwind v4 theme variables: https://tailwindcss.com/docs/theme
- shadcn/ui theming: https://ui.shadcn.com/docs/theming
- Fontsource: https://fontsource.org/
- Lucide: https://lucide.dev/
- axe with Playwright: https://playwright.dev/docs/accessibility-testing
