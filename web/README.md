# The web app

For anyone working on the React pit wall in `web/`: its stack, the rules the build enforces, Node, and the commands. What a driver sees is in [the pit wall guide](../docs/pitwall.md).

`web/` is the React pit wall (ADR 0003): Vite,
React and TypeScript (strict), Tailwind, Radix through shadcn/ui components in
`web/src/components/ui/`, TanStack Query, and React Router in data mode. It
builds to static files in `web/dist`, which `those-who-run pitwall --static
web/dist` serves (or `GT7_PITWALL_STATIC`): the session list, the session page
and lap compare ([the pit wall guide](../docs/pitwall.md)); a results card's old `/?session=<id>`
link lands on `/sessions/<id>`.

- **Data** comes only through the client generated from `web/openapi.json` into
  `web/src/api/schema.d.ts` (`npm run api` in `web/` after `make openapi`), and
  the TanStack Query hooks in `web/src/api/hooks.ts`. ESLint fails `fetch` or
  the client anywhere outside `web/src/api/`.
- **Style comes only from the design tokens** (ADR 0004,
  [`docs/design.md`](../docs/design.md)) in `web/src/styles/`: ESLint fails a
  colour literal or an arbitrary Tailwind value anywhere else in `web/src/`, a
  Vitest test checks every allowed colour pair's contrast, and the brand
  colours are generated from `brand.py` into `web/src/styles/brand.css` (`make
  brand-css`; `make check` fails when it is stale). The fonts (Barlow and
  Barlow Semi Condensed) are self-hosted from `@fontsource`; the app is dark
  only.
- **Numbers become text only in `web/src/lib/format.ts`**, whose cases,
  `tests/fixtures/format-cases.json`, pytest checks against the results card's
  formatter too.
- **No browser-only code at module top level**: a Vitest test imports every
  route module under Node with no DOM.
- **Each route is a lazy chunk**, under a gzipped budget in
  `web/bundle-budget.json` (the entry, and each route at most 60 KB). `node
  scripts/bundle-budget.ts --set` in `web/` resets it to the build plus 10%.
- **Playwright** runs the built app against the real `pitwall` over a store
  replayed from fixtures, in Chromium at 390×844, 820×1180 and 1440×900. It
  checks nothing scrolls sideways and saves screenshots to
  `web/test-results/screenshots/`, which CI uploads. The helpers in `web/e2e/`
  (the server, the viewports, the screenshot) are shared by every page's spec.
  Behind the pit wall is a stub engineer (`web/e2e/engineer.ts`), down unless a
  test asks for a state with `setEngineer(page, "driving")`.

Node (26 LTS) is pinned in `web/.node-version` and `engines`, every package
exactly in `web/package-lock.json`, installed with `npm ci`. Add or change a
package with the npm that ships with that Node.

```sh
make web-build       # web/dist
make web-dev         # Vite on http://localhost:5173, /api proxied to a local pitwall on 9852
make web-check       # ESLint, tsc, Vitest, client freshness, bundle budget, Playwright
cd web && npx playwright install chromium   # once, for web-check
```

**On the phone and iPad** from a laptop: `make web-preview` ([the preview](../docs/pitwall.md#the-preview-on-the-phone-and-ipad)).
