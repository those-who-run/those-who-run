"""Startup: one-line errors for bad settings and known failures, and a stop that
works while the engineer is still connecting."""

import asyncio
import errno
import json
import logging
import os
import signal

import discord
import pytest
from gt_telem.errors.playstation_errors import PlayStationNotFoundError

from those_who_run import __main__ as cli
from those_who_run.config import ConfigError, LiveSettings, Settings

LIVE_ENV = {
    "GT7_PS5_IP": "192.0.2.108",
    "DISCORD_BOT_TOKEN": "x",
    "DISCORD_VOICE_CHANNEL_ID": "123",
}


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in (*Settings.PARSED, "GT7_PS5_IP", "DISCORD_BOT_TOKEN", "GT7_RULES_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GT7_VOICE_MODEL", str(tmp_path / "missing.onnx"))
    return monkeypatch


# settings


@pytest.mark.parametrize(
    "name, value, message",
    [
        ("GT7_METRICS_PORT", "nine", "must be an integer"),
        ("GT7_METRICS_PORT", "0", "between 1 and 65535"),
        ("GT7_WEB_PORT", "70000", "between 1 and 65535"),
        ("GT7_RECORD_KEEP", "-1", "0 or more"),
        ("GT7_IDLE_DISCONNECT_SECS", "soon", "must be a number"),
        ("GT7_IDLE_DISCONNECT_SECS", "-5", "0 or more"),
        ("GT7_TELEMETRY_TIMEOUT_SECS", "0", "more than 0"),
        ("GT7_TELEMETRY_TIMEOUT_SECS", "nan", "finite"),
        ("DISCORD_VOICE_CHANNEL_ID", "-3", "channel id"),
        ("LOG_LEVEL", "LOUD", "must be one of"),
        ("GT7_CACHE_MAX_MB", "-1", "0 or more"),
        ("LOG_LEVEL", "BASIC_FORMAT", "must be one of"),
    ],
)
def test_invalid_values_name_the_variable(name, value, message):
    with pytest.raises(ConfigError, match=f"{name}.*{message}"):
        Settings.from_env({name: value})


def test_valid_values_and_level_aliases():
    s = Settings.from_env(
        {
            "GT7_METRICS_PORT": "65535",
            "GT7_RECORD_KEEP": "0",
            "GT7_IDLE_DISCONNECT_SECS": "0",
            "GT7_TELEMETRY_TIMEOUT_SECS": "0.5",
            "LOG_LEVEL": " warning ",
        }
    )
    assert (s.metrics_port, s.record_keep, s.idle_disconnect_secs) == (65535, 0, 0.0)
    assert s.telemetry_timeout_secs == 0.5 and s.log_level == "WARNING"


def test_check_limits_validation_to_the_named_variables():
    s = Settings.from_env({"GT7_METRICS_PORT": "x", "LOG_LEVEL": "debug"}, check=("LOG_LEVEL",))
    assert s.metrics_port == 9850 and s.log_level == "DEBUG"
    with pytest.raises(ConfigError, match="GT7_METRICS_PORT"):
        Settings.from_env({"GT7_METRICS_PORT": "x"}, check=("GT7_METRICS_PORT",))


def test_require_live_returns_typed_settings():
    live = Settings.from_env(LIVE_ENV).require_live()
    assert live == LiveSettings("192.0.2.108", "x", 123)


# the command line


def test_bad_port_exits_non_zero_naming_it(clean_env, capsys):
    clean_env.setenv("GT7_METRICS_PORT", "99999")
    assert cli.main(["run"]) == 2
    err = capsys.readouterr().err
    assert "GT7_METRICS_PORT" in err and "Traceback" not in err


def test_bad_channel_id_exits_non_zero_naming_it(clean_env, capsys):
    clean_env.setenv("DISCORD_VOICE_CHANNEL_ID", "abc")
    assert cli.main(["say"]) == 2
    assert "DISCORD_VOICE_CHANNEL_ID" in capsys.readouterr().err


def test_bad_log_level_exits_non_zero_naming_it(clean_env, capsys):
    clean_env.setenv("LOG_LEVEL", "LOUD")
    assert cli.main(["cars", "list"]) == 2
    assert "LOG_LEVEL" in capsys.readouterr().err


def test_cars_list_runs_with_a_bad_channel_id(clean_env, capsys):
    clean_env.setenv("DISCORD_VOICE_CHANNEL_ID", "abc")
    clean_env.setenv("GT7_METRICS_PORT", "nope")
    assert cli.main(["cars", "list"]) == 0
    assert capsys.readouterr().out


def test_missing_voice_model_is_one_line(clean_env, caplog):
    for k, v in LIVE_ENV.items():
        clean_env.setenv(k, v)
    assert cli.main(["run"]) == 2
    messages = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("voice model not found" in m and "GT7_VOICE_MODEL" in m for m in messages)
    assert not any(r.exc_info for r in caplog.records)


def test_post_with_a_corrupt_summary_is_one_line(clean_env, tmp_path, caplog):
    session = tmp_path / "data" / "sessions" / "s1"
    session.mkdir(parents=True)
    (session / "summary.json").write_text("{not json")
    assert cli.main(["post", "s1", "--dry-run"]) == 2
    assert any("not valid JSON" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "exc, text, code",
    [
        (ConfigError("bad"), "configuration error: bad", 2),
        (discord.LoginFailure("Improper token"), "DISCORD_BOT_TOKEN", 2),
        (OSError(errno.EADDRINUSE, "Address already in use"), "port already in use", 1),
        (PlayStationNotFoundError("none"), "GT7_PS5_IP", 1),
        (FileNotFoundError(2, "No such file", "voices/x.onnx.json"), "voices/x.onnx.json", 1),
    ],
)
def test_known_failures(exc, text, code):
    message, got = cli.known_failure(exc)
    assert text in message and got == code


def test_unknown_failures_keep_their_traceback():
    assert cli.known_failure(RuntimeError("bug")) is None
    assert cli.known_failure(KeyError("x")) is None
    # post names the file itself; a stray JSON error elsewhere is a bug
    assert cli.known_failure(json.JSONDecodeError("Expecting value", "x", 0)) is None


def test_known_failure_traceback_is_kept_at_debug(clean_env, monkeypatch, caplog):
    def boom(args, settings):
        raise FileNotFoundError(2, "No such file", "voices/x.onnx.json")

    monkeypatch.setattr(cli, "dispatch", boom)
    with caplog.at_level(logging.DEBUG, logger="those_who_run"):
        assert cli.main(["cars", "list"]) == 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert len(errors) == 1 and not errors[0].exc_info
    assert debug and isinstance(debug[0].exc_info[1], FileNotFoundError)


def test_main_turns_a_known_failure_into_an_exit_code(clean_env, monkeypatch, caplog):
    def boom(args, settings):
        raise discord.LoginFailure("Improper token has been passed.")

    monkeypatch.setattr(cli, "dispatch", boom)
    assert cli.main(["cars", "list"]) == 2
    assert any("DISCORD_BOT_TOKEN" in r.getMessage() for r in caplog.records)


def test_main_lets_a_bug_raise(clean_env, monkeypatch):
    def boom(args, settings):
        raise RuntimeError("bug")

    monkeypatch.setattr(cli, "dispatch", boom)
    with pytest.raises(RuntimeError):
        cli.main(["cars", "list"])


# stopping during startup


async def test_until_stopped():
    stop = asyncio.Event()

    async def quick():
        return 1

    assert await cli.until_stopped(quick(), stop) is True

    async def failing():
        raise ConfigError("no")

    with pytest.raises(ConfigError):
        await cli.until_stopped(failing(), stop)

    cancelled = []

    async def hang():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    asyncio.get_running_loop().call_later(0.05, stop.set)
    assert await asyncio.wait_for(cli.until_stopped(hang(), stop), 2) is False
    assert cancelled == [True]


class HangingPlayer:
    """start() never returns, like wait_until_ready with Discord unreachable."""

    instances = []

    def __init__(self, *a, **kw):
        self.closed = False
        self.connected = False
        HangingPlayer.instances.append(self)

    async def start(self):
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


class IdleSpeech:
    def __init__(self, *a, **kw):
        pass

    def synthesize(self, text):
        return None


class IdleTelemetry:
    def __init__(self, *a, **kw):
        self.packets = 0
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def connected(self, timeout):
        return False


@pytest.fixture
def hanging_live(monkeypatch, tmp_path):
    import those_who_run.audio.discord_player as dp
    import those_who_run.speech as speech
    import those_who_run.telemetry as telemetry

    HangingPlayer.instances = []
    monkeypatch.setattr(dp, "DiscordPlayer", HangingPlayer)
    monkeypatch.setattr(speech, "PiperSpeech", IdleSpeech)
    monkeypatch.setattr(telemetry, "LiveTelemetry", IdleTelemetry)
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"")
    return Settings(
        ps5_ip="192.0.2.108",
        discord_token="x",
        discord_channel_id=123,
        rules_file=None,
        data_dir=tmp_path / "data",
        voice_model=model,
        metrics_port=0,
        idle_disconnect_secs=600,
        telemetry_timeout_secs=3,
        log_level="INFO",
    )


async def test_stop_ends_run_live_while_player_start_hangs(hanging_live):
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, stop.set)
    assert await asyncio.wait_for(cli.run_live(hanging_live, stop=stop), 5) == 0
    assert HangingPlayer.instances[0].closed


async def test_sigterm_ends_run_live_while_player_start_hangs(hanging_live):
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGTERM)
    assert await asyncio.wait_for(cli.run_live(hanging_live), 5) == 0
    assert HangingPlayer.instances[0].closed
    # the handlers are removed again on the way out
    assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, signal.default_int_handler)


def test_the_cache_dir_check_applies_only_to_commands_that_speak(tmp_path):
    env = {"GT7_DATA_DIR": str(tmp_path), "GT7_CACHE_DIR": str(tmp_path / "cache")}
    with pytest.raises(ConfigError, match="GT7_CACHE_DIR"):
        Settings.from_env(env)
    with pytest.raises(ConfigError, match="GT7_CACHE_DIR"):
        Settings.from_env(env, check=cli.SETTINGS_USED["say"])
    Settings.from_env(env, check=("LOG_LEVEL",))  # cars, tracks and the rest


class SlowClosePlayer(HangingPlayer):
    """Checks, while closing, that data is flushed and a second SIGTERM is safe."""

    seen = {}

    async def close(self):
        handler = signal.getsignal(signal.SIGTERM)
        SlowClosePlayer.seen["handler_installed"] = handler not in (
            signal.SIG_DFL,
            signal.SIG_IGN,
            None,
        )
        if SlowClosePlayer.seen["handler_installed"]:
            os.kill(os.getpid(), signal.SIGTERM)  # a second docker stop
        await asyncio.sleep(0.1)
        self.closed = True


async def test_a_second_sigterm_during_shutdown_does_not_cut_the_flush(
    hanging_live, monkeypatch, tmp_path
):
    import those_who_run.audio.discord_player as dp

    monkeypatch.setattr(dp, "DiscordPlayer", SlowClosePlayer)
    SlowClosePlayer.seen = {}
    record = tmp_path / "rec.jsonl"
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    assert await asyncio.wait_for(cli.run_live(hanging_live, record=record, stop=stop), 5) == 0
    assert SlowClosePlayer.seen == {"handler_installed": True}
    assert record.exists()  # the writer was closed before voice went
    assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, signal.default_int_handler)


async def test_a_hung_voice_close_is_bounded(hanging_live, monkeypatch):
    import those_who_run.audio.discord_player as dp

    class StuckClose(HangingPlayer):
        async def close(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(dp, "DiscordPlayer", StuckClose)
    monkeypatch.setattr(cli, "PLAYER_CLOSE_SECS", 0.1)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    assert await asyncio.wait_for(cli.run_live(hanging_live, stop=stop), 5) == 0
