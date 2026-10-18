# 0003: UI stack, and where it is served

**Status:** Accepted, 2026-10-18. Asked for by #234. Amends
[0001](0001-data-and-network.md) point 5 and its "What #35 does"; the rest of
0001 stands.

## Context

The pit wall is a Streamlit app (#33, `pitwall/app.py`). It lists sessions,
shows a session's laps and compares two laps. The roadmap now asks for more
from the UI than Streamlit does well:

- **A pit wall that works by touch** on a phone in portrait, on an iPad and on
  a desktop. Setup (#138, #139), the track map and delta trace (#117), corners
  (#34) and growth (#118) are all still to come.
- **Dashboards** on a phone or tablet by the wheel: landscape, full screen,
  big type, updated 20 to 30 times a second, more than one screen at once. The
  aim is "the SimHub for GT7": the engineer's numbers on a screen as well as
  in your ear.

What Streamlit costs today:

- It reruns the whole script on every interaction. A 20 Hz widget would mean
  20 reruns a second for each client.
- It is about 300 MB of the image, with pandas and pyarrow (#26, ADR 0001
  point 5).
- `AppTest` (`tests/test_pitwall_page.py`) checks the script, not what a phone
  shows.

The network has its own constraint. Under ADR 0001 point 3, the engineer serves
read-only routes on 9850 with no token, and control routes on 9851 with the
admin token on every request. A browser that called the engineer directly
would need CORS on both ports, the engineer's address and two origins.

More than 20 open issues assume Streamlit, or decide a piece of this
themselves: pages, charts, AppTest, the `web` extra, the port and probe, CORS
on the engineer. This record decides it once.

## Decision

### 1. Streamlit is retired once the API server exists

- No new Streamlit pages are built.
- The pit wall is ported to the new stack in 0.6 (#238), as soon as #173 has
  put an aiohttp server on the engineer's event loop. Then `pitwall/app.py`,
  the `web` extra, the `web` command and the Streamlit tests are removed.
- Until #238 ships, today's Streamlit pit wall and its deploy (#35) stay as
  they are.

Settles: #138 and #139 (SPA routes, not Streamlit views), #168 R4 (AppTest
stays until #238), #184 AC17 to AC19 (superseded by #238).

### 2. The UI is a React single-page app, built to static files

- **Build:** React, Vite and TypeScript, in `web/`. There is no Next.js, and
  no Node at runtime: Node builds `web/dist`, and Python serves it.
- **Data:** TanStack Query, over a TypeScript client generated from the data
  API's OpenAPI schema (`web/openapi.json`, committed). `make check` fails
  when the client is older than the schema.
- **Routing:** React Router in data mode. The scaffold (#237) may pick
  TanStack Router instead, and says why in its PR.
- **UI:** Tailwind for styling, Radix primitives through shadcn/ui
  components.
- **Charts:** uPlot for traces, and plain canvas for live widgets.
- **Bundles:** each route is its own chunk. A size budget for the entry
  chunk and each route chunk is checked in `make check` and CI.

Settles: #237, #238, #117 R6 and R8 and #118 R2 (how the charts are drawn).

### 3. Rules that keep server rendering cheap later

The app is static today, but nothing should stop a later move to React Router
framework mode or Next.js. Two rules, both checked by #237:

- **All data goes through the generated client and its hooks.** Components
  never call `fetch` or the client themselves. A lint rule allows them only
  under `web/src/api/`.
- **No browser-only code at module top level.** That means `window`,
  `document`, `localStorage`, `navigator` and canvas. A test imports every
  route module under Node, with no DOM.

### 4. Two modes: pit wall and dashboards

- **Pit wall:**
  - responsive, and touch first;
  - phone portrait, iPad and desktop;
  - cards lay out by their own width with container queries, not the
    viewport's;
  - tap targets of at least 44 px.
- **Dashboards:**
  - landscape, full screen, large glanceable type;
  - an installable PWA, with a wake lock and automatic reconnect;
  - fed by a WebSocket from the engineer at 20 to 30 Hz (#239). Widgets draw
    to canvas from a plain store outside React's render loop, and React
    renders only when the layout or connection state changes;
  - several screens at once, each on its own layout;
  - built from widgets in a registry plus a layout file (JSON, with a
    schema), so a SimHub-style layout designer (#241) can come later
    without a rewrite.

  The first dashboard is #240.

Settles: #240, #241, #239 (rate and fan-out).

### 5. Definition of done for UI work

- Playwright runs the built app against the real pit wall server, over a store
  replayed from fixtures. It runs at three sizes: phone portrait (390×844),
  iPad (820×1180) and desktop (1440×900).
- Dashboards are checked at phone and iPad landscape instead.
- Each run checks for no horizontal scroll and that the key elements are
  visible, and saves screenshots. CI uploads them, and the PR links them.
- `make check` runs this through `make web-check`, and fails when Node or the
  browser is missing, the same as a skipped test (#161).
- Component tests (Vitest and Testing Library) replace AppTest.

Settles: the Definition of done of every UI issue from #237 on.

### 6. Where things run (extends 0001 point 3)

| Path on `pitwall.nuc.home.arpa` | Served by | Notes |
|---|---|---|
| `/`, `/sessions/...`, `/dash/...`, assets | the pit wall pod | `web/dist`, SPA fallback to `index.html` |
| `/api/v1/...` | the pit wall pod's data API (#236) | read-only: sessions, laps, traces; aiohttp; the index opened `mode=ro`, Parquet through DuckDB |
| `/api/engine/status` | proxied to the engineer's 9850 `/api/v1/status` | read-only, no token |
| `/api/engine/dash` (WebSocket) | proxied to the engineer's 9850 `/api/v1/dash` (#239) | read-only, no token |
| `/api/engine/control/...` | proxied to the engineer's 9851 `/api/v1/...` | the browser's `Authorization` header passed through, never stored or logged |

- **One origin.** The browser only ever talks to the pit wall. It needs no
  CORS, it never learns the engineer's address, and the PWA has one scope.
- **The data API never writes.** It has no route that changes data and holds
  no secret. ADR 0001 points 1, 2 and 4 hold unchanged.
- **The engineer keeps its two ports.** The dash WebSocket is a new route on
  9850. It is read-only, so it belongs there by 0001 point 3. The engineer
  does not serve static files, and it does not need CORS.
- **The admin token stays out of the pit wall pod.** The driver types it, the
  browser keeps it in `sessionStorage` for the tab's life, and the proxy
  forwards it (#140 R3).
- **The pit wall server:** `those-who-run pitwall` serves on
  `GT7_PITWALL_PORT`, default 9852, with `/healthz` for probes. It reaches
  the engineer at `GT7_ENGINEER_URL` (default `http://those-who-run:9850`)
  and `GT7_ENGINEER_CONTROL_URL` (default `http://those-who-run:9851`).

Settles: #173 (no CORS, a WebSocket route, no static files), #136 (status and
the dash on 9850, control on 9851, reached through the proxy), #140 R3, #142
R3.

### 7. Amends 0001 point 5: the `pitwall` image target

- The Dockerfile gets a Node build stage, which builds `web/dist`.
- The `pitwall` final stage is a small Python runtime with what the data API
  imports (aiohttp, duckdb, pyyaml), plus `web/dist` at `/app/web`. It has no
  Streamlit, pandas or pyarrow, no voice, no audio libraries and no Node. It
  is still published as `muldoon/those-who-run:<version>-pitwall`, with the
  same version as the engineer.
- The `web` extra (about 300 MB) goes away with Streamlit (#238).
- #26's 450 MB budget is for the `engineer` image, as before. Without the
  `web` extra the engineer needs no split to meet it. #237 adds the
  `pitwall` target; it no longer waits for #26.

### 8. Own the GT7 decoder

The engineer decrypts and parses GT7 packets in its own code, and gt-telem is
dropped (#235, 0.6). The pin on gt-telem and the private attributes still
used (`_handle_data`, `_callback_executor`, after #201) would otherwise sit
under the dash stream and every 0.7 telemetry issue (#88, #130, #192). This is
recorded here because the dash frame (#239) depends on it as well.

## What #35 does because of this

ADR 0001's "What #35 does" stands for the Streamlit deploy, which stays until
#238. Then #238 changes:

- **Image:** `muldoon/those-who-run:<version>-pitwall` (point 7), bumped with
  the engineer's.
- **Args:** `["pitwall"]`, not `["web"]`.
- **Port:** 9852, not 8501, on the container, the Service and the Ingress
  backend.
- **Probes:** `/healthz` on 9852, not `/_stcore/health`. A down engineer
  never fails them.
- **ConfigMap:** add `GT7_ENGINEER_URL` and `GT7_ENGINEER_CONTROL_URL`, and
  drop `GT7_WEB_PORT`.

The volumes, the no-secrets rule, the network rules and the check with the
engineer scaled to 0 are unchanged.

## What each affected issue does because of this

| Issue | Change |
|---|---|
| #173 | No CORS (one origin through the proxy). Add the dash WebSocket route (#239). Serving static files is not the engineer's job. |
| #136 | Status read-only on 9850, control on 9851 (fixes the body's "existing port 9850" for writes). Clients reach both through `/api/engine/*`. |
| #138, #139 | SPA routes, not Streamlit views. The HTTP calls go through the generated client to `/api/engine/*`. Component tests replace AppTest. |
| #140 | The token is kept in `sessionStorage`, not Streamlit session state. It is sent as `Authorization` through the proxy. |
| #142 | Browsers reach the engineer only through the pit wall proxy. R3 holds through the Service. |
| #26 | The `pitwall` target is point 7's. The 450 MB budget is the engineer's, and the `web` extra leaves the image with #238. |
| #117, #34, #36, #118 | The data functions become data-API routes in #236's server. Charts move to the SPA (uPlot or canvas). #36 R5's download becomes a route. |
| #105 | The PB card's delta-trace PNG needs a renderer on the Python side, since #117's chart now draws in the browser. |
| #183, #195, #178 | `pitwall/` becomes the data API. #183's index tables and #178's repository are what it reads. #195's contract still holds ("pitwall imports only the store's read API"). |
| #35 | The Streamlit deploy stays until #238, which changes the port, probe and args (above). |
| #184 | AC17 to AC19 (`pitwall/app.py`) are superseded by #238. |
| #168 | R4's AppTest (`tests/test_pitwall_page.py`) stays until #238 removes Streamlit. |
| #88, #130, #192 | They parse with #235's decoder rather than gt-telem. |

## Alternatives considered

- **Svelte or SvelteKit.**
  - For: smaller bundles, and a simpler model for live values.
  - Against: a smaller ecosystem for the parts this needs (Radix-quality
    accessible primitives, TanStack Query, generated clients, uPlot wrappers),
    and fewer people and agents fluent in it.
  - The live widgets avoid React's render loop anyway (point 4), which
    removes most of Svelte's advantage here.
- **HTMX with server-rendered HTML.**
  - For: no build step, and Python renders everything.
  - Against: the dashboards are canvas fed by a WebSocket at 20 to 30 Hz, and
    the pit wall's charts are client-side. HTMX would carry the forms and
    tables, and the rest would still need a JavaScript app.
- **Python UI frameworks** (Streamlit, NiceGUI, Reflex, Dash).
  - For: one language.
  - Against: each keeps state on the server per client and renders through a
    websocket of its own, which is the cost Streamlit has today. Each also
    brings its own heavy runtime into the image. None gives an installable
    PWA, or canvas widgets outside its own update cycle, without fighting
    the framework.
- **Next.js.**
  - For: server rendering, and the largest React ecosystem.
  - Against: it needs Node at runtime on the NUC, a second runtime next to
    Python, for pages that are a few kilobytes of JSON each. Static files
    from the Python server cover it today.
  - Point 3 keeps the move cheap if server rendering is ever wanted.

## Consequences

- Node is a development and CI requirement (`web/`, `make web-check`). It is
  never a runtime one.
- Two languages in the repository. #195's `CLAUDE.md` should cover `web/`'s
  layout and the rules in point 3.
- The data API's schema (`web/openapi.json`) and the dash frame's schema
  (`web/dash.schema.json`) are contracts between Python and TypeScript. Both
  are committed and checked in `make check`.
- **HTTPS.** A PWA installs, and the Screen Wake Lock API works, only in a
  secure context. `http://pitwall.nuc.home.arpa` is not one. Until the pit
  wall has TLS, #240 falls back to keeping the screen awake with a muted
  video, and says that installing needs HTTPS. Adding TLS (for example
  cert-manager with a home-lab CA trusted on the phone and iPad) is an open
  decision for the user.
- A new UI issue follows points 3 to 5. A new engineer route that the browser
  needs gets a row in point 6's table and goes through the proxy. Changing
  any of this needs a new ADR that supersedes this one.

## References

- Vite: https://vite.dev/guide/
- TanStack Query: https://tanstack.com/query/latest
- React Router modes: https://reactrouter.com/start/modes
- shadcn/ui: https://ui.shadcn.com/
- uPlot: https://github.com/leeoniya/uPlot
- openapi-typescript: https://openapi-ts.dev/
- Screen Wake Lock API: https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API
- Secure contexts: https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts
