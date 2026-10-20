# Development

For anyone changing the code: `make check` and the other targets, fixtures, the web app, and the brand and wordmark. Back to the [docs index](README.md).

The rules for working on the repository, for people and coding agents alike,
are in [AGENTS.md](../AGENTS.md) (and [web/AGENTS.md](../web/AGENTS.md) for the web
app): issues, the definition of done, pull requests, merging and releases.

## Make targets

```sh
make check           # what CI runs: ruff, mypy, pytest with the coverage floor, web-check
make lint test       # ruff + pytest only, quicker while iterating
make web-check       # the web app only (needs Node and the Playwright browser)
make lock            # after changing dependencies in pyproject.toml: re-resolve uv.lock
make build           # podman build for linux/amd64, local only
```

Every target, as `make help` lists it:

| Target | What it does |
|---|---|
| `help` | Lists the targets. |
| `venv` | Creates `.venv` from `uv.lock` with the dev and engineer extras (needs uv). |
| `lock` | Re-resolves `uv.lock` after changing dependencies in `pyproject.toml`. |
| `voice` | Downloads the Piper voice into `./voices`, sha256-checked. |
| `lint` | `ruff check` and the format check. |
| `fmt` | `ruff format`. |
| `typecheck` | mypy on `src/`. |
| `test` | pytest. |
| `openapi` | Writes `web/openapi.json`, the pit wall API's schema, from its models. |
| `brand-css` | Writes `web/src/styles/brand.css`, the web app's brand colours, from `brand.py`. |
| `wordmark` | Redraws the wordmark and icons as outlines: `make wordmark NOTO=<NotoSansCJK-VF.ttc>`. |
| `check` | Everything a PR must pass: lint, typecheck, tests with the coverage floor, `web-check`. CI runs this. |
| `build` | Builds the engineer's image for linux/amd64 with podman, local only. |
| `build-pitwall` | Builds the slim pit wall image, `<version>-pitwall`. |
| `replay` | Replays `FILE=recording.jsonl`. |
| `web-build` | Builds the React pit wall into `web/dist` (needs Node). |
| `web-dev` | Vite's dev server on http://localhost:5173, `/api` proxied to a local pitwall. |
| `web-check` | ESLint, tsc, Vitest, the client and `brand.css` freshness checks, the bundle budget, Playwright. |
| `docs-screenshots` | The docs' pit wall screenshots into `docs/assets/screens/`, with Playwright over the e2e store ([Screenshots](#screenshots)). |
| `web-preview` | `web/dist` over a copy of a deployed store, on `http://<laptop>:9852`; see [the preview](pitwall.md#the-preview-on-the-phone-and-ipad). |
| `archive-push` | Uploads `GT7_ARCHIVE_DIR` to the `outings` release of those-who-run/outings ([ADR 0002](adr/0002-outing-archive.md)). |
| `archive-pull` | Downloads the `outings` release into `GT7_ARCHIVE_DIR`. |
| `clean` | Removes `.venv`, caches, coverage and build output. |

## Fixtures

A test fixture is a recording cut down with `thin` (see
[Recordings](telemetry.md#recordings)).
Every fixture gets an entry in `tests/fixtures/FIXTURES.yaml`: track, car,
session kind, date, outing and the behaviours it pins (a test fails on a fixture
that isn't listed). `--window 120:180` (seconds) or `--window lap3:lap5` keeps
every frame in that stretch, for physics work that needs 60 Hz; `--stride N`
keeps every Nth frame in place of one per half second.

## Web development

The React pit wall in `web/` has its own guide, [web/README.md](../web/README.md):
the stack, the rules its build enforces (the generated client, the design
tokens, the formatter, the bundle budget, Playwright) and Node. It sits in
`web/` so it moves with the app.

## Screenshots

The pit wall's pictures in the README and [the pit wall guide](pitwall.md#pages)
are taken by `make docs-screenshots`: the session list, the race's session
page, lap compare and `/_kit`, at the phone (390×844, device scale 2) and
desktop (1440×900) sizes, into `docs/assets/screens/<viewport>/<page>.png`.
It runs `web/playwright.docs.config.ts` and `web/e2e/docs.screens.ts` over the
e2e suite's global setup (the built app on the real pit wall, the replayed
fixtures, the stub engineer), with the store dated from a fixed time
(`replay --clock`, through `E2E_REPLAY_CLOCK`), the browser's clock, time zone
and locale fixed, motion reduced, the engineer idle and no session open
(`E2E_NO_LIVE_SESSION`), so no card says "Running" under an "Idle" chip. The
session page's shot is as tall as the page, so the laps show on a phone. Two runs give the same
bytes on one machine. `make web-check` never runs it and never writes `docs/`.

Run it in a PR that changes how one of those pages looks, and look at the
diff of the PNGs in review. `make check` does not compare them: font
rendering differs between machines.

## Brand and wordmark

The palette lives in `those_who_run/brand.py` and is the only place a colour
should come from. The results cards and the pit wall's theme and lap colours
read it.

| Name | Hex | Use |
|---|---|---|
| Advan red | `#D21F1B` | accent, embed colour, flags |
| Deep black | `#111111` | background |
| Carbon grey | `#333333` | panels, secondary |
| White | `#FFFFFF` | type |

The web app's wordmark and icons (`web/src/assets/*.svg`, `web/public/`) are
outlines of Noto Sans CJK JP (走り屋) and Barlow Semi Condensed, both under the
SIL Open Font License 1.1. `make wordmark NOTO=<NotoSansCJK-VF.ttc>` redraws
them with `scripts/wordmark.py`.

Readouts are monospace. Times look like `1:41.023`, deltas like `+0.512`,
trackside glyphs are ⏱️ for times, ⛽ for fuel and 🚩 for the flag.
