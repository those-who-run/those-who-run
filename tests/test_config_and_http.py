from pathlib import Path

import pytest

from those_who_run.config import ConfigError, Settings, deep_merge, load_rules_config


def test_settings_from_env():
    s = Settings.from_env(
        {
            "GT7_PS5_IP": "192.0.2.108",
            "DISCORD_BOT_TOKEN": "x",
            "DISCORD_VOICE_CHANNEL_ID": "123",
            "GT7_METRICS_PORT": "9000",
            "LOG_LEVEL": "debug",
        }
    )
    assert s.ps5_ip == "192.0.2.108"
    assert s.discord_channel_id == 123
    assert s.metrics_port == 9000
    assert s.log_level == "DEBUG"
    assert s.record_dir is None and s.record_keep == 20
    s.require_live()
    s = Settings.from_env({"GT7_RECORD_DIR": "/data/recordings", "GT7_RECORD_KEEP": "5"})
    assert str(s.record_dir) == "/data/recordings" and s.record_keep == 5


def test_settings_bind_address_and_control_port():
    s = Settings.from_env({})
    assert (s.bind_address, s.control_port) == ("0.0.0.0", None)  # no control listener
    s = Settings.from_env({"GT7_BIND_ADDRESS": "127.0.0.1", "GT7_CONTROL_PORT": "9851"})
    assert (s.bind_address, s.control_port) == ("127.0.0.1", 9851)
    with pytest.raises(ConfigError, match="GT7_CONTROL_PORT.*between 1 and 65535"):
        Settings.from_env({"GT7_CONTROL_PORT": "0"})


def test_settings_speech_cache_dir_and_cap():
    s = Settings.from_env({"GT7_DATA_DIR": "/data", "HOME": "/tmp"})
    assert s.speech_cache_dir == Path("/tmp/.cache/those-who-run"), "the image: HOME=/tmp"
    assert s.cache_max_bytes == 100 * 1024 * 1024
    s = Settings.from_env({"XDG_CACHE_HOME": "/xdg", "HOME": "/tmp"})
    assert s.speech_cache_dir == Path("/xdg/those-who-run")
    s = Settings.from_env({"GT7_CACHE_DIR": "/var/cache/gt7", "GT7_CACHE_MAX_MB": "20"})
    assert s.speech_cache_dir == Path("/var/cache/gt7")
    assert s.cache_max_bytes == 20 * 1024 * 1024


@pytest.mark.parametrize(
    "env",
    [
        {"GT7_DATA_DIR": "/data", "GT7_CACHE_DIR": "/data/cache"},
        {"GT7_DATA_DIR": "/data", "GT7_CACHE_DIR": "/data"},
        {"GT7_DATA_DIR": "/data", "GT7_CACHE_DIR": "/data/x/../cache"},
        {"GT7_DATA_DIR": "/srv", "XDG_CACHE_HOME": "/srv/.cache"},
    ],
)
def test_settings_refuse_a_speech_cache_inside_the_data_dir(env):
    """The pit wall mounts the data dir read-write (ADR 0001): it must not be able to
    plant clips the engineer plays into Discord."""
    with pytest.raises(ConfigError, match="inside GT7_DATA_DIR"):
        Settings.from_env(env)


def test_settings_missing_live_values():
    s = Settings.from_env({})
    with pytest.raises(
        ConfigError, match="GT7_PS5_IP, DISCORD_BOT_TOKEN, DISCORD_VOICE_CHANNEL_ID"
    ):
        s.require_live()


def test_bad_channel_id():
    with pytest.raises(ConfigError):
        Settings.from_env({"DISCORD_VOICE_CHANNEL_ID": "abc"})


def test_rules_config_merges_over_defaults(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("rules:\n  fuel:\n    thresholds_laps: [4, 2]\n  final_lap:\n    enabled: false\n")
    cfg = load_rules_config(f)
    assert cfg["rules"]["fuel"]["thresholds_laps"] == [4, 2]
    assert cfg["rules"]["fuel"]["rolling_laps"] == 3
    assert cfg["rules"]["final_lap"]["enabled"] is False
    assert cfg["queue"]["max_age_seconds"] == 8.0


def test_rules_config_errors(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_rules_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_rules_config(bad)


def test_deep_merge_does_not_mutate():
    base = {"a": {"b": 1, "c": 2}}
    out = deep_merge(base, {"a": {"b": 9}, "d": 1})
    assert out == {"a": {"b": 9, "c": 2}, "d": 1}
    assert base == {"a": {"b": 1, "c": 2}}
