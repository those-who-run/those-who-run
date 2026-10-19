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
| `brand-assets` | Writes the docs' banners, wordmarks and social preview into `docs/assets/` from `brand.py` ([Brand and wordmark](#brand-and-wordmark)). |
| `check` | Everything a PR must pass: lint, typecheck, tests with the coverage floor, `web-check`. CI runs this. |
| `build` | Builds the engineer's image for linux/amd64 with podman, local only. |
| `build-pitwall` | Builds the slim pit wall image, `<version>-pitwall`. |
| `replay` | Replays `FILE=recording.jsonl`. |
| `web-build` | Builds the React pit wall into `web/dist` (needs Node). |
| `web-dev` | Vite's dev server on http://localhost:5173, `/api` proxied to a local pitwall. |
| `web-check` | ESLint, tsc, Vitest, the client and `brand.css` freshness checks, the bundle budget, Playwright. |
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
