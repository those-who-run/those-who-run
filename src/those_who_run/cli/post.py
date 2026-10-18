"""``those-who-run post``: post a stored session's results card."""

from __future__ import annotations

import argparse
import asyncio
import json

from those_who_run.config import ConfigError, Settings
from those_who_run.store import SessionStore

HELP = "post a stored session's results card to DISCORD_RESULTS_CHANNEL_ID"
SETTINGS: tuple[str, ...] = ("DISCORD_RESULTS_CHANNEL_ID",)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("session_id", help="a directory name under GT7_DATA_DIR/sessions")
    parser.add_argument("--dry-run", action="store_true", help="print the card, post nothing")


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(run_post(settings, args.session_id, args.dry_run))


async def run_post(settings: Settings, session_id: str, dry_run: bool) -> int:
    import discord

    from those_who_run.results import ResultsPoster, build_card

    path = settings.data_dir / "sessions" / session_id / "summary.json"
    if not path.exists():
        raise ConfigError(f"{path}: no such session summary")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: not valid JSON: {exc}") from exc
    card = build_card(summary, settings.pitwall_url)
    if card is None:
        print("no full lap: nothing to post")
        return 1
    print(card.title)
    if card.url:
        print(card.url)
    print(card.description)
    for name, value in card.fields:
        print(f"  {name}: {value}")
    if dry_run:
        return 0
    if not settings.discord_token or not settings.results_channel_id:
        raise ConfigError("posting needs DISCORD_BOT_TOKEN and DISCORD_RESULTS_CHANNEL_ID")
    # Recording the post writes the index: refused (StoreBusy) while the engineer runs.
    store = SessionStore(settings.data_dir)
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(settings.discord_token)  # HTTP only: no gateway needed to post
        poster = ResultsPoster(client, settings.results_channel_id, on_posted=store.mark_posted)
        ok = await poster.post(session_id, card)
    finally:
        await client.close()
        store.close()
    return 0 if ok else 1
