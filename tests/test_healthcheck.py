import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from those_who_run import healthcheck
from those_who_run.__main__ import build_parser, main
from those_who_run.config import Settings
from those_who_run.healthcheck import health_urls, mode_of, pid1_argv, run_healthcheck


def settings(**env: str) -> Settings:
    return Settings.from_env({"GT7_METRICS_PORT": "9850", "GT7_WEB_PORT": "8501", **env})


def test_mode_from_pid1_arguments():
    assert mode_of(["/app/.venv/bin/python", "/app/.venv/bin/those-who-run", "web"]) == "web"
    assert mode_of(["those-who-run", "run", "--record", "x.jsonl"]) == "run"
    assert mode_of(["sleep", "infinity"]) is None
    assert mode_of([]) is None


def test_urls_follow_mode_and_ports():
    s = settings(GT7_METRICS_PORT="9999", GT7_WEB_PORT="8600")
    assert health_urls(s, "run") == ["http://127.0.0.1:9999/healthz"]
    assert health_urls(s, "web") == ["http://127.0.0.1:8600/_stcore/health"]
    assert health_urls(s, "web", ["those-who-run", "web", "--port", "8700"]) == [
        "http://127.0.0.1:8700/_stcore/health"
    ]
    assert health_urls(s, "web", ["those-who-run", "web", "--port=8701"]) == [
        "http://127.0.0.1:8701/_stcore/health"
    ]
    assert health_urls(s, None) == [
        "http://127.0.0.1:9999/healthz",
        "http://127.0.0.1:8600/_stcore/health",
    ]


def test_pid1_argv_reads_nul_separated_cmdline(tmp_path: Path):
    f = tmp_path / "cmdline"
    f.write_bytes(b"/usr/bin/python\0those-who-run\0web\0")
    assert pid1_argv(f) == ["/usr/bin/python", "those-who-run", "web"]
    assert pid1_argv(tmp_path / "missing") == []


@pytest.fixture
def server():
    """A local HTTP server answering 200 on /_stcore/health and 503 elsewhere."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200 if self.path == "/_stcore/health" else 503)
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
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: ["those-who-run", "web"])
    s = settings(GT7_WEB_PORT=str(server), GT7_METRICS_PORT=str(server))
    assert run_healthcheck(s) == 0
    assert run_healthcheck(s, mode="run") == 1  # /healthz answers 503 here


def test_unknown_mode_accepts_either(server, monkeypatch):
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: [])
    s = settings(GT7_WEB_PORT=str(server), GT7_METRICS_PORT="1")
    assert run_healthcheck(s, timeout=0.5) == 0


def test_unhealthy_when_nothing_listens(monkeypatch, capsys):
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: ["those-who-run", "run"])
    assert run_healthcheck(settings(GT7_METRICS_PORT="1"), timeout=0.5) == 1
    assert "unhealthy" in capsys.readouterr().out


def test_cli_subcommand(server, monkeypatch):
    args = build_parser().parse_args(["healthcheck", "--mode", "web", "--timeout", "1"])
    assert (args.mode, args.timeout) == ("web", 1.0)
    monkeypatch.setenv("GT7_WEB_PORT", str(server))
    monkeypatch.setattr(healthcheck, "pid1_argv", lambda: [])
    assert main(["healthcheck", "--mode", "web"]) == 0
