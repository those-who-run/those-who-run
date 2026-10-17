"""Command line entry point: run, say, replay, record, thin, tracks, web, healthcheck."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from those_who_run import __version__, brand
from those_who_run.callouts import CalloutQueue
from those_who_run.config import ConfigError, Settings, load_rules_config
from those_who_run.engine import Engine
from those_who_run.metrics import HealthServer, Metrics
from those_who_run.rules import build_rules
from those_who_run.state import RaceState
from those_who_run.store import SessionStore, StoreBusy
from those_who_run.supervise import Supervisor

if TYPE_CHECKING:
    from those_who_run.audio.player import Player

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
    rp.add_argument(
        "--store",
        type=Path,
        help="keep the sessions found in this directory (default: a temporary one, thrown away;"
        " never GT7_DATA_DIR unless named here)",
    )

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

    sub.add_parser(
        "rebuild-best",
        help="recompute each stored session's best lap from its summary (stores from 0.4.0)",
    )

    wb = sub.add_parser(
        "web", help="the pit wall: browse sessions and laps in GT7_DATA_DIR (needs the web extra)"
    )
    wb.add_argument(
        "--port", type=int, default=None, help="port to listen on (GT7_WEB_PORT, default 8501)"
    )
    wb.add_argument(
        "--address", default="0.0.0.0", help="address to listen on (default all, for a container)"
    )

    hc = sub.add_parser(
        "healthcheck", help="exit 0 when the engineer or pit wall in this container answers"
    )
    hc.add_argument(
        "--mode",
        choices=["run", "web"],
        default=None,
        help="which to probe (default: the mode of PID 1, or either)",
    )
    hc.add_argument("--timeout", type=float, default=2.0, help="seconds per probe (default 2)")
    return p


# The parsed environment variables each command reads. An invalid value in any
# other variable does not stop the command. LOG_LEVEL is checked for all.
SETTINGS_USED: dict[str, tuple[str, ...]] = {
    "run": Settings.PARSED,
    "say": ("DISCORD_VOICE_CHANNEL_ID", "GT7_CACHE_DIR", "GT7_CACHE_MAX_MB"),
    "post": ("DISCORD_RESULTS_CHANNEL_ID",),
    "web": ("GT7_WEB_PORT",),
    "healthcheck": ("GT7_METRICS_PORT", "GT7_WEB_PORT"),
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env(check=("LOG_LEVEL", *SETTINGS_USED.get(args.command, ())))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)  # logging is not set up yet
        return 2
    logging.basicConfig(
        level=logging.getLevelNamesMapping()[settings.log_level],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        return dispatch(args, settings)
    except StoreBusy as exc:  # another process holds the data directory's writer lock
        print(f"those-who-run {args.command}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        known = known_failure(exc)
        if known is None:
            raise
        message, code = known
        log.error("%s", message)
        # One line for the user; the traceback stays one LOG_LEVEL=DEBUG away,
        # so a bug that happens to raise one of these is not hidden for good.
        log.debug("traceback for the error above", exc_info=exc)
        return code


def dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "run":
        return asyncio.run(run_live(settings, record=args.record))
    if args.command == "say":
        return asyncio.run(run_say(settings, args.text))
    if args.command == "replay":
        return asyncio.run(
            run_replay(settings, args.recording, args.wav_out, args.realtime, args.store)
        )
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
    if args.command == "rebuild-best":
        return run_rebuild_best(settings)
    if args.command == "web":
        return run_web(settings, args.port or settings.web_port, args.address)
    if args.command == "healthcheck":
        from those_who_run.healthcheck import run_healthcheck

        return run_healthcheck(settings, args.mode, args.timeout)
    return 1


def run_rebuild_best(settings: Settings) -> int:
    from those_who_run.results import race_time
    from those_who_run.store import rebuild_best_laps

    if not (settings.data_dir / "index.sqlite").exists():
        raise ConfigError(f"{settings.data_dir}: no index.sqlite")
    fixes = rebuild_best_laps(settings.data_dir)
    for f in fixes:
        before = race_time(f.before) if f.before else "-"
        after = race_time(f.after) if f.after else "-"
        print(f"{f.session_id}  {before} -> {after}")
    print(f"\n{len(fixes)} session(s) corrected")
    return 0


def known_failure(exc: BaseException) -> tuple[str, int] | None:
    """A one-line message and exit code for a failure the user can fix, or
    None for a bug, which keeps its traceback. Exit 2 is configuration."""
    if isinstance(exc, ConfigError):
        return f"configuration error: {exc}", 2
    try:
        import discord
    except ImportError:  # pragma: no cover - a core dependency
        discord = None  # type: ignore[assignment]
    if discord is not None and isinstance(exc, discord.LoginFailure):
        return f"Discord rejected DISCORD_BOT_TOKEN: {exc}", 2
    try:
        from gt_telem.errors.playstation_errors import (
            PlayStationNotFoundError,
            PlayStationOnStandbyError,
        )
    except ImportError:  # pragma: no cover - a core dependency
        pass
    else:
        if isinstance(exc, PlayStationNotFoundError):
            return "no PS5 found on the network: set GT7_PS5_IP or pass --ps5-ip", 1
        if isinstance(exc, PlayStationOnStandbyError):
            return f"the PS5 is on standby, wake it and try again: {exc}", 1
    if isinstance(exc, FileNotFoundError):
        return f"file not found: {exc.filename or exc}", 1
    if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
        return f"port already in use, is another engineer running? ({exc})", 1
    if isinstance(exc, PermissionError):
        return f"permission denied: {exc.filename or exc}", 1
    return None


def require_voice_model(settings: Settings) -> Path:
    path = settings.voice_model
    if not path.exists():
        raise ConfigError(f"voice model not found: {path} (set GT7_VOICE_MODEL, or `make voice`)")
    return path


async def run_post(settings: Settings, session_id: str, dry_run: bool) -> int:
    import discord

    from those_who_run.results import ResultsPoster, build_card

    path = settings.data_dir / "sessions" / session_id / "summary.json"
    if not path.exists():
        raise ConfigError(f"{path}: no such session summary")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: not valid JSON: {exc}") from exc
    card = build_card(summary, settings.pitwall_url)
    if card is None:
        print("no full lap: nothing to post")
        return 1
    print(card.title)
    if card.url:
        print(card.url)
    print(card.description)
    for name, value in card.fields:
        print(f"  {name}: {value}")
    if dry_run:
        return 0
    if not settings.discord_token or not settings.results_channel_id:
        raise ConfigError("posting needs DISCORD_BOT_TOKEN and DISCORD_RESULTS_CHANNEL_ID")
    # Recording the post writes the index: refused (StoreBusy) while the engineer runs.
    store = SessionStore(settings.data_dir)
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(settings.discord_token)  # HTTP only: no gateway needed to post
        poster = ResultsPoster(client, settings.results_channel_id, on_posted=store.mark_posted)
        ok = await poster.post(session_id, card)
    finally:
        await client.close()
        store.close()
    return 0 if ok else 1


def run_web(settings: Settings, port: int, address: str) -> int:
    """Serve the pit wall with ``streamlit run``. Streamlit is imported here only,
    so the engineer runs without the web extra installed."""
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as exc:
        raise ConfigError("the pit wall needs Streamlit: pip install 'those-who-run[web]'") from exc
    from those_who_run import pitwall

    script = Path(pitwall.__file__).with_name("app.py")
    os.environ["GT7_DATA_DIR"] = str(settings.data_dir.resolve())  # read again by the app
    log.info("pit wall on http://%s:%d, reading %s", address, port, settings.data_dir)
    return (
        streamlit_cli.main(
            ["run", str(script), *streamlit_flags(port, address)],
            prog_name="streamlit",
            standalone_mode=False,
        )
        or 0
    )


def streamlit_flags(port: int, address: str) -> list[str]:
    """Server and theme options for ``streamlit run``: headless, no file watching
    or usage stats, and the livery."""
    return [
        f"--server.port={port}",
        f"--server.address={address}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--theme.base=dark",
        f"--theme.primaryColor={brand.hex_colour(brand.ACCENT)}",
        f"--theme.backgroundColor={brand.hex_colour(brand.BACKGROUND)}",
        f"--theme.secondaryBackgroundColor={brand.hex_colour(brand.PANEL)}",
        f"--theme.textColor={brand.hex_colour(brand.TEXT)}",
    ]


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
        try:
            sessions, complete = summarise_recording(f)
        except Exception as exc:  # noqa: BLE001 - one bad file must not end the listing
            log.exception("could not read %s", f)
            print(f"{f.name}  (unreadable: {exc})")
            continue
        print(f.name + ("" if complete else "  (incomplete: still being written or cut off)"))
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
        results = backfill(settings.data_dir, force=args.force)  # StoreBusy: see main
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
    settings: Settings,
    recording: Path,
    wav_out: Path | None,
    realtime: bool,
    store_dir: Path | None = None,
) -> int:
    """Replay a recording. Sessions in it go to ``store_dir``, or to a temporary
    directory thrown away afterwards: never into ``GT7_DATA_DIR`` (the pit wall
    and the results history only ever see real drives) unless named here, and
    then only while the engineer is stopped (the store's writer lock)."""
    import tempfile

    from those_who_run.audio.player import ConsolePlayer, WavDirPlayer
    from those_who_run.replay import read_recording, replay, summarise

    rules_cfg = load_rules_config(settings.rules_file)
    queue = CalloutQueue(max_age=None)
    if wav_out is not None:
        from those_who_run.speech import PiperSpeech

        speech = PiperSpeech(require_voice_model(settings), wav_out / ".cache", rules_cfg["voice"])
        player: ConsolePlayer = WavDirPlayer(speech, wav_out)
    else:
        player = ConsolePlayer()
    with tempfile.TemporaryDirectory(prefix="those-who-run-replay-") as tmp:
        store = SessionStore(store_dir or Path(tmp))
        engine = Engine(build_rules(rules_cfg["rules"]), queue, store)
        try:
            spoken = await replay(read_recording(recording), engine, player, realtime=realtime)
        finally:
            try:
                # A session still open when the recording stops is ended, so the
                # store is complete: every session has its summary.json.
                if store.session is not None and engine.prev is not None:
                    store.end_session(engine.prev)
            finally:
                store.close()
    log.info("replay summary: %s", summarise(spoken, queue))
    if store_dir is not None:
        log.info("sessions stored in %s", store_dir)
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
    speech = PiperSpeech(
        require_voice_model(settings),
        settings.speech_cache_dir,
        rules_cfg["voice"],
        max_cache_bytes=settings.cache_max_bytes,
    )
    player = DiscordPlayer(settings.discord_token, settings.discord_channel_id, speech)
    await player.start()
    try:
        if not await player.connect():
            log.error("could not join the voice channel, see errors above")
            return 1
        await player.play(Callout(text=text, priority=0, rule="say", created_at=time.monotonic()))
        await asyncio.sleep(0.5)
    finally:
        await player.close()
    return 0


async def run_live(
    settings: Settings, record: Path | None = None, stop: asyncio.Event | None = None
) -> int:
    """The live engineer. Runs until ``stop`` is set, by SIGINT or SIGTERM
    unless the caller passes its own event; startup is cut short too."""
    from those_who_run.audio.discord_player import DiscordPlayer
    from those_who_run.replay import OutingRecorder, RecordingWriter
    from those_who_run.rules.telemetry import TelemetryVoice
    from those_who_run.speech import PiperSpeech
    from those_who_run.telemetry import LiveTelemetry

    live = settings.require_live()
    rules_cfg = load_rules_config(settings.rules_file)
    rules = build_rules(rules_cfg["rules"])
    metrics = Metrics()
    queue = CalloutQueue(max_age=float(rules_cfg["queue"]["max_age_seconds"]))
    recorder = SessionStore(settings.data_dir)  # StoreBusy first: see main
    try:
        voice_model = require_voice_model(settings)  # before any socket or Discord connection
    except ConfigError:
        recorder.close()
        raise
    engine = Engine(rules, queue, recorder, metrics)
    speech = PiperSpeech(
        voice_model,
        settings.speech_cache_dir,
        rules_cfg["voice"],
        on_duration=metrics.speech_seconds.observe,
        max_cache_bytes=settings.cache_max_bytes,
    )
    player = DiscordPlayer(
        live.discord_token,
        live.discord_channel_id,
        speech,
        idle_disconnect_secs=settings.idle_disconnect_secs,
        on_voice_state=lambda up: metrics.voice_connected.set(1 if up else 0),
        max_age=queue.max_age,
    )
    loop = asyncio.get_running_loop()
    states: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(live.ps5_ip, states, loop)

    stop = stop if stop is not None else asyncio.Event()
    supervisor = Supervisor(stop)

    def health() -> dict:
        return {
            # Telemetry and voice are down whenever the PS5 is off, which is
            # normal. A dead task, or a telemetry listener that cannot bind,
            # makes the engineer unhealthy.
            "ok": supervisor.ok() and telem.healthy,
            "tasks": supervisor.alive(),
            "telemetry_connected": telem.connected(settings.telemetry_timeout_secs),
            "telemetry_listening": telem.listening,
            "telemetry_restarts": telem.restarts,
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
            pitwall_url=settings.pitwall_url,
        )
        recorder.on_end = poster.submit
        log.info("results cards go to channel %s", settings.results_channel_id)

    http = HealthServer(settings.metrics_port, metrics, health)

    async def startup() -> None:
        # Pre-warm the voice so the first callout is not late.
        await loop.run_in_executor(None, speech.synthesize, "Race engineer online.")
        await player.start()
        telem.start()

    async def handle(state: RaceState) -> None:
        if writer is not None:
            writer.write(state)
        engine.process(state)
        await player.on_phase(state.phase, state.t)

    async def watchdog() -> None:
        was: bool | None = None
        voice = TelemetryVoice(rules_cfg["rules"].get("telemetry"))
        log.info("telemetry: waiting for packets from %s", settings.ps5_ip)
        errors = ErrorLog("watchdog tick")
        while True:
            try:
                now_connected = telem.connected(settings.telemetry_timeout_secs)
                metrics.telemetry_connected.set(1 if now_connected else 0)
                if now_connected != was and (was is not None or now_connected):
                    log.info("telemetry %s", "connected" if now_connected else "lost")
                was = now_connected
                for c in voice.observe(now_connected, engine.prev, time.monotonic()):
                    queue.push(c)
                    metrics.callouts_total.labels(c.rule).inc()
                    log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
                await player.check_idle(time.monotonic())
            except Exception:
                errors.log()
            await asyncio.sleep(1)

    async def run_tasks() -> None:
        supervisor.spawn("ingest", lambda: ingest_loop(states, handle))
        supervisor.spawn("speak", lambda: speak_loop(queue, player))
        supervisor.spawn("watchdog", watchdog)
        if poster is not None:
            supervisor.spawn("results", poster.run)
        await stop.wait()

    writer: RecordingWriter | OutingRecorder | None = None
    signals = (signal.SIGINT, signal.SIGTERM)
    for sig in signals:
        loop.add_signal_handler(sig, stop.set)
    try:
        http.start()
        if record is not None:
            writer = RecordingWriter(record)
            log.info("recording telemetry frames to %s", record)
        elif settings.record_dir is not None:
            writer = OutingRecorder(settings.record_dir, settings.record_keep)
            log.info(
                "recording outings to %s, keeping %d", settings.record_dir, settings.record_keep
            )
        log.info("%s starting", brand.banner(__version__))
        if not await until_stopped(startup(), stop):
            log.info("stopped during startup")
            return 0
        await run_tasks()
    finally:
        # The signal handlers stay installed until the data is flushed: a second
        # Ctrl-C or SIGTERM only sets stop again, so it cannot cut short
        # summary.json, the last Parquet file or the recording. Data goes first,
        # the network after, and a hung voice close is bounded.
        log.info("shutting down")
        try:
            await supervisor.close()
            await telem.stop()
            recorder.on_end = None  # the loop is going: no card for a session cut short here
            if recorder.session is not None and engine.prev is not None:
                log.info("closing session %s", recorder.session.session_id)
                recorder.end_session(engine.prev)
            recorder.close()
            if writer is not None:
                writer.close()
                log.info("recorded %d frames to %s", writer.count, record or settings.record_dir)
            try:
                await asyncio.wait_for(player.close(), PLAYER_CLOSE_SECS)
            except TimeoutError:
                log.warning("discord did not close within %.0fs, leaving anyway", PLAYER_CLOSE_SECS)
            http.stop()
        finally:
            for sig in signals:
                loop.remove_signal_handler(sig)
    if supervisor.failed:
        log.error("a task could not be kept running: exiting non-zero")
        return 1
    return 0


PLAYER_CLOSE_SECS = 5.0  # docker stop sends SIGKILL after 10 s


async def until_stopped(aw: Awaitable[object], stop: asyncio.Event) -> bool:
    """Run ``aw`` unless ``stop`` is set first. True when it finished (its
    exception propagates); False when ``stop`` won and it was cancelled. Lets
    Ctrl-C and SIGTERM end a startup that hangs, say in ``wait_until_ready``."""
    task = asyncio.ensure_future(aw)
    stopper = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopper.cancel()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    if task.cancelled():
        return False
    task.result()
    return True


class ErrorLog:
    """Logs an error in a loop with its traceback, at most once per
    ``every_secs``, so a fault on every 60 Hz frame does not flood the log.
    Errors in between are counted and reported with the next traceback."""

    def __init__(self, what: str, every_secs: float = 10.0) -> None:
        self._what = what
        self._every = every_secs
        self._last: float | None = None
        self._suppressed = 0

    def log(self, detail: str = "") -> None:
        now = time.monotonic()
        if self._last is not None and now - self._last < self._every:
            self._suppressed += 1
            return
        more = f" ({self._suppressed} more since last report)" if self._suppressed else ""
        log.exception("error in %s%s%s", self._what, f" {detail}" if detail else "", more)
        self._last, self._suppressed = now, 0


async def ingest_loop(
    states: asyncio.Queue[RaceState], handle: Callable[[RaceState], Awaitable[None]]
) -> None:
    """Feed every frame to ``handle``. A frame that raises is logged and
    skipped; the next frame is still processed."""
    errors = ErrorLog("processing frame")
    while True:
        state = await states.get()
        try:
            await handle(state)
        except Exception:
            errors.log(f"t={state.t:.2f}")


async def speak_loop(
    queue: CalloutQueue,
    player: Player,
    clock: Callable[[], float] = time.monotonic,
    idle_secs: float = 0.05,
) -> None:
    """Speak callouts as they come. A callout that fails to play is logged
    and the next one is still spoken."""
    while True:
        c = queue.pop(clock())
        if c is None:
            await asyncio.sleep(idle_secs)
            continue
        try:
            await player.play(c)
        except Exception:
            log.exception("error speaking callout (%s): %s", c.rule, c.text)


if __name__ == "__main__":
    sys.exit(main())
