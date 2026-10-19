"""``those-who-run healthcheck``: the container's HEALTHCHECK, for ``run`` and
``pitwall``.

The engineer (``run``) answers ``/healthz`` on GT7_METRICS_PORT; the pit wall
(``pitwall``, the pitwall image) answers ``/healthz`` on GT7_PITWALL_PORT or its
``--port``. The mode comes from the container's main
process (PID 1), so one HEALTHCHECK serves every mode. Standard library only: no curl in the image.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from those_who_run.config import Settings

MODES = ("run", "pitwall")


def mode_of(argv: Sequence[str]) -> str | None:
    """``run`` or ``pitwall`` from a process's arguments, None when it is none."""
    for arg in argv:
        if arg in MODES:
            return arg
    return None


def _port_flag(argv: Sequence[str]) -> int | None:
    for i, arg in enumerate(argv):
        value = None
        if arg == "--port" and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--port="):
            value = arg.split("=", 1)[1]
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _engine_host(bind: str) -> str:
    """Where the engineer answers: loopback when it listens on every address,
    else the one address it is bound to (GT7_BIND_ADDRESS)."""
    if bind in ("", "0.0.0.0", "::"):
        return "127.0.0.1"
    return f"[{bind}]" if ":" in bind else bind


def health_urls(settings: Settings, mode: str | None, argv: Sequence[str] = ()) -> list[str]:
    """The URLs to probe: one for a known mode, both when the mode is unknown."""
    run_url = f"http://{_engine_host(settings.bind_address)}:{settings.metrics_port}/healthz"
    pitwall_url = f"http://127.0.0.1:{_port_flag(argv) or settings.pitwall_port}/healthz"
    if mode == "run":
        return [run_url]
    if mode == "pitwall":
        return [pitwall_url]
    return [run_url, pitwall_url]


def pid1_argv(proc: Path = Path("/proc/1/cmdline")) -> list[str]:
    try:
        raw = proc.read_bytes()
    except OSError:
        return []
    return [a.decode(errors="replace") for a in raw.split(b"\0") if a]


def probe(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (localhost only)
            return 200 <= resp.status < 300
    except urllib.error.URLError, OSError, ValueError:
        return False


def run_healthcheck(settings: Settings, mode: str | None = None, timeout: float = 2.0) -> int:
    """0 when the mode's endpoint answers 2xx (any, when the mode is unknown), else 1."""
    argv = pid1_argv()
    mode = mode or mode_of(argv)
    urls = health_urls(settings, mode, argv)
    for url in urls:
        if probe(url, timeout):
            return 0
    print(f"unhealthy: no answer from {', '.join(urls)}")
    return 1
