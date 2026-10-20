# Setting it up

For anyone setting up the engineer: what it needs, every environment variable, running it from the image or from source, the audio check, and every command. Back to the [docs index](README.md).

## Requirements

- A PS5 running GT7 with **Settings > Network > Telemetry** enabled, on the same
  LAN as the host, ideally with a DHCP reservation.
- A Discord server with a voice channel, and a bot application with the
  **Connect** and **Speak** permissions in that channel. No privileged intents.
- The PS5 signed in to Discord and joined to the same voice channel.
- Linux host with `ffmpeg` and `libopus`, or the container image.
- To build or work on the web app (`web/`): Node, the version in `web/.node-version`.
  Node is never needed to run anything: the image carries the built app.

## Configuration

Environment variables. The `GT7_` prefix names the game, not the project, and
is unchanged by the rebrand.

| Variable | Default | Purpose |
|---|---|---|
| `GT7_PS5_IP` | required for `run` | PS5 address. Optional for `record`, which takes `--ps5-ip` or finds the PS5 by broadcast discovery when neither is set. |
| `DISCORD_BOT_TOKEN` | required | Bot token. |
| `DISCORD_VOICE_CHANNEL_ID` | required | Voice channel the PS5 joins. |
| `GT7_RULES_FILE` | built-in defaults | YAML overriding any value in `rules.example.yaml`. |
| `GT7_DATA_DIR` | `./data` | Lap and session output. |
| `GT7_VOICE_MODEL` | `voices/en_GB-alba-medium.onnx` | Piper voice. |
| `GT7_CACHE_DIR` | `$XDG_CACHE_HOME/those-who-run`, else `~/.cache/those-who-run` | Synthesised sentence clips, reused across laps. Must be owned by the user running the engineer, and must not be inside `GT7_DATA_DIR` (the pit wall can write there). |
| `GT7_CACHE_MAX_MB` | `100` | Size cap for the speech cache; the least recently used clips go first. |
| `GT7_METRICS_PORT` | `9850` | `/metrics`, `/healthz` and the read-only `/api/v1` (`/api/v1/status`). |
| `GT7_CONTROL_PORT` | unset | The control API's port (`9851` in ADR 0001). Unset, nothing listens there. |
| `GT7_BIND_ADDRESS` | `0.0.0.0` | Address both engineer ports listen on. |
| `DISCORD_RESULTS_CHANNEL_ID` | unset | Text channel for results cards. Unset turns them off. |
| `PITWALL_URL` | unset | Pit wall base URL, e.g. `https://pitwall.<your-domain>`. Card titles link to the session there. Unset, no link. |
| `GT7_IDLE_DISCONNECT_SECS` | `600` | Leave the voice channel after this long in menus or with no telemetry. |
| `GT7_TELEMETRY_TIMEOUT_SECS` | `3` | Packets older than this count as disconnected. |
| `GT7_PAUSE_LIMIT_SECS` | `0` (no limit) | End a session that has been paused this long, as ended paused. By default a pause of any length keeps the session, as GT7 keeps the race; losing the feed during a pause (the PS5 switched off or put to rest) ends it. |
| `GT7_CONTINUE_WINDOW_SECS` | `600` | After the engineer restarts mid-race, a session joined part way within this long of the one the shutdown ended (same car and kind) continues it. That session's results card waits this long for it. `0` never continues. |
| `GT7_RECORD_DIR` | unset | Record every outing as `<dir>/<timestamp>.jsonl.gz` (see [Recordings](telemetry.md#recordings)). |
| `GT7_RECORD_KEEP` | `20` | How many outing recordings to keep. |
| `GT7_ARCHIVE_DIR` | `~/.cache/those-who-run/outings` | The outing archive's working copy: `recordings archive` fills it, `make archive-push` and `archive-pull` mirror it (see [The archive](telemetry.md#the-archive)). |
| `GT7_PITWALL_PORT` | `9852` | The pit wall's data API and web app (`those-who-run pitwall`). |
| `GT7_PITWALL_STATIC` | unset | The built web app `pitwall` serves, as `--static` (which wins). The pitwall image sets `/app/web`. |
| `GT7_ENGINEER_URL` | `http://those-who-run:9850` | Where `pitwall` reaches the engineer's read-only port, for `/api/engine/status` and `/api/engine/dash`. |
| `GT7_ENGINEER_CONTROL_URL` | `http://those-who-run:9851` | Where `pitwall` reaches the engineer's control port, for `/api/engine/control/*`. |
| `LOG_LEVEL` | `INFO` | |

## Running

Container (amd64): the command is in the README's
[quick start](../README.md#quick-start), with the current release's tag. The
image's entry point is `those-who-run`, so any command below runs in it by
naming the command after the image (the default is `run`).

From source:

```sh
make venv            # needs uv: .venv from uv.lock, with the dev and engineer extras
make voice           # downloads the Piper voice into ./voices, sha256-checked
GT7_PS5_IP=... DISCORD_BOT_TOKEN=... DISCORD_VOICE_CHANNEL_ID=... .venv/bin/those-who-run run
```

The console script is `those-who-run` and the Python package is
`those_who_run`. The old `gt7-race-engineer` names are gone.

## Audio check

Test the Discord audio path without racing:

```sh
those-who-run say "Radio check"
```

## Commands

Every command of the `those-who-run` console script, one line each.
`those-who-run <command> --help` lists its options.

| Command | What it does | Explained in |
|---|---|---|
| `run` | Live: PS5 telemetry in, Discord voice out. | [Running](#running) |
| `say` | Joins the voice channel, speaks a phrase, leaves (audio test). | [Audio check](#audio-check) |
| `replay` | Runs the rules over a recording, no PS5 or Discord needed. | [Recordings](telemetry.md#recordings) |
| `record` | Captures live telemetry to a JSONL file for later replay. | [Recordings](telemetry.md#recordings) |
| `thin` | Cuts a recording down to a test fixture. | [Recordings](telemetry.md#recordings), [Fixtures](development.md#fixtures) |
| `tracks list` | Prints the track table. | [Track detection](engineer.md#track-detection) |
| `tracks detect` | Runs the detector over a recording or a stored session. | [Track detection](engineer.md#track-detection) |
| `tracks backfill` | Detects the track for stored sessions and updates the index. | [Track detection](engineer.md#track-detection) |
| `tracks learn` | Derives a track table row from a recorded lap. | [Track detection](engineer.md#track-detection) |
| `cars list` | Prints the car table. | [Cars](engineer.md#cars) |
| `cars find` | Cars whose maker or model contains every word given. | [Cars](engineer.md#cars) |
| `cars name` | The name for one car code. | [Cars](engineer.md#cars) |
| `recordings` | One line per session in each outing recording; `recordings archive` archives outings or lists the archive. | [What is in the recordings](telemetry.md#what-is-in-the-recordings), [The archive](telemetry.md#the-archive) |
| `post` | Posts a stored session's results card to `DISCORD_RESULTS_CHANNEL_ID`. | [Results channel](engineer.md#results-channel) |
| `rebuild-best` | Recomputes each stored session's best lap from its summary (stores from 0.4.0). | [Sessions](engineer.md#sessions) |
| `pitwall` | The pit wall's read-only data API over `GT7_DATA_DIR`, and the web app with `--static`. | [The pit wall](pitwall.md#running-it) |
| `healthcheck` | Exits 0 when the engineer or pit wall in this container answers. | [Running it](pitwall.md#running-it), [Metrics](operations.md#metrics) |
