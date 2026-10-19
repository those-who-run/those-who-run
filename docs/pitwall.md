# The pit wall

For the driver and anyone running the pit wall: the web app as a driver uses it, the data API behind it, the store it reads, the preview on a phone or iPad, and the pitwall image. Back to the [docs index](README.md).

## Pages

The pit wall is a React app over the session store, served with its read-only
data API by `those-who-run pitwall` on port 9852 (`--port` or
`GT7_PITWALL_PORT`, `--address` to bind; ADR 0003). One column, so it works on
a phone straight after a race:

- **Sessions** (`/`): grouped by day in your browser's time zone, newest first,
  each with its results card (title, result, best lap, car, fuel used). The
  session being driven is pinned at the top with the engineer's lap and
  position, and follows its laps without a reload. Filter by track, car,
  session kind and dates; the filters live in the URL. A session with no full
  lap is tucked away until asked for (`?all=1`).
- **A session** (`/sessions/<id>`): the result first, then stat tiles, the race
  story (lap time and position by lap) and the laps: time, gap to the best lap,
  fuel used and left, position (only in a field GT7 flags, as on the card), top
  speed and flags: **pit** and **out** for the in-lap and out-lap the pit-stop
  detector stored (tyre-only stops included; sessions stored before it fall back
  to a rise in fuel), **partial** for the lap the session ended in. GT7 does not
  report track limits. Pick two laps to compare; the picks are in the URL.
- **Lap compare** (`/sessions/<id>/compare?a=&b=`): speed, throttle, brake, gear
  and RPM of two laps over time from each lap's start, from the same session or
  another at the same track, with one cursor across every chart (a horizontal
  drag scrubs on a phone), drag or pinch to zoom. Distance replaces time once
  #15 lands.

A results card's old link, `/?session=<id>`, opens that session. The pit wall
only reads: the index is opened read-only and no session data is written.

## The shell

Every page sits in the shell (`web/src/app/`, #296): a header with the 走り屋
wordmark and the **live engineer chip**, which asks `/api/engine/status` every
5 s while the tab is visible and says "Live · Suzuka Circuit · L3", "Paused",
"Replay", "Demo", "Idle" (or "In the menus"), or "Engineer offline" when the
engineer doesn't answer; the pages carry on either way. Tap it for the
engineer's version, telemetry and voice, a link to the live session, and the
pit wall's own version; when the two versions differ it says a deploy is
rolling out. The sections' navigation (`web/src/app/sections.ts`) appears once
there are two. **Add to Home Screen** on the iPhone (Safari, Share, Add to Home
Screen) gives the 走り屋 icon and opens the pit wall full screen with no Safari
bars, from `web/public/manifest.webmanifest`; there is no service worker, so a
deploy is never hidden behind a stale cache.

## Running it

Because the index is in WAL mode, a reader still needs to write SQLite's
shared-memory file, `index.sqlite-shm`, next to it, and needs `-wal` and `-shm`
to exist already if it cannot create them. SQLite removes both when the last
connection closes, so on a read-only mount (`:ro`, `readOnly: true`) the pit
wall can only open the index while the engineer is running. Mount the data
directory read-write for the pit wall; it still opens the index `mode=ro`
(see #35).

It needs only the core install (aiohttp, DuckDB, PyYAML), not the `engineer`
extra (Discord, Piper, gt-telem, metrics), and the built web app (`make
web-build`, which needs Node; see [The web app](#the-web-app)):

```sh
make web-build
GT7_DATA_DIR=./data those-who-run pitwall --static web/dist   # http://localhost:9852
```

Its configuration:

| Variable | Default | Purpose |
|---|---|---|
| `GT7_DATA_DIR` | `./data` | The session store it reads. |
| `GT7_PITWALL_PORT` | `9852` | Its port (`--port` wins). |
| `GT7_PITWALL_STATIC` | unset | The built web app (`--static` wins). The pitwall image sets `/app/web`. |
| `GT7_ENGINEER_URL` | `http://those-who-run:9850` | The engineer's read-only port, for the live chip and `/api/engine/dash`. |
| `GT7_ENGINEER_CONTROL_URL` | `http://those-who-run:9851` | The engineer's control port, for `/api/engine/control/*`. |

The pitwall image (below) carries the built app:

<!-- x-release-please-start-version -->
```sh
podman run --rm -p 9852:9852 -v ./data:/data muldoon/those-who-run:0.7.4
```
<!-- x-release-please-end -->

It listens on all addresses and has no login: keep it on the LAN. The images'
health check is `those-who-run healthcheck`: it probes the engineer's `/healthz`
on `GT7_METRICS_PORT` for `run`, and the pit wall's `/healthz` on
`GT7_PITWALL_PORT` (or `--port`) for `pitwall`.

## The preview on the phone and iPad

**On the phone and iPad from a laptop**: `make web-preview
PREVIEW_CONTEXT=<kube context>` builds `web/dist`, copies a deployed store into
`.preview/` (git-ignored) by `tar` out of the pit wall pod's `/data` with
`kubectl exec` (it only reads there, never writes), and runs `those-who-run
pitwall --address 0.0.0.0 --static web/dist` over the copy. Open
`http://<laptop>:9852` on the same network. `PREVIEW_CONTEXT` names the kube
context the pit wall runs in and has no default. `/api/engine/*` goes to the live
engineer, on port 9850 of the node its pod runs on (asked of the cluster), so
the engineer's status is live while the sessions are the copy;
`PREVIEW_ENGINEER` overrides it.

## The data API

`those-who-run pitwall` serves the pit wall's read-only data API on port 9852
(`--port` or `GT7_PITWALL_PORT`, `--address` to bind), for the React pit wall
(ADR 0003) and the dashboards. It needs only the core install: aiohttp,
DuckDB and PyYAML.

| Route | What it returns |
|---|---|
| `GET /api/v1/sessions?track=&car=&kind=` | Sessions, newest first, and the values each filter can take |
| `GET /api/v1/sessions/{id}` | One session |
| `GET /api/v1/sessions/{id}/laps` | Its lap table, flags included (`pit`, `out_lap`, `invalid`, `restart`, `best`, `clean`) |
| `GET /api/v1/sessions/{id}/laps/{lap}/trace?points=1500` | Speed, throttle, brake, gear and RPM against time, thinned keeping peaks |
| `GET /api/v1/sessions/{id}/same-track` | The other sessions at the same track, for lap compare |
| `GET /api/v1/openapi.json` | The OpenAPI 3.1 schema of all of these |
| `GET /healthz` | `ok`, `version`, `index` and `engineer` |
| `/api/engine/status`, `/api/engine/dash`, `/api/engine/control/{path}` | Forwarded to the engineer |

- **Values, not card strings** (ADR 0004 point 6). A session carries
  `final_position`, `total_cars`, `best_lap_ms` and the rest as numbers, with
  the names Python owns (`kind_label`, `track.name`, `position_shown`) beside
  them, and the card's `title` and `result`.
- **The schema** is generated from the response models in
  `src/those_who_run/pitwall/api_models.py` and committed as
  `web/openapi.json`. Change a model, run `make openapi` and commit the file:
  `make check` fails while it is stale.
- **Read-only**: the index is opened `mode=ro` per request and
  nothing is written under `GT7_DATA_DIR`. Responses carry an `ETag` that
  changes only when the engineer writes (a trace's, only when its lap file
  does), so polling gets 304; JSON over 1 KB is gzipped.
- **The engineer, on the same origin.** `/api/engine/status` and the dash
  WebSocket `/api/engine/dash` go to `GT7_ENGINEER_URL`'s `/api/v1/status` and
  `/api/v1/dash`, and `/api/engine/control/{path}` to
  `GT7_ENGINEER_CONTROL_URL`'s `/api/v1/{path}`. The `Authorization` header
  passes through unchanged and is never logged. With the engineer down these
  answer 502 within 2 s, and the data routes carry on.
- **`/healthz`** is 200 while the data directory is readable, with no index yet
  on a new volume too, and 503 when it is not. `engineer` says whether the
  engineer answered; an engineer that is down never fails it.
- **`--static DIR`** serves the built web app (`web/dist`) on every other path,
  with `index.html` for client routes such as `/sessions/<id>` and
  `/?session=<id>`. Hashed files under `assets/` are cached for a year;
  `index.html` is never cached.

```sh
GT7_DATA_DIR=./data those-who-run pitwall                 # http://localhost:9852
curl -s localhost:9852/api/v1/sessions | jq '.sessions[0]'
```

## The store

Every frame of every lap is kept, so the pit wall (milestone 2.0) can show
racing lines, traces and growth over time. Under `GT7_DATA_DIR`:

```
index.sqlite                      sessions and laps tables, for listing and filtering
index.sqlite-wal, -shm            SQLite's write-ahead log, while a process has it open
engineer.lock                     the writer lock: held by whatever is writing the store
sessions/<id>/lap-NN.parquet      60 Hz frames for that lap, ZSTD compressed
sessions/<id>/summary.json        human-readable summary
```

Frames are buffered in memory and written on a background thread when the lap
completes, so a crash loses at most the lap in progress and callouts are never
held up by disk. A lap's row goes into the index only once its file is
complete, so the pit wall never shows a lap without its frames. A partial lap at the end of a session is written with
`complete = 0`. Restarting from the pause menu closes the session and opens a
new one; quitting closes it; Ctrl-C closes whatever is open. Budget roughly
20 MB per hour of driving (#36 measured 17.5 to 23 MB). Parquet is written and
read with DuckDB; any Parquet-aware tool can read the files. From 0.3 frames also carry the body
rotation (`rot_x`, `rot_y`, `rot_z`, `orientation`) and spin (`ang_vel_*`),
raw from the packet, for drift detection; older laps lack those columns.

The index is in SQLite's WAL mode, so the pit wall reading it never holds up
the engineer's writes. There is one writer at a time (ADR 0001): `run` holds
an exclusive lock on `engineer.lock` for as long as it is up, and every other
command that writes the store (`tracks backfill`, `post`, `rebuild-best`,
`replay --store` into it) refuses with exit code 1 while it does. Use the pit
wall, or stop the engineer first. The engineer likewise refuses to start while
one of those is running.
The pit wall only reads and never takes the lock.

## The pitwall image

`docker build --target pitwall` (`make build-pitwall`) is the pit wall alone:
the core install and `web/dist` at `/app/web`, with `GT7_PITWALL_STATIC=/app/web`
and `CMD ["pitwall"]` on port 9852. It has no Discord, Piper, gt-telem,
prometheus-client, audio libraries, voice or Node (about 210 MB). Each
release pushes it as `muldoon/those-who-run:<version>-pitwall`, next to the
engineer's tag. The default target is the engineer's image (about 940 MB), which
has no pit wall in it.
