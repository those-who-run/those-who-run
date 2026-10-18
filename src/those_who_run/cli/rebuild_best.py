"""``those-who-run rebuild-best``: recompute each stored session's best lap."""

from __future__ import annotations

import argparse

from those_who_run.config import ConfigError, Settings

HELP = "recompute each stored session's best lap from its summary (stores from 0.4.0)"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    pass


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.results import race_time
    from those_who_run.store import rebuild_best_laps

    if not (settings.data_dir / "index.sqlite").exists():
        raise ConfigError(f"{settings.data_dir}: no index.sqlite")
    fixes = rebuild_best_laps(settings.data_dir)
    for f in fixes:
        before = race_time(f.before) if f.before else "-"
        after = race_time(f.after) if f.after else "-"
        print(f"{f.session_id}  {before} -> {after}")
    print(f"\n{len(fixes)} session(s) corrected")
    return 0
