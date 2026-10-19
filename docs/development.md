# Development

For anyone changing the code: `make check` and the other targets, fixtures, the web app, and the brand and wordmark. Back to the [docs index](README.md).

The rules for working on the repository, for people and coding agents alike,
are in [AGENTS.md](../AGENTS.md) (and [web/AGENTS.md](../web/AGENTS.md) for the web
app): issues, the definition of done, pull requests, merging and releases.

## Make targets

```sh
make check           # what CI runs: ruff, mypy, workflow-lint, pytest with the coverage floor, web-check
make hooks           # the git hooks (make venv runs it): once per clone, every worktree shares them
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

**Weakened tests.** On a pull request, CI's `test` job runs
`scripts/test_guard.py` over the PR's change. It fails the job when the change
deletes a test file or a test, adds a skip, an expected failure or a focused test
(`pytest.mark.skip`, `xfail`, `test.skip`, `test.only` and the rest; Playwright's
conditional `test.skip(<condition>, "<reason>")` inside a test is by design and
passes), adds a `no cover` pragma or a coverage `omit` or exclusion, lowers
`fail_under`, turns off `xfail_strict`, raises a bundle budget, or edits the
`TWR_FAIL_ON_SKIP` switch or Playwright's `forbidOnly`, unless the PR description
has a line saying why:

```text
Tests weakened: the bounds were too tight for CI's slower runner (#348)
```

at least ten characters after the colon: what was wrong with the test. Editing the
description starts no run, so re-run the failed job afterwards (`gh run rerun
<run-id> --failed`); the script reads the description when it runs. Never delete,
skip or loosen a test to make CI pass without that line. What it found goes to the
job summary either way. Dependabot's PRs are exempt. Locally:
`.venv/bin/python scripts/test_guard.py origin/main HEAD`. `xfail_strict = true`
makes an expected failure that passes fail the run.

The guard is a "say why" speed bump, not a protection: CI runs the PR's own copy
of the script, and the author writes the description, so a PR can change the
script, the workflow or just write the line. It makes the reason visible; the
maintainer's review is what decides.

**Scorecard.** `.github/workflows/scorecard.yml` runs
[OpenSSF Scorecard](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
weekly, on every push to `main` and on demand (`gh workflow run scorecard.yml`).
It scores the settings and workflows nothing in `make check` can see (token
permissions, pinned dependencies, dangerous workflows, SAST), publishes the result
behind the badge at the top of the README and uploads it to code scanning. It
runs with the Actions token, which can't read branch rules, so its
Branch-Protection check comes back inconclusive. It gates nothing: a drop is
drift to look into.

Every target, as `make help` lists it:

| Target | What it does |
|---|---|
| `help` | Lists the targets. |
| `venv` | Creates `.venv` from `uv.lock` with the dev and engineer extras (needs uv), and installs the git hooks. |
| `hooks` | Installs the git hooks (`.pre-commit-config.yaml`), shared by every worktree ([Commit hooks](#commit-hooks)). Never skip them. |
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
| `web-deps` | Installs `web/node_modules` from `web/package-lock.json` (`npm ci`). |
| `web-build` | Builds the React pit wall into `web/dist` (needs Node). |
| `web-dev` | Vite's dev server on http://localhost:5173, `/api` proxied to a local pitwall. |
| `web-check` | ESLint, tsc, Vitest, the client and `brand.css` freshness checks, the bundle budget, Playwright. |
| `docs-screenshots` | The docs' pit wall screenshots into `docs/assets/screens/`, with Playwright over the e2e store ([Screenshots](#screenshots)). |
| `web-preview` | `web/dist` over a copy of a deployed store, on `http://<laptop>:9852`; see [the preview](pitwall.md#the-preview-on-the-phone-and-ipad). |
| `archive-push` | Uploads `GT7_ARCHIVE_DIR` to the `outings` release of those-who-run/outings ([ADR 0002](adr/0002-outing-archive.md)). |
| `archive-pull` | Downloads the `outings` release into `GT7_ARCHIVE_DIR`. |
| `clean` | Removes `.venv`, caches, coverage and build output. |

## Commit hooks

`make hooks` installs a `pre-commit` and a `commit-msg` hook
([pre-commit](https://pre-commit.com/), `.pre-commit-config.yaml`). Before a commit
is made they check the staged files in seconds: ruff format and ruff check, ESLint
under `web/`, `web/openapi.json`, `brand.css` and the web client against their
sources (`make openapi`, `make brand-css`, `npm run api`), `uv lock --check`, a
gitleaks scan of the staged changes, whitespace, merge-conflict markers, YAML and
large files, and actionlint and zizmor on the workflows. The commit message must be
a conventional commit with one of release-please's types (`feat:`, `fix:`, `docs:`,
and the rest). pytest, mypy, `tsc`, Vitest and Playwright stay in `make check`.

- The hooks run the committing checkout's own tools: ruff and pre-commit from its
  `.venv`, ESLint from its `web/node_modules`. A missing one fails the hook with the
  make target that installs it (`make venv`, `make web-deps`).
- Git keeps hooks in the common `.git/hooks`, so one `make hooks` covers every
  worktree (`git worktree add`); each worktree still needs its own `make venv`
  (which also installs the hooks), or its first commit fails and asks for it. A
  branch from before the hooks commits without them.
- The external hooks (pre-commit-hooks, gitleaks, actionlint, zizmor,
  conventional-pre-commit) are pinned to a commit SHA, the tag in the `frozen:`
  comment. `make hooks` builds their environments once, into `~/.cache/pre-commit`
  (gitleaks and actionlint are Go programs: pre-commit uses the Go on `PATH`, or
  downloads one).
- Don't skip them. `--no-verify` and `SKIP=` gain nothing: CI's `test` job runs
  `pre-commit run --all-files` before `make check`, and gitleaks on every commit in
  the PR (the commit hook only sees what is staged). CI also checks the PR title
  with the commit-msg hook, since a squash merge makes the title the commit subject.
- In Claude Code, `.claude/hooks/guard.py` refuses `--no-verify`, `-n`, `SKIP=`,
  `core.hooksPath` and writes to `.git/hooks` or `.git/config`, and asks when the
  program is a variable or an alias (`$g commit`). It is a guard against mistakes,
  not a sandbox: a script file or a program that runs git itself gets past it. CI
  and the `main` ruleset are the backstop. It needs Claude Code v2.1.295 or later:
  older versions ignore `onFailure: "block"`, so a guard that crashes or is missing
  lets the command run.
- `pre-commit run --all-files` runs them all by hand; `pre-commit run <id>` runs one.

## Agent guardrails

Agents (Claude Code) do most of the work here, as the maintainer, with the maintainer's `gh` token
(admin on this repository), kubeconfigs and registry logins. The repository is
public, so an agent also reads text from strangers. The committed
`.claude/settings.json` applies to every session and subagent in every worktree
(#352):

- **Denied: reading or editing secrets.** `.env` and `.env.*` in any directory,
  `~/.kube/`, `~/.ssh/`, `~/.aws/`, `~/.config/gcloud/`, `~/.gnupg/`,
  `~/.config/helm/`, `~/.docker/`, `~/.config/gh/`, `~/.config/containers/auth.json`,
  `/run/user/*/containers/auth.json` (`$XDG_RUNTIME_DIR`), `~/.netrc`,
  `~/.claude/.credentials.json`, `~/.claude.json`, and any `*.pem`, `*.key`, `id_rsa*`
  or `id_ed25519*`. The deny rules in `.claude/settings.json` cover the Read and Edit
  tools. For Bash, the guard blocks a command that names one of those paths as an
  argument or a redirection (`cat`, `head`, `sed`, `cp`, `tar`, `source`, `curl -F`,
  `python3 -c "open(...)"` and the rest; `ls`, `echo` and `test` pass, and for `git`
  and `gh` only a bare path argument counts, not a commit message or a PR body). It
  does not stop a program or script that builds the path itself; only the sandbox
  does. `.env.*` also covers a template such as `.env.example`: none exists, and one
  that does needs an exception here.
- **Blocked: actions that reach outside the repository, by
  `.claude/hooks/guard.py`.** The guard is a PreToolUse hook that parses every Bash
  command, following chains, `$(...)`, `bash -c`, `env` and wrappers. A blocked
  command tells the agent why and to ask the maintainer:
  - `git push` that forces (`-f`, `--force*`, `+ref`), mirrors, deletes, prunes,
    pushes tags or a `v*` ref, or pushes to `main`, and `git tag v*`: a `v*` tag
    publishes a release;
  - `gh pr merge --admin`, `gh release create|edit|delete|upload`,
    `gh workflow run|enable|disable`, `gh repo edit|delete|rename|archive`,
    `gh secret`, `gh variable` and `gh ruleset` writes, `gh alias set`, `gh auth token`;
  - `gh api` writes to the repository itself, its rulesets, Actions permissions,
    environments, collaborators, hooks, keys, branch protection, releases, refs,
    dispatches and merges, and the GraphQL mutations that do the same;
  - `docker`/`podman` `login`, `logout`, `push` (and `--push`), `--privileged`, and
    mounting `/`, the home directory, its secrets or the container socket;
  - `kubectl` (and `oc`) and `helm` commands that change the cluster or the current
    context. Reading (`get`, `logs`, `describe`) is fine. The cluster changes through
    the deployment repository and Argo CD;
  - skipping the commit hooks (see [Commit hooks](#commit-hooks)).
- **Asked first: public posts in the maintainer's name, and other repositories.**
  `gh issue create|comment|edit|close`, `gh pr create|comment|review|close` (also
  through `gh api`), `gh pr merge` and `gh pr ready` (agents merge only when asked),
  `gh` with `-R`/`--repo` outside `those-who-run/`, and `gh run rerun`, which may
  re-run a release. The guard's `GH_ASK` is the one list of these: `settings.json`
  has no `Bash(...)` rules to drift from it, and a test keeps it that way. Edits to
  `.claude/settings.json`, `settings.local.json` and `.claude/hooks/` ask too (Edit
  rules in `settings.json`), so an agent can't quietly loosen its own policy.
- **Fails closed.** If the guard crashes or times out, the command is blocked
  (`onFailure: "block"`, Claude Code v2.1.295 or later). If it can't parse a command
  that names git, gh, kubectl, helm, docker or podman, or the program is a variable
  or an alias (`g=git; $g push`), it asks. `--dangerously-skip-permissions` is
  refused here (`disableBypassPermissionsMode`).
- **Not a sandbox.** The guard reads the command line, so it catches mistakes, not
  an agent set on getting round it: a script file, a program that runs git or opens
  a file itself, or a command decoded at run time gets past it. A bare `git push` on
  a branch that tracks `main` names no branch, so the guard can't see it; the `main`
  ruleset (a pull request, squash only, `test` and `image` passing) refuses it, as it
  refuses any direct push to `main`. CI and the ruleset are the backstop.
- **Logged.** Every block and ask goes to `~/.claude/twr-guard.log`: time, decision,
  rule, and the first 200 characters of the command, with tokens, `Authorization`
  headers, passwords and secret values redacted.

It runs only in Claude Code: the maintainer's own terminal is untouched. To see
what it would do with a command:

```sh
echo '{"tool_name": "Bash", "tool_input": {"command": "git push --tags"}}' | python3 .claude/hooks/guard.py
```

A new rule is one line in the tables at the top of `guard.py` plus a blocked case
and a near miss in `tests/test_claude_hooks.py`.

**Kept in user settings, outside the repository** (`~/.claude/settings.json`). Claude
Code reads these only from user or managed scope:

- `autoMode.environment`: describe this repository (public, `those-who-run`, the
  rules above) rather than another project's.
- The sandbox (`sandbox.enabled`, with `filesystem.denyRead` on the secret paths
  above). It is the only control that also stops a script reading those files
  itself.

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
