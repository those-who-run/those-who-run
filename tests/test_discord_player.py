"""DiscordPlayer lifecycle against a stub client. No network."""

import asyncio
import time
import wave

import discord

from tests.conftest import make_state
from those_who_run.__main__ import ingest_loop
from those_who_run.audio.discord_player import DiscordPlayer, wav_seconds
from those_who_run.callouts import Callout
from those_who_run.state import Phase


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
        self.name = "pit-lane"
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
    await player.connect(now=100.0)
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
    await player.connect(now=100.0)
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
        await player.connect(now=100.0 + 15.0 * i)
        assert not player.connected
        assert channel.connect_calls == 0 and stale.force_disconnects == 0
    await player.connect(now=100.0 + 15.0 * DiscordPlayer.STALE_ATTEMPTS_BEFORE_RESET)
    assert stale.force_disconnects == 1
    assert channel.connect_calls == 1
    assert player.connected
    await player.close()


# playback


def write_wav(path, seconds=0.1, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    return path


class WavSpeech:
    def __init__(self, path):
        self.path = path
        self.texts = []

    def synthesize(self, text):
        self.texts.append(text)
        return self.path


class FakeSource:
    def __init__(self, path):
        self.path = path
        self.cleaned = 0

    def cleanup(self):
        self.cleaned += 1


class FakeVoiceClient:
    """``mode``: "finish" calls ``after`` at once, "raise" raises like discord.py
    when voice dropped, "hang" never calls ``after``."""

    def __init__(self, mode="finish", connected=True):
        self.mode = mode
        self._connected = connected
        self.played = []
        self.stopped = 0

    def is_connected(self):
        return self._connected

    def play(self, src, after):
        if self.mode == "raise":
            raise discord.ClientException("Not connected to voice.")
        self.played.append(src)
        if self.mode == "finish":
            after(None)

    def stop(self):
        self.stopped += 1

    async def disconnect(self, force=False):
        self._connected = False


def playing_player(tmp_path, vc, **kw):
    sources = []

    def factory(path):
        sources.append(FakeSource(path))
        return sources[-1]

    speech = WavSpeech(write_wav(tmp_path / "clip.wav"))
    player = DiscordPlayer("tok", 123, speech, client=StubClient(), source_factory=factory, **kw)
    player._vc = vc
    return player, sources, speech


def fresh(text="Pit this lap.", max_age=None):
    return Callout(text=text, priority=5, rule="fuel", created_at=time.monotonic(), max_age=max_age)


def test_wav_seconds(tmp_path):
    assert abs(wav_seconds(write_wav(tmp_path / "a.wav", 0.5)) - 0.5) < 1e-6
    assert wav_seconds(tmp_path / "missing.wav") is None


async def test_plays_and_returns_when_done(tmp_path):
    vc = FakeVoiceClient("finish")
    player, sources, _ = playing_player(tmp_path, vc)
    await asyncio.wait_for(player.play(fresh()), 1)
    assert vc.played == sources and sources[0].cleaned == 0


async def test_source_cleaned_up_when_play_raises(tmp_path):
    vc = FakeVoiceClient("raise")
    player, sources, _ = playing_player(tmp_path, vc)
    try:
        await player.play(fresh())
    except discord.ClientException:
        pass
    else:
        raise AssertionError("expected the play error to reach the caller")
    assert len(sources) == 1 and sources[0].cleaned == 1
    assert not player._play_lock.locked()


async def test_playback_wait_is_bounded_when_after_never_fires(tmp_path):
    vc = FakeVoiceClient("hang")
    player, sources, _ = playing_player(tmp_path, vc)
    player.PLAY_MARGIN_SECS = 0.2  # clip is 0.1 s: bound 0.3 s
    started = time.monotonic()
    await asyncio.wait_for(player.play(fresh()), 2)
    assert time.monotonic() - started < 1.0
    assert vc.stopped == 1 and sources[0].cleaned == 1
    assert not player._play_lock.locked()
    vc.mode = "finish"
    await asyncio.wait_for(player.play(fresh("Final lap.")), 1)
    assert len(vc.played) == 2


async def test_rechecks_connection_inside_the_lock(tmp_path):
    vc = FakeVoiceClient("finish", connected=True)
    player, sources, speech = playing_player(tmp_path, vc)

    def drop_during_synthesis(text):
        vc._connected = False
        return speech.path

    speech.synthesize = drop_during_synthesis
    await player.play(fresh())
    assert sources == [] and vc.played == []


class SlowChannel(StubVoiceChannel):
    def __init__(self, delay, vc=None):
        super().__init__(None)
        self.delay = delay
        self.vc = vc

    async def connect(self, *, reconnect=True, self_deaf=False):
        await asyncio.sleep(self.delay)
        self.guild.voice_client = self.vc or StubVoiceClient(True)
        return self.guild.voice_client


async def test_callout_stale_after_a_slow_connect_is_dropped(tmp_path):
    channel = SlowChannel(0.3)
    player = DiscordPlayer("tok", 123, StubSpeech(), client=ChannelStubClient(channel), max_age=0.1)
    started = time.monotonic()
    await player.play(fresh())  # StubSpeech raises if it gets as far as synthesis
    assert time.monotonic() - started < 0.25  # gave up at the deadline, not after the join
    await asyncio.sleep(0.3)
    assert player.connected  # the join itself carried on in the background
    await player.close()


async def test_callout_own_max_age_overrides_the_players(tmp_path):
    vc = FakeVoiceClient("finish")
    channel = SlowChannel(0.2, vc)
    path = write_wav(tmp_path / "clip.wav")
    player = DiscordPlayer(
        "tok",
        123,
        WavSpeech(path),
        client=ChannelStubClient(channel),
        max_age=0.05,
        source_factory=FakeSource,
    )
    await player.play(fresh(max_age=5.0))
    assert len(vc.played) == 1


async def test_slow_connect_does_not_pause_ingest():
    channel = SlowChannel(5.0)
    player = DiscordPlayer("tok", 123, StubSpeech(), client=ChannelStubClient(channel))
    processed = []

    async def handle(state):
        processed.append(state.t)  # stands in for engine.process
        await player.on_phase(state.phase, state.t)

    states = asyncio.Queue()
    for t in range(100):
        states.put_nowait(make_state(t=1000.0 + t))
    task = asyncio.create_task(ingest_loop(states, handle))
    for _ in range(100):
        if len(processed) == 100:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert len(processed) == 100
    assert not player.connected and player._connect_task is not None
    await player.close()


async def test_idle_disconnect_without_any_frames():
    vc = StubVoiceClient(True)
    states = []
    player = DiscordPlayer(
        "tok",
        123,
        StubSpeech(),
        client=StubClient(),
        idle_disconnect_secs=600,
        on_voice_state=states.append,
    )
    player._vc = vc
    await player.on_phase(Phase.IN_RACE, 100.0)  # last frame, then the PS5 goes off
    await player.check_idle(500.0)
    assert player.connected
    await player.check_idle(701.0)
    assert not player.connected and vc.force_disconnects == 1 and states == [False]


async def test_idle_clock_starts_at_first_check_when_joined_without_frames():
    vc = StubVoiceClient(True)
    player = DiscordPlayer("tok", 123, StubSpeech(), client=StubClient(), idle_disconnect_secs=10)
    player._vc = vc
    await player.check_idle(100.0)
    await player.check_idle(105.0)
    assert player.connected
    await player.check_idle(111.0)
    assert not player.connected
