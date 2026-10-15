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

No cloud. No subscription. No LLM. One small box on your LAN.

```
 ┌───────────────────────────────────────────────┐
 │  THOSE WHO RUN        走り屋        v0.1.0     │
 │  PS5 ──UDP 33740──▶ engineer ──Piper──▶ Discord │
 │  ⏱️  lap times   ⛽ fuel   🚩 final lap   P1▲   │
 └───────────────────────────────────────────────┘
```

## ⏱️ What it says (v1)

| Rule | When | Example |
|---|---|---|
| `start_brief` | two seconds into a race: track (if known), distance, grid slot | "Sportsland SUGO. Two laps. P ten of twenty." |
| `start_brief` | the detector names the track after the brief | "Nurburgring twenty-four hour." |
| `lap_time` | every completed lap | "Lap three. One forty-one point zero. One point five over best." |
| `lap_time` | a lap beats the best so far (own template and priority) | "Lap two. One thirty-nine point zero. New best by one point zero." |
| `fuel` | estimate crosses 10, 5, 3, 2, 1 laps | "Fuel. Three laps remaining." |
| `final_lap` | last lap of a lap-count race starts | "Final lap." |
| `position` | a place is gained or lost (races only), after a short settle | "Up to sixth." |
| `race_summary` | the chequered flag | "Chequered flag. Finished sixth. Best lap fifty-one point zero. Fuel used thirty-eight percent." |

Fuel is estimated from the last three laps' consumption and only announced
when it is shorter than the laps left in the race. A pit stop resets the
warnings. Every threshold and phrase is configurable, see `rules.example.yaml`.

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
| `GT7_METRICS_PORT` | `9850` | `/metrics` and `/healthz`. |
| `GT7_IDLE_DISCONNECT_SECS` | `600` | Leave the voice channel after this long in menus. |
| `GT7_TELEMETRY_TIMEOUT_SECS` | `3` | Packets older than this count as disconnected. |
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
  muldoon/those-who-run:0.2.1
```

From source:

```sh
make venv            # creates .venv and installs with dev extras
make voice           # downloads the Piper voice into ./voices
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
   only thing that tells a reverse layout from its twin.
4. **A completed lap fits the layout.** Once the lap counter has closed a lap,
   the driven box is the lap's box and the distance is its length. A layout
   the lap fills poorly, or whose known length is off, is ruled out. This is
   what stops a track the table does not know from being mistaken for a
   neighbour whose line happens to sit nearby.

The verdict carries a confidence: `confirmed` (line crossed and a full lap
fits, nothing else left), `probable` (line crossed but no full lap yet, or a
single layout left), `ambiguous` (several still fit; no track is named unless
a line was crossed) or `none` (nothing fits: a new track, or one the table has
wrong). A race with a rolling start is probable before the lights and confirmed
at the end of lap 1; a flying lap from the pits is probable within a minute and
confirmed at the end of the lap; a one-lap race confirms at the flag.

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
from 100001 up, since GT7's own ids are not visible in telemetry.

## Data

Every frame of every lap is kept, so the pit wall (milestone 2.0) can show
racing lines, traces and growth over time. Under `GT7_DATA_DIR`:

```
index.sqlite                      sessions and laps tables, for listing and filtering
sessions/<id>/lap-NN.parquet      60 Hz frames for that lap, ZSTD compressed
sessions/<id>/summary.json        human-readable summary
```

Frames are buffered in memory and written on a background thread when the lap
completes, so a crash loses at most the lap in progress and callouts are never
held up by disk. A partial lap at the end of a session is written with
`complete = 0`. Restarting from the pause menu closes the session and opens a
new one; quitting closes it; Ctrl-C closes whatever is open. Budget roughly
10 MB per hour of driving. Parquet is written and read with DuckDB; any
Parquet-aware tool can read the files.

## Metrics

Metric names keep the `gt7_` prefix because they describe GT7 telemetry:

`gt7_telemetry_packets_total`, `gt7_telemetry_connected`, `gt7_voice_connected`,
`gt7_in_race`, `gt7_callouts_total{rule}`, `gt7_callouts_dropped_total`,
`gt7_current_lap`, `gt7_total_laps`, `gt7_fuel_level`, `gt7_fuel_capacity`,
`gt7_fuel_laps_remaining`, `gt7_last_lap_seconds`, `gt7_best_lap_seconds`,
`gt7_speed_kph`, `gt7_speech_seconds`.

`GET /healthz` returns JSON with telemetry and voice connection state.

## Livery

The palette lives in `those_who_run/brand.py` and is the only place a colour
should come from. Nothing in this release draws a UI; the values are there for
the pit wall and any Discord embeds that follow.

| Name | Hex | Use |
|---|---|---|
| Advan red | `#D21F1B` | accent, embed colour, flags |
| Deep black | `#111111` | background |
| Carbon grey | `#333333` | panels, secondary |
| White | `#FFFFFF` | type |

Readouts are monospace. Times look like `1:41.023`, deltas like `+0.512`,
trackside glyphs are ⏱️ for times, ⛽ for fuel and 🚩 for the flag.

## Roadmap

Planned work is tracked as GitHub milestones, one per release:
https://github.com/those-who-run/those-who-run/milestones

## Development

```sh
make lint test       # ruff + pytest
make build           # podman build for linux/amd64
make release VERSION=0.2.1   # build and push muldoon/those-who-run:0.2.1
```

Tags matching `v*` are built and pushed to Docker Hub by GitHub Actions. The
workflow needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.

## What GT7 actually reports

Learned from recordings, and encoded in `state.py`:

- `current_lap` is -1 in menus, 0 at the track before the start, 1 and up while
  driving, and `total_laps + 1` once you take the flag. The results screen
  briefly replays the final frames afterwards; those are ignored.
- The position field (`race_start_pos` in gt-telem) updates live during a race.
- GT7 does not count lap 1 of a race towards its best lap, so the engineer
  tracks its own best as a fallback and lap 2 still gets a delta.
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

## Licence

GPL-3.0-only. gt-telem and Piper are GPL-3.0, which this project inherits.
走り屋 is used here in its plain sense, people who run, and claims nothing else.
