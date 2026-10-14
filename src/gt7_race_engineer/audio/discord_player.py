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
from typing import Any

import discord

from gt7_race_engineer.callouts import Callout
from gt7_race_engineer.speech import Speech
from gt7_race_engineer.state import Phase

log = logging.getLogger(__name__)

ACTIVE_PHASES = {Phase.AT_TRACK, Phase.IN_RACE, Phase.PAUSED}


class DiscordPlayer:
    def __init__(
        self,
        token: str,
        channel_id: int,
        speech: Speech,
        idle_disconnect_secs: float = 600.0,
        reconnect_backoff_secs: float = 15.0,
        on_voice_state: Any | None = None,
        client: discord.Client | None = None,
    ) -> None:
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
        self._idle_since: float | None = None
        self._play_lock = asyncio.Lock()

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
        await self._disconnect()
        await self._client.close()
        if self._client_task is not None:
            self._client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._client_task

    @property
    def connected(self) -> bool:
        return self._vc is not None and self._vc.is_connected()

    # phase driven join/leave

    async def on_phase(self, phase: Phase, now: float) -> None:
        if phase in ACTIVE_PHASES:
            self._idle_since = None
            if not self.connected:
                await self._ensure_connected(now)
            return
        if self._idle_since is None:
            self._idle_since = now
        elif self.connected and now - self._idle_since > self._idle_secs:
            log.info("idle for %.0fs, leaving voice channel", now - self._idle_since)
            await self._disconnect()

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
                self._vc = await channel.connect(reconnect=True, self_deaf=True)
                log.info("joined voice channel %s", channel.name)
                self._report_voice(True)
            except Exception:  # noqa: BLE001
                log.exception("failed to join voice channel %s", self._channel_id)
                self._vc = None
                self._report_voice(False)

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

    async def play(self, callout: Callout) -> None:
        if not self.connected:
            await self._ensure_connected(time.monotonic())
            if not self.connected:
                log.warning("dropping callout, not connected to voice: %s", callout.text)
                return
        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(None, self._speech.synthesize, callout.text)
        async with self._play_lock:
            vc = self._vc
            if vc is None:
                return
            done = asyncio.Event()

            def _after(err: Exception | None) -> None:
                if err is not None:
                    log.error("playback error: %s", err)
                loop.call_soon_threadsafe(done.set)

            log.info("speaking (%s): %s", callout.rule, callout.text)
            vc.play(discord.FFmpegPCMAudio(str(wav)), after=_after)
            await done.wait()
