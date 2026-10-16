"""Command line entry point: run, say, replay, record, thin, tracks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from those_who_run import __version__, brand
from those_who_run.callouts import CalloutQueue
from those_who_run.config import ConfigError, Settings, load_rules_config
from those_who_run.engine import Engine
from those_who_run.metrics import HealthServer, Metrics
from those_who_run.rules import build_rules
from those_who_run.state import Phase, RaceState
from those_who_run.store import SessionStore

log = logging.getLogger("those_who_run")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="those-who-run", description=f"{brand.NAME} {brand.KANJI}: {brand.TAGLINE}."
    )
    p.add_argument("--version", action="version", version=brand.banner(__version__))
    sub = p.add_subparsers(dest="command", required=True)

    rn = sub.add_parser("run", help="live: PS5 telemetry in, Discord voice out")
    rn.add_argument(
        "--record", type=Path, help="also append every telemetry frame to this JSONL file"
    )

    sy = sub.add_parser("say", help="join the voice channel, speak a phrase, leave (audio test)")
    sy.add_argument("text", nargs="?", default="Radio check. Race engineer online.")

    rp = sub.add_parser("replay", help="run the rules over a recording, no PS5 or Discord needed")
    rp.add_argument("recording", type=Path)
    rp.add_argument("--wav-out", type=Path, help="also synthesise each callout into this directory")
    rp.add_argument("--realtime", action="store_true", help="sleep to match the recording's timing")

    rc = sub.add_parser("record", help="capture live telemetry to a JSONL file for later replay")
    rc.add_argument("output", type=Path)
    rc.add_argument("--ps5-ip", help="override GT7_PS5_IP; omit both to use broadcast discovery")
    rc.add_argument(
        "--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)"
    )

    th = sub.add_parser("thin", help="cut a recording down to a test fixture")
    th.add_argument("source", type=Path, help="a .jsonl or .jsonl.gz recording")
    th.add_argument("output", type=Path)
    th.add_argument("--start", type=float, help="seconds from the first frame")
    th.add_argument("--end", type=float, help="seconds from the first frame")
    th.add_argument(
        "--every", type=float, default=0.5, help="keep one frame per this many seconds (0.5)"
    )

    tr = sub.add_parser("tracks", help="track detection: list the table, test it, backfill data")
    trs = tr.add_subparsers(dest="tracks_command", required=True)
    trs.add_parser("list", help="print the track table")
    td = trs.add_parser("detect", help="run the detector over a recording or a stored session")
    td.add_argument("source", type=Path, help="a .jsonl recording or a sessions/<id> directory")
    tb = trs.add_parser(
        "backfill", help="detect the track for stored sessions and update the index"
    )
    tb.add_argument("--force", action="store_true", help="re-run even for confirmed sessions")
    tl = trs.add_parser(
        "learn", help="derive a table row (finish line, direction, box) from a recorded lap"
    )
    tl.add_argument("source", type=Path, help="a .jsonl recording or a sessions/<id> directory")
    tl.add_argument("--id", type=int, default=0, help="track id for the printed CSV row")
    tl.add_argument("--name", default="NAME", help="track name for the printed CSV row")

    cr = sub.add_parser("cars", help="GT7 car names by car code")
    crs = cr.add_subparsers(dest="cars_command", required=True)
    crs.add_parser("list", help="print the car table")
    cf = crs.add_parser("find", help="cars whose maker or model contains every word given")
    cf.add_argument("text", nargs="+")
    cn = crs.add_parser("name", help="the name for one car code")
    cn.add_argument("code", type=int)

    rl = sub.add_parser(
        "recordings", help="one line per session in each outing recording (GT7_RECORD_DIR)"
    )
    rl.add_argument("paths", nargs="*", type=Path, help="recordings or directories")
    rl.add_argument("--last", type=int, default=0, help="only the newest N recordings")

    po = sub.add_parser(
        "post", help="post a stored session's results card to DISCORD_RESULTS_CHANNEL_ID"
    )
    po.add_argument("session_id", help="a directory name under GT7_DATA_DIR/sessions")
    po.add_argument("--dry-run", action="store_true", help="print the card, post nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        if args.command == "run":
            return asyncio.run(run_live(settings, record=args.record))
        if args.command == "say":
            return asyncio.run(run_say(settings, args.text))
        if args.command == "replay":
            return asyncio.run(run_replay(settings, args.recording, args.wav_out, args.realtime))
        if args.command == "record":
            return asyncio.run(run_record(settings, args.output, args.ps5_ip, args.seconds))
        if args.command == "thin":
            return run_thin(args.source, args.output, args.start, args.end, args.every)
        if args.command == "tracks":
            return run_tracks(settings, args)
        if args.command == "cars":
            return run_cars(args)
        if args.command == "recordings":
            return run_recordings(settings, args.paths, args.last)
        if args.command == "post":
            return asyncio.run(run_post(settings, args.session_id, args.dry_run))
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
    except KeyboardInterrupt:
        return 130
    return 1


async def run_post(settings: Settings, session_id: str, dry_run: bool) -> int:
    import json

    import discord

    from those_who_run.results import ResultsPoster, build_card

    path = settings.data_dir / "sessions" / session_id / "summary.json"
    if not path.exists():
        raise ConfigError(f"{path}: no such session summary")
    summary = json.loads(path.read_text(encoding="utf-8"))
    card = build_card(summary)
    if card is None:
        print("no full lap: nothing to post")
        return 1
    print(card.title)
    print(card.description)
    for name, value in card.fields:
        print(f"  {name}: {value}")
    if dry_run:
        return 0
    if not settings.discord_token or not settings.results_channel_id:
        raise ConfigError("posting needs DISCORD_BOT_TOKEN and DISCORD_RESULTS_CHANNEL_ID")
    client = discord.Client(intents=discord.Intents.none())
    await client.login(settings.discord_token)  # HTTP only: no gateway needed to post
    try:
        store = SessionStore(settings.data_dir)
        poster = ResultsPoster(client, settings.results_channel_id, on_posted=store.mark_posted)
        ok = await poster.post(session_id, card)
        store.close()
    finally:
        await client.close()
    return 0 if ok else 1


def run_recordings(settings: Settings, paths: list[Path], last: int) -> int:
    from those_who_run.recordtools import list_recordings, summarise_recording

    if not paths:
        if settings.record_dir is None:
            raise ConfigError("give recordings or a directory, or set GT7_RECORD_DIR")
        paths = [settings.record_dir]
    files: list[Path] = []
    for p in paths:
        files.extend(list_recordings(p) if p.is_dir() else [p])
    if last:
        files = files[-last:]
    for f in files:
        sessions, complete = summarise_recording(f)
        print(f.name + ("" if complete else "  (still being written)"))
        for s in sessions:
            print("   " + s.line())
        if not sessions:
            print("   no session")
    return 0


def run_cars(args: argparse.Namespace) -> int:
    from those_who_run.cars import car_name, find_cars, load_cars

    if args.cars_command == "name":
        print(car_name(args.code) or "none")
        return 0
    cars = load_cars() if args.cars_command == "list" else find_cars(" ".join(args.text))
    for c in cars:
        print(f"{c.id:5d}  {c.full_name}")
    return 0 if cars else 1


def run_tracks(settings: Settings, args: argparse.Namespace) -> int:
    from those_who_run.tracks import load_tracks
    from those_who_run.tracktools import backfill, detect_recording, detect_session, learn_track

    if args.tracks_command == "list":
        for t in load_tracks():
            geo = (
                f"{t.direction}  box {t.box[2] - t.box[0]:.0f} x {t.box[3] - t.box[1]:.0f} m"
                if t.box
                else "no geometry"
            )
            print(f"{t.id:5d}  {t.name:55s} {geo}")
        return 0
    if args.tracks_command == "detect":
        src: Path = args.source
        if src.is_dir():
            match, steps = detect_session(src)
        elif src.suffix == ".jsonl":
            match, steps = detect_recording(src)
        else:
            raise ConfigError(f"{src}: expected a .jsonl recording or a session directory")
        for st in steps:
            cands = ", ".join(
                f"{c.track.name} ({c.fit:.2f}{', line' if c.line_crossed else ''})"
                for c in st.match.candidates[:4]
            )
            m = st.match
            head = f"t={st.t:9.1f} lap {st.lap:2d}  {m.confidence:9s} {m.name}"
            print(f"{head}: {m.evidence}  [{cands}]")
        print(f"\nresult: {match.confidence} {match.name} ({match.track_id})")
        return 0 if match.confidence in ("confirmed", "probable") else 1
    if args.tracks_command == "learn":
        learned = learn_track(args.source)
        print(f"lap length {learned.lap_length_m:.0f} m over {learned.laps_used} completed lap(s)")
        print(f"finish line at {learned.line[0][0]:.0f},{learned.line[0][1]:.0f} .. ", end="")
        print(f"{learned.line[1][0]:.0f},{learned.line[1][1]:.0f}  direction {learned.direction}")
        print(f"box {' '.join(f'{v:.0f}' for v in learned.box)}")
        print("nearest existing lines:", learned.nearest)
        print("\ncsv row:\n" + learned.csv_row(args.id, args.name))
        return 0
    if args.tracks_command == "backfill":
        results = backfill(settings.data_dir, force=args.force)
        for r in results:
            flag = "updated" if r.updated else "skipped"
            print(
                f"{r.session_id}  {flag:8s} {r.after.confidence:9s} {r.after.name!s:40s} "
                f"(was {r.before[0]} {r.before[1] or '-'})  {r.note}"
            )
        print(f"\n{sum(r.updated for r in results)} of {len(results)} sessions updated")
        return 0
    return 1


async def run_replay(
    settings: Settings, recording: Path, wav_out: Path | None, realtime: bool
) -> int:
    from those_who_run.audio.player import ConsolePlayer, WavDirPlayer
    from those_who_run.replay import read_recording, replay, summarise

    rules_cfg = load_rules_config(settings.rules_file)
    queue = CalloutQueue(max_age=None)
    engine = Engine(build_rules(rules_cfg["rules"]), queue, SessionStore(settings.data_dir))
    if wav_out is not None:
        from those_who_run.speech import PiperSpeech

        speech = PiperSpeech(settings.voice_model, wav_out / ".cache", rules_cfg["voice"])
        player: ConsolePlayer = WavDirPlayer(speech, wav_out)
    else:
        player = ConsolePlayer()
    spoken = await replay(read_recording(recording), engine, player, realtime=realtime)
    log.info("replay summary: %s", summarise(spoken, queue))
    return 0


def run_thin(
    source: Path, output: Path, start: float | None, end: float | None, every: float
) -> int:
    from those_who_run.replay import read_recording, thin, write_recording

    frames = list(read_recording(source))
    kept = write_recording(output, thin(frames, every=every, start=start, end=end))
    print(f"{kept} of {len(frames)} frames kept in {output}")
    return 0


async def run_record(settings: Settings, output: Path, ps5_ip: str | None, seconds: float) -> int:
    from those_who_run.replay import RecordingWriter
    from those_who_run.telemetry import LiveTelemetry

    ip = ps5_ip or settings.ps5_ip
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(ip, queue, loop, discover=ip is None)
    writer = RecordingWriter(output)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    telem.start()
    deadline = time.monotonic() + seconds if seconds > 0 else None
    log.info("recording to %s (Ctrl-C to stop)", output)
    try:
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            try:
                state = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            writer.write(state)
    finally:
        writer.close()
        await telem.stop()
        log.info("wrote %d states to %s", writer.count, output)
    return 0


async def run_say(settings: Settings, text: str) -> int:
    """Audio path test: no telemetry involved."""
    from those_who_run.audio.discord_player import DiscordPlayer
    from those_who_run.callouts import Callout
    from those_who_run.speech import PiperSpeech

    if not settings.discord_token or not settings.discord_channel_id:
        raise ConfigError("DISCORD_BOT_TOKEN and DISCORD_VOICE_CHANNEL_ID are required")
    rules_cfg = load_rules_config(settings.rules_file)
    speech = PiperSpeech(settings.voice_model, Path("/tmp/those-who-run/cache"), rules_cfg["voice"])
    player = DiscordPlayer(settings.discord_token, settings.discord_channel_id, speech)
    await player.start()
    try:
        await player.on_phase(Phase.AT_TRACK, time.monotonic())
        if not player.connected:
            log.error("could not join the voice channel, see errors above")
            return 1
        await player.play(Callout(text=text, priority=0, rule="say", created_at=time.monotonic()))
        await asyncio.sleep(0.5)
    finally:
        await player.close()
    return 0


async def run_live(settings: Settings, record: Path | None = None) -> int:
    from those_who_run.audio.discord_player import DiscordPlayer
    from those_who_run.replay import OutingRecorder, RecordingWriter
    from those_who_run.rules.telemetry import TelemetryVoice
    from those_who_run.speech import PiperSpeech
    from those_who_run.telemetry import LiveTelemetry

    settings.require_live()
    assert settings.ps5_ip and settings.discord_token and settings.discord_channel_id
    rules_cfg = load_rules_config(settings.rules_file)
    rules = build_rules(rules_cfg["rules"])
    metrics = Metrics()
    queue = CalloutQueue(max_age=float(rules_cfg["queue"]["max_age_seconds"]))
    recorder = SessionStore(settings.data_dir)
    engine = Engine(rules, queue, recorder, metrics)
    speech = PiperSpeech(
        settings.voice_model,
        Path("/tmp/those-who-run/cache"),
        rules_cfg["voice"],
        on_duration=metrics.speech_seconds.observe,
    )
    player = DiscordPlayer(
        settings.discord_token,
        settings.discord_channel_id,
        speech,
        idle_disconnect_secs=settings.idle_disconnect_secs,
        on_voice_state=lambda up: metrics.voice_connected.set(1 if up else 0),
    )
    loop = asyncio.get_running_loop()
    states: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(settings.ps5_ip, states, loop)

    def health() -> dict:
        return {
            "ok": True,
            "telemetry_connected": telem.connected(settings.telemetry_timeout_secs),
            "voice_connected": player.connected,
            "packets": telem.packets,
            "races_started": engine.races_started,
            "queue": len(queue),
            "session": engine.kind.record(),
            "track": None
            if engine.track is None
            else {
                "id": engine.track.track_id,
                "name": engine.track.name,
                "confidence": engine.track.confidence,
            },
        }

    poster = None
    if settings.results_channel_id:
        from those_who_run.results import ResultsPoster

        poster = ResultsPoster(
            player.client,
            settings.results_channel_id,
            on_posted=recorder.mark_posted,
            on_result=lambda r: metrics.results_posts_total.labels(r).inc(),
        )
        recorder.on_end = poster.submit
        log.info("results cards go to channel %s", settings.results_channel_id)

    http = HealthServer(settings.metrics_port, metrics, health)
    http.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    writer: RecordingWriter | OutingRecorder | None = None
    if record is not None:
        writer = RecordingWriter(record)
        log.info("recording telemetry frames to %s", record)
    elif settings.record_dir is not None:
        writer = OutingRecorder(settings.record_dir, settings.record_keep)
        log.info("recording outings to %s, keeping %d", settings.record_dir, settings.record_keep)

    log.info("%s starting", brand.banner(__version__))
    # Pre-warm the voice so the first callout is not late.
    await loop.run_in_executor(None, speech.synthesize, "Race engineer online.")
    await player.start()
    telem.start()

    async def ingest() -> None:
        while True:
            state = await states.get()
            if writer is not None:
                writer.write(state)
            engine.process(state)
            await player.on_phase(state.phase, state.t)

    async def speak() -> None:
        while True:
            c = queue.pop(time.monotonic())
            if c is None:
                await asyncio.sleep(0.05)
                continue
            await player.play(c)

    async def watchdog() -> None:
        was: bool | None = None
        voice = TelemetryVoice(rules_cfg["rules"].get("telemetry"))
        log.info("telemetry: waiting for packets from %s", settings.ps5_ip)
        while True:
            now_connected = telem.connected(settings.telemetry_timeout_secs)
            metrics.telemetry_connected.set(1 if now_connected else 0)
            if now_connected != was and (was is not None or now_connected):
                log.info("telemetry %s", "connected" if now_connected else "lost")
            was = now_connected
            for c in voice.observe(now_connected, engine.prev, time.monotonic()):
                queue.push(c)
                metrics.callouts_total.labels(c.rule).inc()
                log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
            await asyncio.sleep(1)

    tasks = [
        asyncio.create_task(ingest(), name="ingest"),
        asyncio.create_task(speak(), name="speak"),
        asyncio.create_task(watchdog(), name="watchdog"),
    ]
    if poster is not None:
        tasks.append(asyncio.create_task(poster.run(), name="results"))
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await player.close()
        await telem.stop()
        http.stop()
        recorder.on_end = None  # the loop is going: no card for a session cut short here
        if recorder.session is not None and engine.prev is not None:
            log.info("closing session %s", recorder.session.session_id)
            recorder.end_session(engine.prev)
        recorder.close()
        if writer is not None:
            writer.close()
            log.info("recorded %d frames to %s", writer.count, record or settings.record_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
