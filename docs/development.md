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

## Fixtures

Deployed, the engineer records on its own: with `GT7_RECORD_DIR` set, every
outing (from leaving the menu to returning to it) becomes one
`<dir>/<YYYYMMDD-HHMMSS>.jsonl.gz` (UTC), about 20 MB an hour, and only the newest
`GT7_RECORD_KEEP` (20) files are kept. Cut a recording down to a test fixture
with `thin`: it keeps every frame where a phase, lap, lap time, position or car
count changed, the frames either side, and one frame per half second. It
writes gzip unless given `--plain`, and adds `.gz` to the name if it is missing.
Every fixture gets an entry in `tests/fixtures/FIXTURES.yaml`: track, car,
session kind, date, outing and the behaviours it pins (a test fails on a fixture
that isn't listed). `--window 120:180` (seconds) or `--window lap3:lap5` keeps
every frame in that stretch, for physics work that needs 60 Hz; `--stride N`
keeps every Nth frame in place of one per half second.

## Web development



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
