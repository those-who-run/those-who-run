# Telemetry and recordings

For anyone working on what the engineer reads: what GT7 actually reports, how outings are recorded, replayed, cut down and archived, and the known limits. Back to the [docs index](README.md).

## Recordings

Capture frames during a live session with `run --record session.jsonl`, or develop without a PS5 or Discord:

```sh
# capture a session from any machine on the LAN (uses discovery if no IP given)
those-who-run record session.jsonl --ps5-ip 192.0.2.108

# run the rules over it, printing callouts; optionally write WAVs to listen to
those-who-run replay session.jsonl --wav-out ./out

# keep the sessions it finds, to look at them in the pit wall
those-who-run replay session.jsonl --store ./replayed
GT7_DATA_DIR=./replayed those-who-run pitwall --static web/dist
```

A replay never writes to `GT7_DATA_DIR`: the sessions it finds go to a
temporary store that is thrown away afterwards, or to `--store DIR`. So the pit
wall and the results history only ever show real drives.

Deployed, the engineer records on its own: with `GT7_RECORD_DIR` set, every
outing (from leaving the menu to returning to it) becomes one
`<dir>/<YYYYMMDD-HHMMSS>.jsonl.gz` (UTC), about 20 MB an hour, and only the newest
`GT7_RECORD_KEEP` (20) files are kept. Cut a recording down to a test fixture
with `thin`: it keeps every frame where a phase, lap, lap time, position or car
count changed, the frames either side, and one frame per half second. It
writes gzip unless given `--plain`, and adds `.gz` to the name if it is missing.

```sh
kubectl -n those-who-run cp those-who-run-xxxx:/data/recordings/20261016-193001.jsonl.gz ./outing.jsonl.gz
those-who-run thin outing.jsonl.gz tests/fixtures/real-pit-stop-2026-10-16.jsonl.gz --start 120 --end 600
```

### The archive

Outings that specs and tests rely on go in the archive before the engineer
prunes them ([ADR 0002](docs/adr/0002-outing-archive.md)): the `outings` release
of [those-who-run/outings](https://github.com/those-who-run/outings), mirrored in `GT7_ARCHIVE_DIR` (default
`~/.cache/those-who-run/outings`).

```sh
those-who-run recordings archive 20261017-162118 --note "Gilles 12-lap race, one stop" --issue 15
those-who-run recordings archive          # list it: id, track, car, kind, issues, note
make archive-push                         # upload to the release (needs gh)
make archive-pull                         # download what is missing
```

Recordings are one `RaceState` JSON object per line, version-tagged, and do not
depend on gt-telem's packet layout.

### What is in the recordings

`those-who-run recordings` replays each outing recording in `GT7_RECORD_DIR`
(or the files and directories given) and prints one line per session: when it
started (local time, and how far into the file), how long it was driven (pauses
left out), track and kind, the result, car, best lap, session kind and start, and
how it ended (`flag`, `quit`, `restart`, `paused` if the recording stops in a
pause, or `open` if it stops mid-session). Handy for matching a night's
drives to notes:

```sh
those-who-run recordings --last 5
#   19:31  +0:28   8.5 min  Sportsland SUGO · 5-lap race  🚩 Finished P3 of 20 in 8:36.182 ...
```

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
- A race replay starts like a race (track screen, then lap 1) but never sets
  the cars-on-track flag, while the fuel drains as it did in the race. A
  session that starts unflagged is held for up to 3 s: a fuel drop makes it a
  replay, ignored until the next start (no callouts, no session, no card, one
  log line); the flag makes it a drive, and its frames go through as if never
  held.
- GT7's attract-mode demo race, which plays by itself when the PS5 sits idle on
  the menu, is unflagged too, with the fuel flat. A drive always loads its track
  (menu, loading, track screen, loading, track screen, lap 1); a demo goes from
  the menu to the track with no loading screen. So when 3 s pass without the
  flag or a fuel drop, or the start ends or pauses first, an unflagged start
  with no loading screen since the last menu is a demo, ignored like a replay.
  With no menu seen (the engineer started mid-demo) it is a demo if GT7 reports
  two or more cars with the flag off. Anything else is a drive. The unflagged
  races of 2026-10-15 (#63) were demos.

## Known limits

- GT7 only exposes your own car. There are no gaps to the cars around you.
- Only the Discord send path is implemented. Spoken questions are a later phase.
- If the PS5 drops off the network, the engineer says so after
  `GT7_TELEMETRY_TIMEOUT_SECS` and again when packets return. The heartbeat
  that keeps GT7 streaming goes out every 2 s and survives send errors, so the
  stream resumes within a couple of seconds of the network. A lap crossed
  during the gap, and the one after, are left out of the fuel average. The PS5
  needs a fixed address (`GT7_PS5_IP`); a new DHCP lease ends the stream.
