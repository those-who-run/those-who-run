import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from those_who_run import healthcheck
from those_who_run.__main__ import build_parser, main
from those_who_run.config import Settings
from those_who_run.healthcheck import health_urls, mode_of, pid1_argv, run_healthcheck


def settings(**env: str) -> Settings:
    return Settings.from_env({"GT7_METRICS_PORT": "9850", "GT7_PITWALL_PORT": "9852", **env})


def test_mode_from_pid1_arguments():
    assert (
        mode_of(["/app/.venv/bin/python", "/app/.venv/bin/those-who-run", "pitwall"]) == "pitwall"
    )
    assert mode_of(["those-who-run", "web"]) is None  # the old pit wall's mode went in #238
    assert mode_of(["those-who-run", "run", "--record", "x.jsonl"]) == "run"
    assert mode_of(["those-who-run", "pitwall", "--port", "9900"]) == "pitwall"
    assert mode_of(["sleep", "infinity"]) is None
    assert mode_of([]) is None


def test_urls_follow_mode_and_ports():
    s = settings(GT7_METRICS_PORT="9999", GT7_PITWALL_PORT="9900")
    assert health_urls(s, "run") == ["http://127.0.0.1:9999/healthz"]
    # The pitwall image (#237): the data API's /healthz on GT7_PITWALL_PORT or --port.
    assert health_urls(s, "pitwall") == ["http://127.0.0.1:9900/healthz"]
    assert health_urls(s, "pitwall", ["those-who-run", "pitwall", "--port", "9901"]) == [
        "http://127.0.0.1:9901/healthz"
    ]
    assert health_urls(s, "pitwall", ["those-who-run", "pitwall", "--port=9902"]) == [
        "http://127.0.0.1:9902/healthz"
    ]
    assert health_urls(s, None) == [
        "http://127.0.0.1:9999/healthz",
        "http://127.0.0.1:9900/healthz",
    ]


def test_the_engineer_probe_follows_the_bind_address():
    assert health_urls(settings(GT7_BIND_ADDRESS="::"), "run") == ["http://127.0.0.1:9850/healthz"]
    s = settings(GT7_BIND_ADDRESS="192.0.2.20")
    assert health_urls(s, "run") == ["http://192.0.2.20:9850/healthz"]
    assert health_urls(settings(GT7_BIND_ADDRESS="::1"), "run") == ["http://[::1]:9850/healthz"]


def test_pid1_argv_reads_nul_separated_cmdline(tmp_path: Path):
    f = tmp_path / "cmdline"
    f.write_bytes(b"/usr/bin/python\0those-who-run\0pitwall\0")
    assert pid1_argv(f) == ["/usr/bin/python", "those-who-run", "pitwall"]
    assert pid1_argv(tmp_path / "missing") == []


@pytest.fixture
def server():
    """A local HTTP server answering 200 on /healthz and 503 elsewhere."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200 if self.path == "/healthz" else 503)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_healthy_when_the_mode_endpoint_answers(server, monkeypatch):
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: ["those-who-run", "pitwall"])
    s = settings(GT7_PITWALL_PORT=str(server), GT7_METRICS_PORT="1")
    assert run_healthcheck(s, timeout=0.5) == 0
    assert run_healthcheck(s, mode="run", timeout=0.5) == 1  # nothing on the engineer's port


def test_unknown_mode_accepts_either(server, monkeypatch):
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: [])
    s = settings(GT7_PITWALL_PORT=str(server), GT7_METRICS_PORT="1")
    assert run_healthcheck(s, timeout=0.5) == 0


def test_unhealthy_when_nothing_listens(monkeypatch, capsys):
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: ["those-who-run", "run"])
    assert run_healthcheck(settings(GT7_METRICS_PORT="1"), timeout=0.5) == 1
    assert "unhealthy" in capsys.readouterr().out


def test_cli_subcommand(server, monkeypatch):
    args = build_parser().parse_args(["healthcheck", "--mode", "pitwall", "--timeout", "1"])
    assert (args.mode, args.timeout) == ("pitwall", 1.0)
    with pytest.raises(SystemExit):  # the old pit wall's mode went in #238
        build_parser().parse_args(["healthcheck", "--mode", "web"])
    monkeypatch.setenv("GT7_PITWALL_PORT", str(server))
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: [])
    assert main(["healthcheck", "--mode", "pitwall"]) == 0
