# Those Who Run 走り屋

**A self-hosted voice race engineer for Gran Turismo 7.**

Picture a two-bay tuning shop on the industrial edge of Tsukuba in 1995. A
Hachi-Roku on the lift, a Sylvia outside with the bonnet off, a wall of
dog-eared timing sheets, a stopwatch on a lanyard and a radio that only ever
says what matters. Nobody there has a subscription to anything. The engineer
on the pit wall counts your laps, watches your fuel and tells you where you
stand, in your ear, in plain words.

That is this. It reads the PS5's UDP telemetry, applies deterministic rules,
synthesises speech locally with Piper, and plays it into a Discord voice
channel. Join that channel from the PS5's Discord integration and the engineer
speaks inside your PSVR2 headset while the HUD is gone.

No cloud required. No subscription. One small box on your LAN.

```
 ┌───────────────────────────────────────────────┐
 │  THOSE WHO RUN        走り屋        v0.4.0     │
 │  PS5 ──UDP 33740──▶ engineer ──Piper──▶ Discord │
 │  ⏱️  lap times   ⛽ fuel   🚩 final lap   P1▲   │
 └───────────────────────────────────────────────┘
```

## ⏱️ What it says

| Rule | When | Example |
|---|---|---|
| `start_brief` | two seconds into a race: track (if known), distance, grid slot | "Sportsland SUGO. Two laps. P ten of twenty." |
| `start_brief` | the detector names the track after the brief, still on the first lap | "Nurburgring twenty-four hour." |
| `lap_time` | every completed lap, including the in-lap to a pit stop | "Lap three. One forty-one point zero. One point five over best." |
| `lap_time` | a lap beats the best so far (own template and priority); in a lap-count race lap 2 is not measured against lap 1, the start | "Lap three. One thirty-nine point zero. New best by one point zero." |
| `fuel` | estimate crosses 10, 5, 3, 2, 1 laps | "Fuel. Three laps remaining." |
| `fuel` | the lap after this one cannot be completed, once per stint | "Pit this lap." |
| `final_lap` | last lap of a lap-count race starts | "Final lap." |
| `position` | a place is gained or lost (races only), after a 3 s settle, at most every 10 s, quiet for the first 15 s | "Up to sixth." |
| `temps` | a tyre stays over 120 °C for five seconds (corners already over join it in one phrase); water or oil high; cold tyres at the start | "Rear tyres hot." |
| `telemetry` | packets stop for 3 s mid-race or mid-pause, and when they return | "Lost telemetry." / "Telemetry back." |
| `race_summary` | the chequered flag, or the end of a timed race (kept for 30 s, so it waits behind the final lap time) | "Chequered flag. Finished sixth. Best lap fifty-three point one. Fuel used thirty-eight percent." |
| `race_summary` | leaving a time trial, practice or solo run, which have no flag (`quit_kinds`) | "Session done. Seven laps. Best lap forty-nine point seven." |

The telemetry callout is the one thing not driven by frames: the live
watchdog (`GT7_TELEMETRY_TIMEOUT_SECS`, 3 s) raises it, so a quiet headset is
never ambiguous. Fuel is estimated from the last three laps' consumption and only announced
when it is shorter than the laps left in the race. The in-lap and out-lap of a
pit stop are left out of the average, and a stop starts a new stint with the
warnings armed again. Every threshold and phrase is configurable, see `rules.example.yaml`.

### The script

Phrases come from a bundled script, `src/those_who_run/data/script.yaml`:
four to six variants per callout, picked at random and never the same one twice
running, so an endurance race does not hear one sentence a hundred times. A few
situations have their own pools: into the lead or onto the podium, losing the
lead, a delta under 0.3 s or over 2 s, a new best by under 0.2 s, a win or a
podium at the flag, and "Fuel is fine to the end" when fuel was a worry and the
final lap is covered. The table above shows the plain built-in phrases.

Any template in the rules file may be a string or a list, and replaces the
script's list for that key. `script: false` at the top level of the rules file
turns the script off and leaves the single built-in phrases. Placeholders are
filled with words, never digits; `tests/test_script.py` formats every variant
and fails on an unknown slot.

Each sentence is synthesised on its own with `voice.sentence_pause_secs`
(0.35 s) of silence between them, so "Lap two." and the time and the delta do
not run together. Sentences are cached separately, so only the numbers are new
work for each lap. Callouts older than `queue.max_age_seconds` (8 s) are
dropped rather than spoken late; a rule can set its own `max_age_seconds`.

## How it works

```
PS5 (GT7) --UDP 33740--> engineer --Piper WAV--> Discord voice channel --> PS5 Discord --> headset
         <--UDP 33739 heartbeat--
```

- Telemetry: [gt-telem](https://github.com/RaceCrewAI/gt-telem). The PS5 streams
  encrypted packets at 60 Hz to whoever sends it a heartbeat.
- Rules are pure functions of consecutive `RaceState` frames and have no I/O, so
  they are tested against synthetic races and can be replayed from recordings.
- Speech: [Piper](https://github.com/OHF-Voice/piper1-gpl) with the
  `en_GB-alba-medium` voice baked into the image. Phrases are cached.
- Audio: discord.py plays WAVs into the configured voice channel. The bot joins
  when you are at a track and leaves after an idle timeout in menus.
- Observability: Prometheus metrics and a health endpoint on `:9850`, Parquet
  frames per lap plus a session summary under the data directory.

## Requirements

- A PS5 running GT7 with **Settings > Network > Telemetry** enabled, on the same
  LAN as the host, ideally with a DHCP reservation.
- A Discord server with a voice channel, and a bot application with the
  **Connect** and **Speak** permissions in that channel. No privileged intents.
- The PS5 signed in to Discord and joined to the same voice channel.
- Linux host with `ffmpeg` and `libopus`, or the container image.

## Configuration

Environment variables. The `GT7_` prefix names the game, not the project, and
is unchanged by the rebrand.

| Variable | Default | Purpose |
|---|---|---|
| `GT7_PS5_IP` | required | PS5 address. Broadcast discovery is not used when set. |
| `DISCORD_BOT_TOKEN` | required | Bot token. |
| `DISCORD_VOICE_CHANNEL_ID` | required | Voice channel the PS5 joins. |
| `GT7_RULES_FILE` | built-in defaults | YAML overriding any value in `rules.example.yaml`. |
| `GT7_DATA_DIR` | `./data` | Lap and session output. |
| `GT7_VOICE_MODEL` | `voices/en_GB-alba-medium.onnx` | Piper voice. |
| `GT7_CACHE_DIR` | `$XDG_CACHE_HOME/those-who-run`, else `~/.cache/those-who-run` | Synthesised sentence clips, reused across laps. Must be owned by the user running the engineer, and must not be inside `GT7_DATA_DIR` (the pit wall can write there). |
| `GT7_CACHE_MAX_MB` | `100` | Size cap for the speech cache; the least recently used clips go first. |
| `GT7_METRICS_PORT` | `9850` | `/metrics` and `/healthz`. |
| `DISCORD_RESULTS_CHANNEL_ID` | unset | Text channel for results cards. Unset turns them off. |
| `PITWALL_URL` | unset | Pit wall base URL, e.g. `http://pitwall.nuc.home.arpa`. Card titles link to the session there. Unset, no link. |
| `GT7_IDLE_DISCONNECT_SECS` | `600` | Leave the voice channel after this long in menus or with no telemetry. |
| `GT7_TELEMETRY_TIMEOUT_SECS` | `3` | Packets older than this count as disconnected. |
| `GT7_RECORD_DIR` | unset | Record every outing as `<dir>/<timestamp>.jsonl.gz` (see below). |
| `GT7_RECORD_KEEP` | `20` | How many outing recordings to keep. |
| `GT7_WEB_PORT` | `8501` | The pit wall (`those-who-run web`). |
| `LOG_LEVEL` | `INFO` | |

## 🚩 Running

Container (amd64):

```sh
podman run --rm \
  -e GT7_PS5_IP=192.0.2.108 \
  -e DISCORD_BOT_TOKEN=... \
  -e DISCORD_VOICE_CHANNEL_ID=... \
  -p 33740:33740/udp -p 9850:9850 \
  -v ./data:/data \
  muldoon/those-who-run:0.4.0
```

From source:

```sh
make venv            # needs uv: .venv from uv.lock, with the dev and web extras
make voice           # downloads the Piper voice into ./voices, sha256-checked
GT7_PS5_IP=... DISCORD_BOT_TOKEN=... DISCORD_VOICE_CHANNEL_ID=... .venv/bin/those-who-run run
```

The console script is `those-who-run` and the Python package is
`those_who_run`. The old `gt7-race-engineer` names are gone.

### Audio check, replay and record

Test the Discord audio path without racing:

```sh
those-who-run say "Radio check"
```

Capture frames during a live session with `run --record session.jsonl`, or develop without a PS5 or Discord:

```sh
# capture a session from any machine on the LAN (uses discovery if no IP given)
those-who-run record session.jsonl --ps5-ip 192.0.2.108

# run the rules over it, printing callouts; optionally write WAVs to listen to
those-who-run replay session.jsonl --wav-out ./out
```

On the NUC the engineer records on its own: with `GT7_RECORD_DIR` set, every
outing (from leaving the menu to returning to it) becomes one
`<dir>/<YYYYMMDD-HHMMSS>.jsonl.gz` (UTC), about 20 MB an hour, and only the newest
`GT7_RECORD_KEEP` (20) files are kept. Cut a recording down to a test fixture
with `thin`: it keeps every frame where a phase, lap, lap time, position or car
count changed, the frames either side, and one frame per half second.

```sh
kubectl -n those-who-run cp those-who-run-xxxx:/data/recordings/20261016-193001.jsonl.gz ./outing.jsonl.gz
those-who-run thin outing.jsonl.gz tests/fixtures/real-pit-stop-2026-10-16.jsonl --start 120 --end 600
```

Recordings are one `RaceState` JSON object per line, version-tagged, and do not
depend on gt-telem's packet layout.

## Track detection

GT7 never says which track you are on. The engineer works it out from where
the car goes, using a table of 106 layouts (finish line, direction, lap
bounding box, optionally lap length; adapted from gt-telem and Bornhall's
gt7telemetry) and four independent facts:

1. **A finish line is close to where the car has been.** The grid, the pit
   lane and every lap boundary are within a kilometre of the layout's line.
   This separates the real track from unrelated layouts whose enormous boxes
   happen to contain the same coordinates.
2. **The path stays inside the box.** A layout is dropped the moment the car
   leaves its bounds. Family members that share a finish line (GP vs 24h,
   Indy vs full) fall out as you drive past the shorter one.
3. **The finish line is crossed, in the right direction.** Two witnesses:
   GT7's own lap counter (when it ticks, the car is on the line, whatever the
   table says) and the car's path cutting the table's segment, widened to span
   the track because the recorded segments are only a car's width. This is the
   only thing that tells a reverse layout from its twin. The lap counter wins:
   other layouts' lines lie all over a circuit (Fuji's pit exit runs through
   Tokyo East's line; a lap of Tokyo East cuts Suzuka's), so a path crossing
   counts only while racing and only until the lap counter has shown where the
   line is, and at a lap boundary a line much further away than the nearest
   one is another circuit's.
4. **A completed lap fits the layout.** Once the lap counter has closed a lap,
   the driven box is the lap's box and the distance is its length. A layout
   the lap fills poorly, or whose known length is off, is ruled out. This is
   what stops a track the table does not know from being mistaken for a
   neighbour whose line happens to sit nearby.

The verdict carries a confidence: `confirmed` (line crossed and a full lap
fits, nothing else left), `probable` (line crossed but no full lap yet, or a
single layout left), `ambiguous` (several still fit; no track is named unless
a line was crossed) or `none` (nothing fits: a new track, or one the table has
wrong). When the layouts still in the running all belong to one circuit (Fuji
and Fuji Short are identical in the table), the start brief says the circuit's
name. A race with a rolling start is probable before the lights and confirmed
at the end of lap 1; a flying lap from the pits is probable within a minute and
confirmed at the end of the lap; a one-lap race confirms at the flag. The
verdict never drops on a blip, but a layout that has been ruled out is
replaced, so a wrong early guess does not stick to the session.

The verdict is logged, stored with the session (`track_id` and
`track_confidence` in the index, a `track` block with the candidates in
`summary.json`), exported as `gt7_track_id` and `gt7_track_info`, and shown
by `/healthz`.

```sh
those-who-run tracks list                      # the table
those-who-run tracks detect session.jsonl      # how the decision evolved over a recording
those-who-run tracks detect data/sessions/<id> # same, from stored Parquet laps
those-who-run tracks backfill                  # fill in sessions recorded before detection existed
those-who-run tracks learn data/sessions/<id> --id 100001 --name "New Track"
                                               # a table row from a recorded lap, for tracks the table lacks
```

When GT7 adds a track, drive a lap, run `tracks learn` on the session and add
the printed row to `src/those_who_run/data/tracks.csv`. Learned rows use ids
from 100001 up, since GT7's own ids are not visible in telemetry. Sportsland
SUGO (100001) was added this way from its first lap on 2026-10-15, and Circuit
Gilles Villeneuve (100002) from a daily race on 2026-10-17.

## Cars

GT7 sends a car code, not a name. `src/those_who_run/data/cars.csv` maps codes
to maker and model (590 cars, from ddm999/gt7info, MIT-0); a car newer than the
table shows as "car <code>". Session summaries carry `car_name`.

```sh
those-who-run cars find rx vision   # codes and names matching every word
those-who-run cars name 3339        # Subaru BRZ Drift Car '17
```

## What is in the recordings

`those-who-run recordings` replays each outing recording in `GT7_RECORD_DIR`
(or the files and directories given) and prints one line per session: when it
started (local time, and how far into the file), how long it ran, track and kind, the result, car, best
lap, session kind and start, and how it ended (`flag`, `quit`, `restart`, or
`open` if the recording stops mid-session). Handy for matching a night's
drives to notes:

```sh
those-who-run recordings --last 5
#   19:31  +0:28   8.5 min  Sportsland SUGO · 5-lap race  🚩 Finished P3 of 20 in 8:36.182 ...
```

## Results channel

Set `DISCORD_RESULTS_CHANNEL_ID` to a text channel and the bot posts a card for
every session with at least one full lap: track and kind in the title
("Sportsland SUGO · 5-lap race"), the result ("🚩 Finished P3 of 20 in
8:14.302", "Retired on lap 2 of 3", "3 laps"), best lap with its lap number,
car and fuel used. Position only appears where the engineer would say it (a
field GT7 flags). Cards are queued and retried three times, so Discord never
holds up the engineer; `gt7_results_posts_total{result}` counts ok, failed and
skipped, and the index records `posted_at`. Unset, nothing is posted. With
`PITWALL_URL` set, each card's title links to its session on the pit wall
(`<PITWALL_URL>/?session=<id>`), and `--dry-run` prints that link.

The voice bot posts them, so it needs View Channel, Send Messages and Embed
Links on that channel. To post or re-post a stored session by hand:

```sh
those-who-run post 20261016-190000 --dry-run   # print the card
those-who-run post 20261016-190000             # send it
```

## Session kind

GT7 does not say what mode it is in either. The engineer sorts every session
by what telemetry does show (`src/those_who_run/sessionkind.py`):

| Kind | Telemetry |
|---|---|
| `lap_race` | a lap total and two or more cars |
| `solo_laps` | a lap total and one car |
| `timed_field` | no lap total and three or more cars: qualifying or a timed race, which GT7 reports the same way |
| `solo_timed` | no lap total and one car: time trial or practice. A ghost can add a second car; two cars only count as a field once you are not first |

It also records whether **fuel use** is on (the level has dropped while racing;
off after 20 s of driving without a drop) and GT7's **cars on track** flag,
which a whole group of sessions never set (a mode still to be named), and the
**start**: `grid` when the car is near standstill in the first 0.3 s of racing,
otherwise `rolling` in a lap race and `flying` in anything else (out of the
pits onto a timed lap). The kind is logged, stored with the session
(`session_kind`, `fuel_use` and `start_type` in the index, a `session_kind`
block in `summary.json`), exported as `gt7_session_info{kind,fuel_use,start}`
and shown by `/healthz`. Rules receive it through `on_session`, and it shapes
what is said:

- Grid slot, places gained and lost, and the finishing position are only
  spoken when we are sure other cars are racing for position: GT7 flags cars
  on track and the session has a field. Never in a time trial (where the ghost
  can count as a second car), and not in the races GT7 does not flag either,
  until we know what mode those are.
- Fuel calls need measured consumption, so a session with fuel use off is
  quiet about fuel already.
- Leaving a time trial, practice or solo run gets a short summary, since those
  never show a flag.

## Data

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
command that writes the store (`tracks backfill`, `post`, `rebuild-best`)
refuses with exit code 1 while it does. Use the pit wall, or stop the engineer
first. The engineer likewise refuses to start while one of those is running.
The pit wall only reads and never takes the lock.

A session's `best_lap_ms` is the best lap the results card and the pit wall
show: GT7's own best when there is one, which leaves out lap 1 from a grid
start; `fastest_lap_ms` in `summary.json` is the quickest complete lap of any
kind. Stores written by 0.4.0 or earlier counted that lap 1; correct them once
with:

```sh
those-who-run rebuild-best
```

## Pit wall

`those-who-run web` serves the pit wall, a Streamlit app over the session
store, on port 8501 (`--port` or `GT7_WEB_PORT`). Phase 1 (#33) shows what is
stored today:

- **Sessions:** newest first, each with its results card (title, result, best
  lap, car, fuel used) and the date in your browser's time zone. Filter by
  track, car, session kind and dates. A session still being driven is listed
  too, from the index.
- **Laps:** time, gap to the best lap, fuel used and left, position (only in a
  field GT7 flags, as on the card), top speed and flags: **pit** and **out** for
  the in-lap and out-lap the pit-stop detector stored (tyre-only stops
  included; sessions stored before it fall back to a rise in fuel), **partial**
  for the lap the session ended in. GT7 does not report track limits.
- **Lap compare:** speed, throttle, brake, gear and RPM of two laps over time
  from each lap's start, from the same session or another at the same track.
  Drag a chart to zoom. Distance replaces time once #15 lands.

Each session has its own link, `?session=<id>`. The pit wall only reads: the
index is opened read-only and no session data is written. One column, so it
works on a phone straight after a race.

Because the index is in WAL mode, a reader still needs to write SQLite's
shared-memory file, `index.sqlite-shm`, next to it, and needs `-wal` and `-shm`
to exist already if it cannot create them. SQLite removes both when the last
connection closes, so on a read-only mount (`:ro`, `readOnly: true`) the pit
wall can only open the index while the engineer is running. Mount the data
directory read-write for the pit wall; it still opens the index `mode=ro`
(see #35).

Streamlit is an optional extra, so the engineer's own install stays lean:

```sh
pip install -e ".[web]"          # make venv installs it too
GT7_DATA_DIR=./data those-who-run web        # http://localhost:8501
```

The image includes the extra (about 300 MB of Streamlit, pandas and pyarrow;
see #26), so the same image runs it with a different command, sharing the
data volume with the engineer:

```sh
podman run --rm -p 8501:8501 -v ./data:/data muldoon/those-who-run:0.4.0 web
```

It listens on all addresses and has no login: keep it on the LAN. The image's
health check is `those-who-run healthcheck`: it probes the engineer's `/healthz`
on `GT7_METRICS_PORT` for `run`, and the pit wall's `/_stcore/health` on
`GT7_WEB_PORT` (or `--port`) for `web`.

### Pit wall on the NUC

On the NUC the pit wall is at **http://pitwall.nuc.home.arpa** (LAN only, no
login). It's the Deployment `those-who-run-pitwall` in namespace
`those-who-run`, next to the engineer. It uses the same image and tag, with
`args: ["web"]`. The manifests are in
the deployment repo under
`manifests/those-who-run/` (a kustomize base and `overlays/local`), and
their layout follows [ADR 0001](docs/adr/0001-data-and-network.md):

- The data volume is mounted read-write at `/data`, so SQLite can create the
  index's `-shm` and `-wal` files while the engineer is stopped. It's mounted
  again with `subPath: sessions` at `/data/sessions`, read-only.
- It uses only the `those-who-run-env` ConfigMap: no Secret, no admin token.
- It has no hostPort. The only way in is a ClusterIP Service on 8501 and the
  Traefik Ingress `those-who-run-pitwall-ingress`.
- Probes are on `/_stcore/health`. Its limits (1 CPU, 768Mi) stay well under
  the engineer's request, so it can't starve the engineer during a race.
- It uses `RollingUpdate`. It takes no lock, so restarting it never touches the
  engineer, and the reverse holds too.

To deploy or upgrade, from a home-lab checkout:

```sh
# one tag for both Deployments: newTag under images: in base/kustomization.yaml
kubectl --context=my-cluster apply -k manifests/those-who-run/overlays/local
kubectl --context=my-cluster -n those-who-run rollout status deploy/those-who-run-pitwall

# check it
curl -s http://pitwall.nuc.home.arpa/_stcore/health    # ok
# (or -H 'Host: pitwall.nuc.home.arpa' http://192.0.2.216/... if the name doesn't resolve)
kubectl --context=my-cluster -n those-who-run exec deploy/those-who-run-pitwall -- \
  touch /data/sessions/x                               # fails: Read-only file system
```

The dashboard link lives in the deployment repo.

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
503, while any task is dead; a task that crashes is logged and restarted with
backoff. Telemetry and voice being down does not make it unhealthy: that is
normal with the PS5 off.

## Livery

The palette lives in `those_who_run/brand.py` and is the only place a colour
should come from. The results cards and the pit wall's theme and lap colours
read it.

| Name | Hex | Use |
|---|---|---|
| Advan red | `#D21F1B` | accent, embed colour, flags |
| Deep black | `#111111` | background |
| Carbon grey | `#333333` | panels, secondary |
| White | `#FFFFFF` | type |

Readouts are monospace. Times look like `1:41.023`, deltas like `+0.512`,
trackside glyphs are ⏱️ for times, ⛽ for fuel and 🚩 for the flag.

## Roadmap

[ROADMAP.md](ROADMAP.md) has the direction: principles, the streams that
run in parallel, their order and the open decisions. Details live in the
GitHub milestones and issues, each issue labelled with its stream:
https://github.com/those-who-run/those-who-run/milestones

## Development

```sh
make check           # what CI runs: ruff, mypy, pytest with the coverage floor
make lint test       # ruff + pytest only, quicker while iterating
make lock            # after changing dependencies in pyproject.toml: re-resolve uv.lock
make build           # podman build for linux/amd64, local only
```

### Releasing

The only way to publish an image is to push a `v*` tag; GitHub Actions does the
rest (`.github/workflows/release.yml`):

1. Set `__version__` in `src/those_who_run/__init__.py`, the version's one home
   (`pyproject.toml` reads it), and merge that.
2. Tag the merge commit and push the tag: `git tag v0.5.0 && git push origin v0.5.0`.
3. The workflow runs `make check`, fails unless the tag is `v` plus that version
   (`v0.5.0-rc1` matches `0.5.0rc1`), builds the image, runs `--version` and
   `web --help` in it, then pushes `muldoon/those-who-run:<tag without v>`.
   `latest` moves only for a final release, never for an `-rc`, alpha, beta or
   dev tag.

The workflow needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.

## What GT7 actually reports

Learned from recordings, and encoded in `state.py`:

- `current_lap` is -1 in menus, 0 at the track before the start, 1 and up while
  driving, and `total_laps + 1` once you take the flag. The results screen
  briefly replays the final frames afterwards; those are ignored.
- The position field (`race_start_pos` in gt-telem) updates live during a race.
- GT7 does not count lap 1 of a lap-count race towards its best lap: the grid
  sits ahead of the line, so lap 1 is short (57.1 s against 60 s laps at Suzuka
  East). The engineer follows GT7, so lap 2 has no delta and the summary's best
  lap is GT7's. Timed races and time trials do count lap 1, and so does a race
  with a rolling start, where lap 1 begins on the line (SUGO, 2026-10-15).
  The rule that holds everywhere: when GT7 posts lap 1 and keeps its best
  blank, it has left lap 1 out (a grid ahead of the line, qualifying's out
  lap), and so does the engineer.
- A timed race never reports FINISHED (there is no lap total to exceed). Its
  end is the first crossing after the clock runs out, and GT7 shows it the way
  it shows the flag: it takes the car over, throttle and brake at 0 while it
  coasts, then the results. The engineer calls the race finished after 3 s of
  that following a crossing, in a timed race with a field; drivers never coast
  hands-off that long at racing speed (1.8 s at most in every recorded race).
- After the results GT7 replays the race's last frames from the track screen,
  with the finished race's lap counter. They are not a new race.
- Laps within 50 ms of the best are "equal to best"; time-trial laps can repeat
  to a few milliseconds.
- GT7 has no pit flag; a stop is a run of camera cuts, each a single loading
  frame that keeps the lap counter (quitting and restarting reset it to 0, so
  they never look like this). **Entry:** the car jumps 120 to 330 m into the
  pit lane and the next frame reads the limiter, 60.0 km/h with no pedals,
  while GT7 drives it to the box (at Willow Springs the picture first freezes
  at the pit entry for five seconds). **Box:** one or two more cuts at rest,
  then fuel climbs about 10% a second to the amount asked for, and new tyres
  show as all four tyre temperatures dropping to 60.0 °C in one frame (tyre
  radius never changes). **Exit:** once the car moves off, a cut puts it at the
  pit exit at 80 km/h. Places drop while the car stands in the box (P5 to P11
  at Gilles Villeneuve). Seen at Suzuka East, Willow Springs (three stops) and
  Circuit Gilles Villeneuve, 2026-10-15 to 17; no race without a stop has such
  a cut. `src/those_who_run/pitstop.py` finds stops from the cuts, or from the
  car jumping between two packets when a cut frame is lost.
- The finish line can fall anywhere in a stop: in the entry cut (Suzuka East),
  in the exit cut (Willow Springs) or on a driving frame in the pit lane after
  the box (Gilles Villeneuve). A crossing in a cut arrives on the loading
  frame; the engine compares the next driving frame with the one before the
  cut, so the lap is still called. The engineer calls the lap the car entered
  the pits on the in-lap and the lap it left on the out-lap; neither counts
  towards fuel use, the fuel rule stays quiet on a crossing in the pits, and the
  session summary lists each stop (`pit_stops`: laps, time in the pit lane and
  at rest, fuel before and after, tyres, places) with the number of `stints`.
  Laps carry `pit` = `in` or `out` in the index.
- Time trials and practice report zero total laps and no cars on track. Lap
  times are still announced; the brief, final-lap, position and summary rules
  stay quiet. Qualifying reports zero total laps *with* cars on track, so it is
  briefed as a timed race.
- Timed races never report a flag (no lap total to exceed), so they get no
  summary yet. That needs a timed-race recording.
- GT7 sends no track id; see Track detection above.

## Known limits

- GT7 only exposes your own car. There are no gaps to the cars around you.
- Only the Discord send path is implemented. Spoken questions are a later phase.
- If the PS5 drops off the network, the engineer says so after
  `GT7_TELEMETRY_TIMEOUT_SECS` and again when packets return. The heartbeat
  that keeps GT7 streaming goes out every 2 s and survives send errors, so the
  stream resumes within a couple of seconds of the network. A lap crossed
  during the gap, and the one after, are left out of the fuel average. The PS5
  needs a fixed address (`GT7_PS5_IP`); a new DHCP lease ends the stream.

## Licence

GPL-3.0-only. gt-telem and Piper are GPL-3.0, which this project inherits.
The car table comes from ddm999/gt7info under MIT-0, and the track table from
gt-telem and Bornhall/gt7telemetry.
走り屋 is used here in its plain sense, people who run, and claims nothing else.
