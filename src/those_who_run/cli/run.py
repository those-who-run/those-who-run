"""``those-who-run run``: the live engineer, PS5 telemetry in, Discord voice out."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from those_who_run import __version__, brand
from those_who_run.callouts import CalloutQueue
from those_who_run.cli.common import require_voice_model
from those_who_run.config import ConfigError, Settings, load_rules_config
from those_who_run.engine import Engine
from those_who_run.metrics import HealthServer, Metrics
from those_who_run.rules import build_rules
from those_who_run.state import RaceState
from those_who_run.store import SessionStore
from those_who_run.supervise import Supervisor

if TYPE_CHECKING:
    from those_who_run.audio.player import Player

log = logging.getLogger("those_who_run")

HELP = "live: PS5 telemetry in, Discord voice out"
SETTINGS: tuple[str, ...] = Settings.PARSED


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record", type=Path, help="also append every telemetry frame to this JSONL file"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(run_live(settings, record=args.record))


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
    recorder = SessionStore(settings.data_dir)  # StoreBusy first: see cli.main
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
