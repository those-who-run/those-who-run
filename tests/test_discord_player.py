"""DiscordPlayer lifecycle against a stub client. No network."""

import asyncio

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
