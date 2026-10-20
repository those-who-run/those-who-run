# Development

For anyone changing the code: `make check` and the other targets, fixtures, the web app, and the brand and wordmark. Back to the [docs index](README.md).

The rules for working on the repository, for people and coding agents alike,
are in [AGENTS.md](../AGENTS.md) (and [web/AGENTS.md](../web/AGENTS.md) for the web
app): issues, the definition of done, pull requests, merging and releases.

## Make targets

```sh
make check           # what CI runs: ruff, mypy, workflow-lint, pytest with the coverage floor, web-check
make lint test       # ruff + pytest only, quicker while iterating
make workflow-lint   # zizmor and actionlint over .github/workflows/ and dependabot.yml
make web-check       # the web app only (needs Node and the Playwright browser)
make lock            # after changing dependencies in pyproject.toml: re-resolve uv.lock
make build           # podman build for linux/amd64, local only
```

**Workflows.** `make workflow-lint` runs [zizmor](https://docs.zizmor.sh/audits/)
(fails on a finding of medium severity or above) and
[actionlint](https://github.com/rhysd/actionlint) (with shellcheck over each `run:`
step), at the exact versions in the `dev` extra. With `GH_TOKEN` set, as in CI,
zizmor adds its online audits (impostor commits, known-vulnerable actions);
`release.yml` sets `ZIZMOR_OFFLINE`, so a new advisory fails PRs, not a publish. A
`# zizmor: ignore[<audit>]` comment is the last resort: it needs the reason on the
same line or the line above, and the PR that adds it says why the finding is wrong
or accepted.

**Dependencies.** Every direct dependency, Python and npm, has a row in
[dependencies.md](dependencies.md) saying why it is there. To add one:
check it is the package you mean (owner, source repository, release history,
downloads) and that nothing already listed does the job, add it to `pyproject.toml`
(then `make lock`) or `web/package.json`, and add its row in the same PR;
`tests/test_dependencies.py` fails `make check` until you do, and on a row whose
package is gone. On a PR, CI's dependency review fails on a known vulnerability
(moderate or above) or a licence GPL-3.0 can't take in what the lockfiles change.
`web/.npmrc` sets `ignore-scripts=true`: no package's install script runs.

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
| `workflow-lint` | zizmor and actionlint over `.github` (`make check` runs it). |
| `test` | pytest. |
| `docs-check` | Every internal link and anchor in the Markdown resolves, offline ([Docs checks](#docs-checks)). |
| `openapi` | Writes `web/openapi.json`, the pit wall API's schema, from its models. |
| `brand-css` | Writes `web/src/styles/brand.css`, the web app's brand colours, from `brand.py`. |
| `wordmark` | Redraws the wordmark and icons as outlines: `make wordmark NOTO=<NotoSansCJK-VF.ttc>`. |
| `brand-assets` | Writes the docs' banners, wordmarks and social preview into `docs/assets/` from `brand.py` ([Brand and wordmark](#brand-and-wordmark)). |
| `check` | Everything a PR must pass: lint, typecheck, workflow-lint, tests with the coverage floor, `web-check`. CI runs this. |
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

## Docs checks

`make check` keeps the docs and the code in step, so a PR that changes one
without the other fails:

- `make docs-check` (`scripts/docs_links.py`) checks every internal link and
  anchor in the top-level Markdown files, `web/*.md`, `docs/**/*.md` and
  `.github/**/*.md` (not `CHANGELOG.md`): relative paths exist, and `#anchors`
  match a heading by GitHub's rules (a percent-encoded path is decoded, and
  one starting `/` is from the repository's root). It never fetches external
  URLs, so it runs offline. `make check` runs it once, inside pytest;
  `make docs-check` is the quick local run.
- `tests/test_docs.py` fails when an environment variable a quoted string under
  `src/` names (`GT7_*`, `DISCORD_*`, `PITWALL_URL`, `LOG_LEVEL`) has no row in
  [the config table](setup.md#configuration), or a row names one nothing reads;
  when a command or subcommand from `build_parser()` is missing from
  [the commands table](setup.md#commands), or a row names one that doesn't
  exist; when a `.PHONY` target is missing from `make help`, or a `make help`
  target from [the make table](#make-targets); and when a metric registered in
  `metrics.py` is not named under [Metrics](operations.md#metrics). It also
  checks the config table's ports, numbers and engineer URLs against
  `Settings`' defaults.

Each failure names what is missing and the file to edit. The tables' first
column holds the name in backticks, which is what the tests read.

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

The docs' own brand assets are in `docs/assets/`: `banner-dark.svg` and
`banner-light.svg` (the README's hero, picked by the reader's theme),
`wordmark-dark.svg` and `wordmark-light.svg` (the wordmark alone, transparent,
for dark and light pages) and `social-preview.png` (1280×640, the card a link
to the repository shows). `make brand-assets` writes them with
`scripts/brand_assets.py`: the colours from `brand.py`, the wordmark's outlines
from `web/src/assets/wordmark.svg`, and the tagline outlined from Barlow with
the same pinned fontTools as `make wordmark`. It needs Node's packages (for the
font) and ImageMagick (for the PNG), and running it twice gives the same bytes.
`make check` fails when an SVG there is stale against `brand.py` or the
wordmark; the PNG is not checked, since rasterising differs between machines,
so regenerate it with the SVGs.

**The social preview is uploaded by hand.** GitHub has no API for it, so after
`social-preview.png` changes, the repository's owner uploads it in
*Settings → General → Social preview*.

Readouts are monospace. Times look like `1:41.023`, deltas like `+0.512`,
trackside glyphs are ⏱️ for times, ⛽ for fuel and 🚩 for the flag.
