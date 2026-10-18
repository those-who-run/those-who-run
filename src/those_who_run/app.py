"""The live engineer as one object: build, start, run, report and stop.

:class:`App` builds every component, runs the long-lived loops under a
:class:`~those_who_run.supervise.Supervisor`, handles SIGINT and SIGTERM, and
tears everything down from one :class:`contextlib.AsyncExitStack`. A component
that fails to start leaves nothing open. The control API (#136) and the rest
call :meth:`App.status` and :meth:`App.stop`.

The PS5, Discord and Piper are reached only through the factories passed in,
which default to the real classes, so a test runs the whole engineer with fakes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from those_who_run import __version__, brand
from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.config import LiveSettings, Settings, load_rules_config
from those_who_run.engine import Engine
from those_who_run.metrics import Metrics
from those_who_run.rules import build_rules
from those_who_run.server import Server
from those_who_run.state import Phase, RaceState
from those_who_run.store import SessionStore
from those_who_run.supervise import Supervisor

if TYPE_CHECKING:
    from those_who_run.audio.player import Player
    from those_who_run.replay import OutingRecorder, RecordingWriter
    from those_who_run.results import ResultsPoster
    from those_who_run.speech import Speech

log = logging.getLogger("those_who_run")

PLAYER_CLOSE_SECS = 5.0  # docker stop sends SIGKILL after 10 s


class TelemetrySource(Protocol):
    """What the engineer needs from :class:`~those_who_run.telemetry.LiveTelemetry`:
    it puts each frame on ``App.states`` once started."""

    packets: int
    listening: bool
    restarts: int

    @property
    def healthy(self) -> bool: ...

    def start(self) -> None: ...

    async def stop(self) -> None: ...

    def connected(self, timeout: float) -> bool: ...


class VoicePlayer(Protocol):
    """What the engineer needs from :class:`~those_who_run.audio.discord_player.DiscordPlayer`."""

    @property
    def connected(self) -> bool: ...

    @property
    def client(self) -> Any: ...  # the discord.Client the results poster shares

    async def start(self) -> None: ...

    async def play(self, callout: Callout) -> None: ...

    async def on_phase(self, phase: Phase, now: float) -> None: ...

    async def check_idle(self, now: float) -> None: ...

    async def close(self) -> None: ...


def piper_speech(app: App) -> Speech:
    from those_who_run.speech import PiperSpeech

    return PiperSpeech(
        app.voice_model,
        app.settings.speech_cache_dir,
        app.rules_cfg["voice"],
        on_duration=app.metrics.speech_seconds.observe,
        max_cache_bytes=app.settings.cache_max_bytes,
    )


def discord_player(app: App) -> VoicePlayer:
    from those_who_run.audio.discord_player import DiscordPlayer

    metrics = app.metrics
    return DiscordPlayer(
        app.live.discord_token,
        app.live.discord_channel_id,
        app.speech,
        idle_disconnect_secs=app.settings.idle_disconnect_secs,
        on_voice_state=lambda up: metrics.voice_connected.set(1 if up else 0),
        max_age=app.queue.max_age,
    )


def live_telemetry(app: App) -> TelemetrySource:
    from those_who_run.telemetry import LiveTelemetry

    return LiveTelemetry(app.live.ps5_ip, app.states, asyncio.get_running_loop())


class App:
    """The live engineer. :meth:`run` once: it starts everything, runs until
    :meth:`stop` (or SIGINT, SIGTERM, or a task that cannot be kept running),
    then flushes the data and closes the network, and returns the exit code.

    A stop during startup cuts it short. Teardown order: the loops, telemetry
    (no frame arrives once the session is being closed), the open session, the
    recording, voice (bounded by ``PLAYER_CLOSE_SECS``), the HTTP server, and
    the signal handlers last, so a second Ctrl-C or SIGTERM cannot cut short
    the flush.
    """

    def __init__(
        self,
        settings: Settings,
        record: Path | None = None,
        *,
        speech: Callable[[App], Speech] = piper_speech,
        player: Callable[[App], VoicePlayer] = discord_player,
        telemetry: Callable[[App], TelemetrySource] = live_telemetry,
    ) -> None:
        self.settings = settings
        self.record = record
        self._make_speech = speech
        self._make_player = player
        self._make_telemetry = telemetry
        self._stop = asyncio.Event()
        self.supervisor = Supervisor(self._stop)
        self.metrics = Metrics()
        # Add API routes to ``server.api`` (or ``server.control_api``) before run().
        self.server = Server(
            self.metrics,
            self.status,
            host=settings.bind_address,
            port=settings.metrics_port,
            control_port=settings.control_port,
        )
        self.writer: RecordingWriter | OutingRecorder | None = None
        self.poster: ResultsPoster | None = None
        self._store_open = False

    # control

    def stop(self) -> None:
        """Ask the engineer to stop. :meth:`run` returns once it is torn down."""
        self._stop.set()

    def status(self) -> dict[str, Any]:
        """The engineer's health: the ``/healthz`` body."""
        engine, telem = self.engine, self.telemetry
        return {
            # Telemetry and voice are down whenever the PS5 is off, which is
            # normal. A dead task, or a telemetry listener that cannot bind,
            # makes the engineer unhealthy.
            "ok": self.supervisor.ok() and telem.healthy,
            "tasks": self.supervisor.alive(),
            "telemetry_connected": telem.connected(self.settings.telemetry_timeout_secs),
            "telemetry_listening": telem.listening,
            "telemetry_restarts": telem.restarts,
            "voice_connected": self.player.connected,
            "packets": telem.packets,
            "races_started": engine.races_started,
            "queue": len(self.queue),
            "session": engine.kind.record(),
            "track": None
            if engine.track is None
            else {
                "id": engine.track.track_id,
                "name": engine.track.name,
                "confidence": engine.track.confidence,
            },
        }

    # lifecycle

    async def run(self) -> int:
        async with contextlib.AsyncExitStack() as stack:
            if not await self._start(stack):
                return 0
            await self._stop.wait()
        if self.supervisor.failed:
            log.error("a task could not be kept running: exiting non-zero")
            return 1
        return 0

    async def _start(self, stack: contextlib.AsyncExitStack) -> bool:
        """Build and start everything, registering each closer on ``stack``
        before the thing it closes can be opened. False when stopped first."""
        settings = self.settings
        self.live: LiveSettings = settings.require_live()
        self.rules_cfg = load_rules_config(settings.rules_file)
        rules = build_rules(self.rules_cfg["rules"])
        self.queue = CalloutQueue(max_age=float(self.rules_cfg["queue"]["max_age_seconds"]))
        self.store = SessionStore(settings.data_dir)  # StoreBusy first: see cli.main
        self._store_open = True
        stack.callback(self._close_store)  # only if what follows fails to build
        self.voice_model = settings.require_voice_model()  # before any socket or Discord
        self.engine = Engine(rules, self.queue, self.store, self.metrics)
        self.speech = self._make_speech(self)
        self.player = self._make_player(self)
        self.states: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
        self.telemetry = self._make_telemetry(self)
        if settings.results_channel_id:
            from those_who_run.results import ResultsPoster

            metrics = self.metrics
            self.poster = ResultsPoster(
                self.player.client,
                settings.results_channel_id,
                on_posted=self.store.mark_posted,
                on_result=lambda r: metrics.results_posts_total.labels(r).inc(),
                pitwall_url=settings.pitwall_url,
            )
            self.store.on_end = self.poster.submit
            log.info("results cards go to channel %s", settings.results_channel_id)

        # Teardown runs these last first: data goes before the network.
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)
        for sig in signals:
            loop.add_signal_handler(sig, self._stop.set)
        for sig in signals:
            stack.callback(loop.remove_signal_handler, sig)
        stack.push_async_callback(self.server.stop)
        stack.push_async_callback(self._close_player)
        stack.callback(self._close_writer)
        stack.callback(self._close_session)
        stack.push_async_callback(self.telemetry.stop)
        stack.push_async_callback(self.supervisor.close)
        stack.callback(log.info, "shutting down")

        await self.server.start()
        if self.record is not None:
            from those_who_run.replay import RecordingWriter

            self.writer = RecordingWriter(self.record)
            log.info("recording telemetry frames to %s", self.record)
        elif settings.record_dir is not None:
            from those_who_run.replay import OutingRecorder

            self.writer = OutingRecorder(settings.record_dir, settings.record_keep)
            log.info(
                "recording outings to %s, keeping %d", settings.record_dir, settings.record_keep
            )
        log.info("%s starting", brand.banner(__version__))
        if not await until_stopped(self._startup(), self._stop):
            log.info("stopped during startup")
            return False
        self.supervisor.spawn("ingest", lambda: ingest_loop(self.states, self._handle))
        self.supervisor.spawn("speak", lambda: speak_loop(self.queue, self.player))
        self.supervisor.spawn("watchdog", self._watchdog)
        if self.poster is not None:
            self.supervisor.spawn("results", self.poster.run)
        return True

    async def _startup(self) -> None:
        # Pre-warm the voice so the first callout is not late.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.speech.synthesize, "Race engineer online.")
        await self.player.start()
        self.telemetry.start()

    def _close_session(self) -> None:
        self.store.on_end = None  # the loop is going: no card for a session cut short here
        if self.store.session is not None and self.engine.prev is not None:
            log.info("closing session %s", self.store.session.session_id)
            self.store.end_session(self.engine.prev)
        self._close_store()

    def _close_store(self) -> None:
        if self._store_open:
            self._store_open = False
            self.store.close()

    def _close_writer(self) -> None:
        if self.writer is not None:
            self.writer.close()
            log.info(
                "recorded %d frames to %s",
                self.writer.count,
                self.record or self.settings.record_dir,
            )

    async def _close_player(self) -> None:
        try:
            await asyncio.wait_for(self.player.close(), PLAYER_CLOSE_SECS)
        except TimeoutError:
            log.warning("discord did not close within %.0fs, leaving anyway", PLAYER_CLOSE_SECS)

    # the loops

    async def _handle(self, state: RaceState) -> None:
        if self.writer is not None:
            self.writer.write(state)
        self.engine.process(state)
        await self.player.on_phase(state.phase, state.t)

    async def _watchdog(self) -> None:
        from those_who_run.rules.telemetry import TelemetryVoice

        settings, metrics, telem = self.settings, self.metrics, self.telemetry
        was: bool | None = None
        voice = TelemetryVoice(self.rules_cfg["rules"].get("telemetry"))
        log.info("telemetry: waiting for packets from %s", settings.ps5_ip)
        errors = ErrorLog("watchdog tick")
        while True:
            try:
                now_connected = telem.connected(settings.telemetry_timeout_secs)
                metrics.telemetry_connected.set(1 if now_connected else 0)
                if now_connected != was and (was is not None or now_connected):
                    log.info("telemetry %s", "connected" if now_connected else "lost")
                was = now_connected
                for c in voice.observe(now_connected, self.engine.prev, time.monotonic()):
                    self.queue.push(c)
                    metrics.callouts_total.labels(c.rule).inc()
                    log.info("callout queued (%s, p%d): %s", c.rule, c.priority, c.text)
                await self.player.check_idle(time.monotonic())
            except Exception:
                errors.log()
            await asyncio.sleep(1)


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
    queue: CalloutQueue, player: Player, clock: Callable[[], float] = time.monotonic
) -> None:
    """Speak callouts as they fall due. A callout that fails to play is logged
    and the next one is still spoken."""
    while True:
        c = await queue.get(clock)
        try:
            await player.play(c)
        except Exception:
            log.exception("error speaking callout (%s): %s", c.rule, c.text)
