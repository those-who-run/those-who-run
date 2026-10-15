import json
import urllib.request

import pytest

from those_who_run.config import ConfigError, Settings, deep_merge, load_rules_config
from those_who_run.metrics import HealthServer, Metrics


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


def test_health_server_serves_metrics_and_health():
    m = Metrics()
    m.in_race.set(1)
    srv = HealthServer(0, m, lambda: {"ok": True, "telemetry_connected": False})
    srv.start()
    try:
        port = srv.bound_port
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as r:
            assert b"gt7_in_race 1.0" in r.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz") as r:
            assert json.load(r)["telemetry_connected"] is False
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope")
    finally:
        srv.stop()
