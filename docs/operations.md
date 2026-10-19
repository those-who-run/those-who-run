# Operations

For whoever runs it: deploying the two images, metrics, `/healthz` and `/api/v1/status`, releasing, and Dependabot. Back to the [docs index](README.md).

## Deploying

Where and how it runs is up to you: nothing here assumes a host, an
orchestrator or a network layout. Each release is two images with one version,
and the two run from the same release:

| Image | Runs | Ports | Health |
|---|---|---|---|
| `muldoon/those-who-run:<version>` | the engineer, `run` | 33740/UDP in, 9850/TCP | `/healthz` on 9850 |
| `muldoon/those-who-run:<version>-pitwall` | the pit wall, `pitwall` | 9852/TCP | `/healthz` on 9852 |

- **One data volume** at `/data` (`GT7_DATA_DIR`), shared by both
  ([ADR 0001](adr/0001-data-and-network.md)). The engineer is its only
  writer and holds `/data/engineer.lock` while `run` is up, so run one engineer
  and stop the old one before starting the new. The speech cache stays outside
  the volume (`XDG_CACHE_HOME`).
- **The pit wall is read-only.** It never writes and never takes the lock. Mount
  `/data/sessions` read-only; `/data` itself stays writable only so SQLite can
  create the index's `-shm` and `-wal` files while the engineer is stopped. It
  needs no secret, only `GT7_ENGINEER_URL` and `GT7_ENGINEER_CONTROL_URL` to
  reach the engineer, and it has no login: keep it on your LAN.
- **The engineer needs the LAN.** It sends its heartbeat to the PS5 at a fixed
  `GT7_PS5_IP` and receives the telemetry on 33740/UDP, so publish that port on
  the host. Its Discord token and channel ids come from the environment.
- **Restart the engineer between drives.** `/healthz` reports `idle` and
  `idle_secs`; wait until it has been idle for a few minutes before replacing
  it, so a new image never cuts the voice mid-race. The pit wall can restart at
  any time.

## Metrics

Metric names keep the `gt7_` prefix because they describe GT7 telemetry:

`gt7_telemetry_packets_total`, `gt7_telemetry_connected`, `gt7_voice_connected`,
`gt7_in_race`, `gt7_callouts_total{rule}`, `gt7_callouts_dropped_total`,
`gt7_current_lap`, `gt7_total_laps`, `gt7_fuel_level`, `gt7_fuel_capacity`,
`gt7_fuel_laps_remaining`, `gt7_last_lap_seconds`, `gt7_best_lap_seconds`,
`gt7_speed_kph`, `gt7_speech_seconds`, `gt7_track_id`, `gt7_track_info`,
`gt7_session_info{kind,fuel_use,start}`, `gt7_results_posts_total{result}`.

`GET /healthz` returns JSON with telemetry and voice connection state, the
detected track, the session kind and `tasks`, the liveness of each long-running
task (`ingest`, `speak`, `watchdog`, `results`). `ok` is false, and the status
503, while any task is dead (a task that crashes is logged and restarted with
backoff) or while the telemetry listener is down, for example because the UDP
port is busy. The listener restarts itself with backoff inside `LiveTelemetry`,
so it is not in `tasks`; `telemetry_listening` and `telemetry_restarts` show
how it is going. No packets arriving is not unhealthy: that is normal with the
PS5 off, and shows as `telemetry_connected: false`. Voice being down is not
unhealthy either.

`idle` is false while driving frames are arriving: in a race, or paused in
one, with the last frame under `GT7_TELEMETRY_TIMEOUT_SECS` old. `idle_secs`
is 0 then, and otherwise the seconds since the last driving frame (since the
engineer's start if there has been none). A session left open because the
frames stopped, say the PS5 was switched off mid-lap, counts as idle: a
restart interrupts no one, and shutdown closes the session. A deployment can
wait on these, so a new image never restarts the engineer mid-race.

`GET /api/v1/status` says what the engineer is doing right now, for the pit
wall's header (which reaches it as `/api/engine/status`): `version`,
`started_at` (epoch seconds), `activity` (`idle`, `driving`, `paused`,
`replay` or `demo`; `idle` exactly when `/healthz` says `idle`), `idle_secs`,
`telemetry` (`connected`, `last_packet_age_s`), `voice_connected`, and
`session`, null when none is open: its `id`, `kind`, `track` (`id`, `name`,
`sure`), `car`, `lap`, `laps_total` (null when timed), and `position` and
`cars`, null where the results card would hide the position or GT7 sends
none. It needs no token and holds no token, secret, or PS5 or Discord id, and
is sent with `Cache-Control: no-store`. Its schema is in `web/openapi.json`,
from the models in `those_who_run/status.py`.

## Releasing

Merged PRs collect in one release PR; merging it ships. Nothing is released per
merge.

1. **The release PR.** On every push to `main`, release-please
   (`.github/workflows/release-please.yml`) keeps one open PR,
   `chore(release): x.y.z`. It lists the merged `feat:`, `fix:`, `perf:` and
   `deps:` commits (Dependabot's, under "Dependencies"), writes `CHANGELOG.md`, and
   bumps `__version__` in `src/those_who_run/__init__.py` (the version's one home,
   which `pyproject.toml` reads) and the version strings in the README and the guides (each line carries a release-please version
   marker, and each file with one is listed under `extra-files` in
   `release-please-config.json`). `docs:`, `test:`, `refactor:`, `build:`, `ci:` and `chore:`
   commits ship in it but are not listed, and on their own they open no release PR.
2. **Ship it.** Merge the release PR. release-please tags the merge commit
   `vx.y.z`, creates the GitHub release from the changelog, then calls
   `.github/workflows/release.yml`. That runs `make check`, fails unless the tag is
   `v` plus `__version__`, builds both images, runs `--version` in each, checks
   neither has the old pit wall's packages and smoke-tests the pit wall
   (`scripts/smoke-pitwall.sh`), and pushes `muldoon/those-who-run:x.y.z`, `latest`
   and `x.y.z-pitwall`.
3. **Deploy it.** Rolling the new tags out is up to whoever runs it (see
   [Deploying](#deploying)).

**Versions follow the milestones.** Before 1.0, `feat:` and `fix:` both bump the
patch (0.6.2 to 0.6.3), and a breaking change bumps the minor
(`bump-patch-for-minor-pre-major` and `bump-minor-pre-major` in
`release-please-config.json`). To start the next line, merge a commit whose message
has a `Release-As:` footer, and the release PR becomes that version:

```sh
git commit --allow-empty -m "chore: start 0.7" -m "Release-As: 0.7.0"
```

Open that as a PR and keep the footer in the squash commit message when you merge it.

**Release candidates** stay manual. Set `__version__` to `0.7.0-rc1` in a PR (keep
the hyphen, so release-please can replace the whole string later) and merge it.
Then tag and push the tag yourself: `git tag v0.7.0-rc1 && git push origin
v0.7.0-rc1`. The tag push runs `release.yml` directly, and the tag matches as a PEP
440 version (`v0.7.0-rc1` and `0.7.0rc1` are equal). An rc never moves `latest`. The next release PR sets `__version__` to the release.

**Tokens and secrets.** release-please runs with the Actions token. A tag that
token creates starts no workflow, so `release-please.yml` calls `release.yml`
(`workflow_call`) instead of relying on the tag push. That way no PAT or App key can
write to this repo, and each release runs once. For the same reason the release PR
gets no CI run of its own; `release.yml` runs `make check` on the tagged commit
before anything is published. Repository secrets:

- `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`: the push to Docker Hub.

The repository setting *Actions → General → Allow GitHub Actions to create and
approve pull requests* must be on for release-please to open its PR.

If a release fails after the tag exists (Docker Hub down, say), re-run the failed
jobs of that *Release PR* run. Pushing the same tag again by hand does not work,
because it already exists.

## Dependabot

Dependabot (`.github/dependabot.yml`) bumps the SHA-pinned actions, `uv.lock`,
`web/package-lock.json` (releases at least 14 days old) and the digest-pinned base
images weekly. `.github/workflows/dependabot-automerge.yml`
squash-merges the safe ones once CI has passed on the PR's head commit:

- **Merged after CI:** patch updates; minor updates of packages at 1.0 or later;
  minor updates of GitHub Actions.
- **Left for review:** majors, minors of 0.x packages, and anything in the Docker
  ecosystem (the Python base image and the uv image). A group merges only when every
  update in it is safe.

`main` is protected by a ruleset: a pull request, squash only, with the `test` and
`image` checks passing. For Dependabot, `dependabot/fetch-metadata` classifies the PR (on
`pull_request_target`, from main's copy of the workflow) and marks a safe head commit
with the `dependabot/auto-merge` status; when CI completes successfully on that
commit (`workflow_run`), the merge job squash-merges the PR, pinned to that SHA. No
job checks out or runs PR code. To hold a safe update, close the PR or push to its
branch. A merge made with the Actions token does not start the `push` CI run on main.
