# The engineer

For the driver: what the engineer says and when, how its rules and phrases are set, how it knows the track, the car and the kind of session, what goes to the results channel, and how a session survives pauses and restarts. Back to the [docs index](README.md).

## What it says

| Rule | When | Example |
|---|---|---|
| `start_brief` | two seconds into a race: track (if known), distance, grid slot | "Sportsland SUGO. Two laps. P ten of twenty." |
| `start_brief` | the detector names the track after the brief, still on the first lap | "Nurburgring twenty-four hour." |
| `lap_time` | every completed lap | "Lap three. One forty-one point zero. One point five over best." |
| `lap_time` | the in-lap and out-lap of a pit stop: no delta, no coaching | "In lap, one thirty point one." / "Out lap, one forty-seven point three." |
| `lap_time` | a lap beats the best so far (own template and priority); in a lap-count race lap 2 is not measured against lap 1, the start | "Lap three. One thirty-nine point zero. New best by one point zero." |
| `fuel` | estimate crosses 10, 5, 3, 2, 1 laps | "Fuel. Three laps remaining." |
| `fuel` | the lap after this one cannot be completed, once per stint | "Pit this lap." |
| `final_lap` | last lap of a lap-count race starts | "Final lap." |
| `position` | a place is gained or lost (races only), after a 3 s settle and a 1 s hold, at most every 10 s, quiet for the first 15 s | "Up to sixth." |
| `temps` | a tyre stays over 120 °C for five seconds (corners already over join it in one phrase); water or oil high; cold tyres at the start | "Rear tyres hot." |
| `telemetry` | packets stop for 3 s mid-race or mid-pause, and when they return | "Lost telemetry." / "Telemetry back." |
| `race_summary` | the chequered flag, or the end of a timed race (kept for 30 s, so it waits behind the final lap time) | "Chequered flag. Finished sixth. Best lap fifty-three point one." |
| `race_summary` | leaving a time trial, practice or solo run, which have no flag (`quit_kinds`) | "Session done. Seven laps. Best lap forty-nine point seven." |

The pit lane is quiet from entry to exit. Only fuel calls are spoken there.
A lap call that falls due in the lane, where the lane crosses the line, is
held and spoken at the exit. A position call still waiting in the queue at
the entry is dropped: one call after the exit gives the net change. Each rule's
`pit_lane` setting (`speak`, `hold` or `drop`) chooses what happens to it.

The telemetry callout is the one thing not driven by frames: the live
watchdog (`GT7_TELEMETRY_TIMEOUT_SECS`, 3 s) raises it, so a quiet headset is
never ambiguous. Fuel is estimated from the last three laps' consumption and only announced
when it is shorter than the laps left in the race. The in-lap and out-lap of a
pit stop are left out of the average, and a stop starts a new stint with the
warnings armed again. Every threshold and phrase is configurable, see `rules.example.yaml`.

## The script

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

The flow, from the PS5 to the headset, is drawn on
[the architecture page](architecture.md#the-engineer). Each part:

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
wrong). When the layouts whose line was crossed all belong to one circuit and
their bounds cannot split them (Fuji and Fuji Short, Spa and Spa 24h, Monza,
Le Mans and Barcelona with and without their chicanes are identical in the
table), the verdict is the circuit: `probable`, named "Circuit de
Spa-Francorchamps" in the brief, on the card and on the pit wall. A race with a
rolling start is probable before the lights and confirmed at the end of lap 1;
a flying lap from the pits is probable within a minute and confirmed at the end
of the lap; a one-lap race confirms at the flag. The
verdict never drops on a blip, but a layout that has been ruled out is
replaced, so a wrong early guess does not stick to the session. A pit stop's
loading cut-scene keeps the lap counter, and the verdict with it; a quit, a
restart or a new event loads at lap 0 and starts over.

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

## Sessions

A pause is not driving time. `summary.json` and the index carry
`driving_ms`, `paused_ms` and `ended_paused` next to the wall-clock
`started_at` and `ended_at`, and the pit wall's session length is `driving_ms`.
A pause of any length keeps the session, whether GT7 sends paused frames or
the frozen stream it sends from the pause menu (identical frames with the car
moving). Losing the feed during a pause (the PS5 switched off or put to rest)
or stopping the engineer ends the session paused: it ends when the pause
began, and its card says "Paused on lap 2 of 5, P3". `GT7_PAUSE_LIMIT_SECS` ends
a pause that long the same way; it is off by default. Outing recordings keep a
pause at one frame a second.

When the engineer starts part way through a session (an upgrade, a crash, a
node reboot: the first frame is a race frame past lap 1), it says "Back with
you. Lap seven. P one." instead of a start brief, makes no cold-tyre call, does
not measure fuel on the lap it joined, and names no track until the finish line
is seen. The session's `joined_on_lap` is set in `summary.json` and the index,
and the card says "Joined on lap 7".

A restart in the middle of a race does not split it. A session the
engineer's shutdown ended is marked `engineer_shutdown` in `summary.json` and
the index, and its results card is held. If the engineer joins a session part
way within `GT7_CONTINUE_WINDOW_SECS` (10 minutes by default), in the same car,
kind (race or not, the lap total) and field size, on the old session's last lap
or later, it continues that session. It keeps the same id, carries the track
over (so it is known at once), appends the laps and records the gap in `gaps`
(`from`, `to`, `lap`, `reason: "engineer restart"`). The lap the gap falls in
is stored as one incomplete lap with the frames from both sides, and keeps
GT7's time for it. The one card goes at the real end and says "Engineer
restarted on lap 7"; the pit wall flags that lap `restart`. A held card that is
never continued goes once the window has passed, or when another session
starts, and says "Engineer stopped on lap 7". Anything that doesn't match is a
new session, as before.

A session's `best_lap_ms` is the best lap the results card and the pit wall
show: GT7's own best when there is one, which leaves out lap 1 from a grid
start; `fastest_lap_ms` in `summary.json` is the quickest complete lap of any
kind. Stores written by 0.4.0 or earlier counted that lap 1; correct them once
with:

```sh
those-who-run rebuild-best
```
