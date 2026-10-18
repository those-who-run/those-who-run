"""Discord voice output.

The PS5 joins a voice channel through its Discord integration; this bot joins
the same channel and plays synthesised WAVs into it, which is how the audio
reaches the PSVR2 headset. Only the send path is used: no voice receive, no
message content intent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import discord

from those_who_run.callouts import Callout
from those_who_run.speech import Speech
from those_who_run.state import Phase

log = logging.getLogger(__name__)

ACTIVE_PHASES = {Phase.AT_TRACK, Phase.IN_RACE, Phase.PAUSED}


def wav_seconds(path: Path) -> float | None:
    """Length of a WAV file, or None when it cannot be read."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except OSError, EOFError, wave.Error, ZeroDivisionError:
        return None


class DiscordPlayer:
    STALE_ATTEMPTS_BEFORE_RESET = 4  # x reconnect_backoff_secs = 60 s by default
    PLAY_MARGIN_SECS = 5.0  # on top of the clip's length before playback is cut off
    PLAY_UNKNOWN_SECS = 30.0  # the bound when the clip's length cannot be read

    def __init__(
        self,
        token: str,
        channel_id: int,
        speech: Speech,
        idle_disconnect_secs: float = 600.0,
        reconnect_backoff_secs: float = 15.0,
        on_voice_state: Any | None = None,
        client: discord.Client | None = None,
        max_age: float | None = None,
        source_factory: Callable[[str], discord.AudioSource] | None = None,
    ) -> None:
        """``max_age`` is the queue's staleness limit: a callout without its own
        ``max_age`` that passes ``created_at + max_age`` while voice connects or
        the clip is synthesised is dropped, not spoken. ``source_factory`` makes
        the audio source from a WAV path (ffmpeg by default)."""
        self._token = token
        self._channel_id = channel_id
        self._speech = speech
        self._idle_secs = idle_disconnect_secs
        self._backoff = reconnect_backoff_secs
        self._on_voice_state = on_voice_state
        if client is None:
            intents = discord.Intents.none()
            intents.guilds = True
            intents.voice_states = True
            client = discord.Client(intents=intents)
        self._client = client
        self._client_task: asyncio.Task[None] | None = None
        self._vc: discord.VoiceClient | None = None
        self._connect_lock = asyncio.Lock()
        self._last_connect_attempt = 0.0
        self._stale_attempts = 0
        self._last_active: float | None = None
        self._play_lock = asyncio.Lock()
        self._connect_task: asyncio.Task[None] | None = None
        self._max_age = max_age
        self._source_factory = source_factory or discord.FFmpegPCMAudio

    # lifecycle

    async def start(self) -> None:
        # login() must complete before wait_until_ready() can be awaited; it
        # initialises the client's internal state. connect() then runs the
        # gateway loop in the background for the life of the process.
        await self._client.login(self._token)
        self._client_task = asyncio.create_task(
            self._client.connect(reconnect=True), name="discord"
        )
        await self._client.wait_until_ready()
        log.info("discord ready as %s", self._client.user)

    async def close(self) -> None:
        if self._connect_task is not None:
            self._connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._connect_task
        await self._disconnect()
        await self._client.close()
        if self._client_task is not None:
            self._client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._client_task

    @property
    def client(self) -> discord.Client:
        """The logged-in client, shared with the results poster."""
        return self._client

    @property
    def connected(self) -> bool:
        return self._vc is not None and self._vc.is_connected()

    # phase driven join/leave

    async def on_phase(self, phase: Phase, now: float) -> None:
        """Join when on track. Never waits for the join: telemetry ingest calls
        this on every frame, and ``channel.connect`` can take a minute."""
        if phase in ACTIVE_PHASES:
            self._last_active = now
            if not self.connected:
                self._start_connect(now)

    async def check_idle(self, now: float) -> None:
        """Leave the channel once no frame has been on track for the idle period.
        Driven by a timer, so it also fires when frames stop arriving."""
        if self._last_active is None:
            self._last_active = now  # joined without a frame (say): start counting
            return
        if self.connected and now - self._last_active > self._idle_secs:
            log.info("idle for %.0fs, leaving voice channel", now - self._last_active)
            await self._disconnect()

    async def connect(self, now: float | None = None) -> bool:
        """Join now and wait for the outcome. Returns whether voice is up."""
        task = self._start_connect(time.monotonic() if now is None else now)
        if task is not None:
            await asyncio.shield(task)
        return self.connected

    def _start_connect(self, now: float) -> asyncio.Task[None] | None:
        """The running join, or a new one in the background. None when voice is
        up or the last attempt is within the backoff."""
        if self._connect_task is not None and not self._connect_task.done():
            return self._connect_task
        if self.connected or now - self._last_connect_attempt < self._backoff:
            return None
        self._connect_task = asyncio.create_task(self._ensure_connected(now), name="voice-connect")
        return self._connect_task

    async def _ensure_connected(self, now: float) -> None:
        if now - self._last_connect_attempt < self._backoff:
            return
        async with self._connect_lock:
            if self.connected:
                return
            self._last_connect_attempt = now
            try:
                channel = self._client.get_channel(self._channel_id)
                if channel is None:
                    channel = await self._client.fetch_channel(self._channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    raise RuntimeError(f"channel {self._channel_id} is not a voice channel")
                if await self._adopt_existing(channel):
                    return
                self._vc = await channel.connect(reconnect=True, self_deaf=True)
                self._stale_attempts = 0
                log.info("joined voice channel %s", channel.name)
                self._report_voice(True)
            except Exception:  # noqa: BLE001
                log.exception("failed to join voice channel %s", self._channel_id)
                self._vc = None
                self._report_voice(False)

    async def _adopt_existing(self, channel: Any) -> bool:
        """Handle a voice client discord.py already holds for this guild.

        After a gateway hiccup discord.py reconnects voice on its own, and
        ``channel.connect`` raises "Already connected to a voice channel" for
        as long as that client exists. Reuse it when it is up; while it is
        still reconnecting, wait, and only tear it down if it stays dead for
        several attempts. Returns True when the caller should not connect.
        """
        existing = getattr(channel.guild, "voice_client", None)
        if existing is None:
            self._stale_attempts = 0
            return False
        if existing.is_connected():
            self._vc = existing
            self._stale_attempts = 0
            log.info("reusing voice connection to %s", channel.name)
            self._report_voice(True)
            return True
        self._stale_attempts += 1
        if self._stale_attempts < self.STALE_ATTEMPTS_BEFORE_RESET:
            log.info(
                "voice client for %s is reconnecting, waiting (%d/%d)",
                channel.name,
                self._stale_attempts,
                self.STALE_ATTEMPTS_BEFORE_RESET,
            )
            self._vc = existing
            return True
        log.warning("voice client for %s stuck reconnecting, forcing a fresh join", channel.name)
        with contextlib.suppress(Exception):
            await existing.disconnect(force=True)
        self._vc = None
        self._stale_attempts = 0
        return False

    async def _disconnect(self) -> None:
        if self._vc is not None:
            try:
                await self._vc.disconnect(force=True)
            except Exception:  # noqa: BLE001
                log.exception("error leaving voice channel")
            self._vc = None
            self._report_voice(False)

    def _report_voice(self, state: bool) -> None:
        if self._on_voice_state is not None:
            self._on_voice_state(state)

    # playback

    def _deadline(self, callout: Callout) -> float | None:
        limit = self._max_age if callout.max_age is None else callout.max_age
        return None if limit is None else callout.created_at + limit

    def _stale(self, callout: Callout, deadline: float | None, stage: str) -> bool:
        if deadline is not None and time.monotonic() > deadline:
            log.warning("dropping callout, stale after %s: %s", stage, callout.text)
            return True
        return False

    async def play(self, callout: Callout) -> None:
        deadline = self._deadline(callout)
        if not self.connected:
            task = self._start_connect(time.monotonic())
            if task is not None:
                timeout = None if deadline is None else max(deadline - time.monotonic(), 0.0)
                # shield: a callout giving up must not cancel the join itself
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), timeout)
            if self._stale(callout, deadline, "connecting"):
                return
            if not self.connected:
                log.warning("dropping callout, not connected to voice: %s", callout.text)
                return
        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(None, self._speech.synthesize, callout.text)
        if wav is None:
            log.info("nothing to say (%s): %r", callout.rule, callout.text)
            return
        try:
            await self._speak(wav, callout, deadline)
        finally:
            self._speech.release(wav)  # played or dropped: a one-off clip goes

    async def _speak(self, wav: Path, callout: Callout, deadline: float | None) -> None:
        if self._stale(callout, deadline, "synthesis"):
            return
        async with self._play_lock:
            if self._stale(callout, deadline, "waiting to speak"):
                return
            vc = self._vc
            if vc is None or not vc.is_connected():
                log.warning("dropping callout, voice dropped before playing: %s", callout.text)
                return
            await self._play_wav(vc, wav, callout)

    async def _play_wav(self, vc: Any, wav: Path, callout: Callout) -> None:
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def _after(err: Exception | None) -> None:
            if err is not None:
                log.error("playback error: %s", err)
            loop.call_soon_threadsafe(done.set)

        length = wav_seconds(wav)
        bound = self.PLAY_UNKNOWN_SECS if length is None else length + self.PLAY_MARGIN_SECS
        src = self._source_factory(str(wav))  # spawns ffmpeg
        try:
            log.info("speaking (%s): %s", callout.rule, callout.text)
            vc.play(src, after=_after)
        except BaseException:
            src.cleanup()  # play never started: nothing else will reap ffmpeg
            raise
        try:
            await asyncio.wait_for(done.wait(), bound)
        except TimeoutError:
            log.warning("playback did not finish within %.1fs, stopping: %s", bound, callout.text)
            with contextlib.suppress(Exception):
                vc.stop()
            src.cleanup()
