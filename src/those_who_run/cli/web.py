"""``those-who-run web``: the pit wall, served by Streamlit."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from those_who_run import brand
from those_who_run.config import ConfigError, Settings

log = logging.getLogger("those_who_run")

HELP = "the pit wall: browse sessions and laps in GT7_DATA_DIR (needs the web extra)"
SETTINGS: tuple[str, ...] = ("GT7_WEB_PORT",)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port", type=int, default=None, help="port to listen on (GT7_WEB_PORT, default 8501)"
    )
    parser.add_argument(
        "--address", default="0.0.0.0", help="address to listen on (default all, for a container)"
    )


def run(args: argparse.Namespace, settings: Settings) -> int:
    return run_web(settings, args.port or settings.web_port, args.address)


def run_web(settings: Settings, port: int, address: str) -> int:
    """Serve the pit wall with ``streamlit run``. Streamlit is imported here only,
    so the engineer runs without the web extra installed."""
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as exc:
        raise ConfigError("the pit wall needs Streamlit: pip install 'those-who-run[web]'") from exc
    from those_who_run import pitwall

    script = Path(pitwall.__file__).with_name("app.py")
    os.environ["GT7_DATA_DIR"] = str(settings.data_dir.resolve())  # read again by the app
    log.info("pit wall on http://%s:%d, reading %s", address, port, settings.data_dir)
    return (
        streamlit_cli.main(
            ["run", str(script), *streamlit_flags(port, address)],
            prog_name="streamlit",
            standalone_mode=False,
        )
        or 0
    )


def streamlit_flags(port: int, address: str) -> list[str]:
    """Server and theme options for ``streamlit run``: headless, no file watching
    or usage stats, and the livery."""
    return [
        f"--server.port={port}",
        f"--server.address={address}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--theme.base=dark",
        f"--theme.primaryColor={brand.hex_colour(brand.ACCENT)}",
        f"--theme.backgroundColor={brand.hex_colour(brand.BACKGROUND)}",
        f"--theme.secondaryBackgroundColor={brand.hex_colour(brand.PANEL)}",
        f"--theme.textColor={brand.hex_colour(brand.TEXT)}",
    ]
