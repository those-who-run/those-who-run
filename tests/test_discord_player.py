"""DiscordPlayer lifecycle against a stub client. No network."""

import asyncio

import discord

from gt7_race_engineer.audio.discord_player import DiscordPlayer
from gt7_race_engineer.state import Phase


class StubClient:
    """Mimics the discord.py ordering rule: wait_until_ready needs login first."""

    def __init__(self):
        self.calls = []
        self.user = "stub#0001"
        self._ready = None
        self._connected = asyncio.Event()

    async def login(self, token):
        self.calls.append(("login", token))
        self._ready = asyncio.Event()

    async def connect(self, reconnect=True):
        self.calls.append(("connect", reconnect))
        assert self._ready is not None, "connect before login"
        self._ready.set()
        await self._connected.wait()

    async def wait_until_ready(self):
        if self._ready is None:
            raise RuntimeError("Client has not been properly initialised")
        await self._ready.wait()

    async def close(self):
        self.calls.append(("close", None))
        self._connected.set()

    def get_channel(self, channel_id):
        return None

    async def fetch_channel(self, channel_id):
        raise RuntimeError("no such channel in stub")


class StubVoiceClient:
    def __init__(self, connected):
        self._connected = connected
        self.guild = None
        self.force_disconnects = 0

    def is_connected(self):
        return self._connected

    async def disconnect(self, force=False):
        # discord.py's cleanup() drops the client from the guild on disconnect
        self.force_disconnects += 1
        self._connected = False
        if self.guild is not None:
            self.guild.voice_client = None


class StubGuild:
    def __init__(self, voice_client):
        self.voice_client = voice_client
        if voice_client is not None:
            voice_client.guild = self


class StubVoiceChannel(discord.VoiceChannel):
    """Just enough of a VoiceChannel for the player: no discord state behind it."""

    def __init__(self, voice_client):
        self.name = "race-engineer"
        self.guild = StubGuild(voice_client)
        self.connect_calls = 0

    async def connect(self, *, reconnect=True, self_deaf=False):
        self.connect_calls += 1
        if self.guild.voice_client is not None:
            raise discord.ClientException("Already connected to a voice channel.")
        self.guild.voice_client = StubVoiceClient(True)
        self.guild.voice_client.guild = self.guild
        return self.guild.voice_client


class ChannelStubClient(StubClient):
    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel


class StubSpeech:
    def synthesize(self, text):
        raise AssertionError("should not synthesise in this test")


async def test_start_logs_in_before_waiting_ready():
    client = StubClient()
    player = DiscordPlayer("tok", 123, StubSpeech(), client=client)
    await asyncio.wait_for(player.start(), timeout=2)
    assert client.calls[:2] == [("login", "tok"), ("connect", True)]
    await player.close()
    assert ("close", None) in client.calls


async def test_join_failure_is_logged_not_raised():
    client = StubClient()
    states = []
    player = DiscordPlayer("tok", 123, StubSpeech(), client=client, on_voice_state=states.append)
    await player.start()
    await player.on_phase(Phase.AT_TRACK, now=100.0)
    assert not player.connected
    assert states == [False]
    await player.close()


async def test_reuses_voice_client_discord_reconnected_by_itself():
    """After a gateway stall discord.py reconnects voice on its own; channel.connect
    then raises "Already connected" forever (seen 2026-10-14). Adopt that client."""
    channel = StubVoiceChannel(StubVoiceClient(True))
    client = ChannelStubClient(channel)
    states = []
    player = DiscordPlayer("tok", 123, StubSpeech(), client=client, on_voice_state=states.append)
    await player.start()
    await player.on_phase(Phase.IN_RACE, now=100.0)
    assert player.connected
    assert channel.connect_calls == 0
    assert states == [True]
    await player.close()


async def test_waits_while_discord_reconnects_then_forces_a_fresh_join():
    stale = StubVoiceClient(False)
    channel = StubVoiceChannel(stale)
    client = ChannelStubClient(channel)
    player = DiscordPlayer("tok", 123, StubSpeech(), client=client, reconnect_backoff_secs=15.0)
    await player.start()
    for i in range(DiscordPlayer.STALE_ATTEMPTS_BEFORE_RESET - 1):
        await player.on_phase(Phase.IN_RACE, now=100.0 + 15.0 * i)
        assert not player.connected
        assert channel.connect_calls == 0 and stale.force_disconnects == 0
    await player.on_phase(
        Phase.IN_RACE, now=100.0 + 15.0 * DiscordPlayer.STALE_ATTEMPTS_BEFORE_RESET
    )
    assert stale.force_disconnects == 1
    assert channel.connect_calls == 1
    assert player.connected
    await player.close()
