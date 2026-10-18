"""``those-who-run say``: join the voice channel, speak a phrase, leave."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from those_who_run.config import ConfigError, Settings, load_rules_config

log = logging.getLogger("those_who_run")

HELP = "join the voice channel, speak a phrase, leave (audio test)"
SETTINGS: tuple[str, ...] = ("DISCORD_VOICE_CHANNEL_ID", "GT7_CACHE_DIR", "GT7_CACHE_MAX_MB")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("text", nargs="?", default="Radio check. Race engineer online.")


def run(args: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(run_say(settings, args.text))


async def run_say(settings: Settings, text: str) -> int:
    """Audio path test: no telemetry involved."""
    from those_who_run.audio.discord_player import DiscordPlayer
    from those_who_run.callouts import Callout
    from those_who_run.speech import PiperSpeech

    if not settings.discord_token or not settings.discord_channel_id:
        raise ConfigError("DISCORD_BOT_TOKEN and DISCORD_VOICE_CHANNEL_ID are required")
    rules_cfg = load_rules_config(settings.rules_file)
    speech = PiperSpeech(
        settings.require_voice_model(),
        settings.speech_cache_dir,
        rules_cfg["voice"],
        max_cache_bytes=settings.cache_max_bytes,
    )
    player = DiscordPlayer(settings.discord_token, settings.discord_channel_id, speech)
    await player.start()
    try:
        if not await player.connect():
            log.error("could not join the voice channel, see errors above")
            return 1
        await player.play(Callout(text=text, priority=0, rule="say", created_at=time.monotonic()))
        await asyncio.sleep(0.5)
    finally:
        await player.close()
    return 0
