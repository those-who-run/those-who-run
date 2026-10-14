"""Command line entry point: run, replay, record."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from gt7_race_engineer import __version__
from gt7_race_engineer.callouts import CalloutQueue
from gt7_race_engineer.config import ConfigError, Settings, load_rules_config
from gt7_race_engineer.engine import Engine
from gt7_race_engineer.metrics import HealthServer, Metrics
from gt7_race_engineer.rules import build_rules
from gt7_race_engineer.state import Phase, RaceState
from gt7_race_engineer.store import SessionStore

log = logging.getLogger("gt7_race_engineer")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gt7-race-engineer", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    rn = sub.add_parser("run", help="live: PS5 telemetry in, Discord voice out")
    rn.add_argument(
        "--record", type=Path, help="also append every telemetry frame to this JSONL file"
    )

    sy = sub.add_parser("say", help="join the voice channel, speak a phrase, leave (audio test)")
    sy.add_argument("text", nargs="?", default="Radio check. Race engineer online.")

    rp = sub.add_parser("replay", help="run the rules over a recording, no PS5 or Discord needed")
    rp.add_argument("recording", type=Path)
    rp.add_argument("--wav-out", type=Path, help="also synthesise each callout into this directory")
    rp.add_argument("--realtime", action="store_true", help="sleep to match the recording's timing")

    rc = sub.add_parser("record", help="capture live telemetry to a JSONL file for later replay")
    rc.add_argument("output", type=Path)
    rc.add_argument("--ps5-ip", help="override GT7_PS5_IP; omit both to use broadcast discovery")
    rc.add_argument(
        "--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        if args.command == "run":
            return asyncio.run(run_live(settings, record=args.record))
        if args.command == "say":
            return asyncio.run(run_say(settings, args.text))
        if args.command == "replay":
            return asyncio.run(run_replay(settings, args.recording, args.wav_out, args.realtime))
        if args.command == "record":
            return asyncio.run(run_record(settings, args.output, args.ps5_ip, args.seconds))
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
    except KeyboardInterrupt:
        return 130
    return 1


async def run_replay(
    settings: Settings, recording: Path, wav_out: Path | None, realtime: bool
) -> int:
    from gt7_race_engineer.audio.player import ConsolePlayer, WavDirPlayer
    from gt7_race_engineer.replay import read_recording, replay, summarise

    rules_cfg = load_rules_config(settings.rules_file)
    queue = CalloutQueue(max_age=None)
    engine = Engine(build_rules(rules_cfg["rules"]), queue, SessionStore(settings.data_dir))
    if wav_out is not None:
        from gt7_race_engineer.speech import PiperSpeech

        speech = PiperSpeech(settings.voice_model, wav_out / ".cache", rules_cfg["voice"])
        player: ConsolePlayer = WavDirPlayer(speech, wav_out)
    else:
        player = ConsolePlayer()
    spoken = await replay(read_recording(recording), engine, player, realtime=realtime)
    log.info("replay summary: %s", summarise(spoken, queue))
    return 0


async def run_record(settings: Settings, output: Path, ps5_ip: str | None, seconds: float) -> int:
    from gt7_race_engineer.replay import RecordingWriter
    from gt7_race_engineer.telemetry import LiveTelemetry

    ip = ps5_ip or settings.ps5_ip
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(ip, queue, loop, discover=ip is None)
    writer = RecordingWriter(output)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    telem.start()
    deadline = time.monotonic() + seconds if seconds > 0 else None
    log.info("recording to %s (Ctrl-C to stop)", output)
    try:
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            try:
                state = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            writer.write(state)
    finally:
        writer.close()
        await telem.stop()
        log.info("wrote %d states to %s", writer.count, output)
    return 0


async def run_say(settings: Settings, text: str) -> int:
    """Audio path test: no telemetry involved."""
    from gt7_race_engineer.audio.discord_player import DiscordPlayer
    from gt7_race_engineer.callouts import Callout
    from gt7_race_engineer.speech import PiperSpeech

    if not settings.discord_token or not settings.discord_channel_id:
        raise ConfigError("DISCORD_BOT_TOKEN and DISCORD_VOICE_CHANNEL_ID are required")
    rules_cfg = load_rules_config(settings.rules_file)
    speech = PiperSpeech(
        settings.voice_model, Path("/tmp/gt7-race-engineer/cache"), rules_cfg["voice"]
    )
    player = DiscordPlayer(settings.discord_token, settings.discord_channel_id, speech)
    await player.start()
    try:
        await player.on_phase(Phase.AT_TRACK, time.monotonic())
        if not player.connected:
            log.error("could not join the voice channel, see errors above")
            return 1
        await player.play(Callout(text=text, priority=0, rule="say", created_at=time.monotonic()))
        await asyncio.sleep(0.5)
    finally:
        await player.close()
    return 0


async def run_live(settings: Settings, record: Path | None = None) -> int:
    from gt7_race_engineer.audio.discord_player import DiscordPlayer
    from gt7_race_engineer.replay import RecordingWriter
    from gt7_race_engineer.speech import PiperSpeech
    from gt7_race_engineer.telemetry import LiveTelemetry

    settings.require_live()
    assert settings.ps5_ip and settings.discord_token and settings.discord_channel_id
    rules_cfg = load_rules_config(settings.rules_file)
    rules = build_rules(rules_cfg["rules"])
    metrics = Metrics()
    queue = CalloutQueue(max_age=float(rules_cfg["queue"]["max_age_seconds"]))
    recorder = SessionStore(settings.data_dir)
    engine = Engine(rules, queue, recorder, metrics)
    speech = PiperSpeech(
        settings.voice_model,
        Path("/tmp/gt7-race-engineer/cache"),
        rules_cfg["voice"],
        on_duration=metrics.speech_seconds.observe,
    )
    player = DiscordPlayer(
        settings.discord_token,
        settings.discord_channel_id,
        speech,
        idle_disconnect_secs=settings.idle_disconnect_secs,
        on_voice_state=lambda up: metrics.voice_connected.set(1 if up else 0),
    )
    loop = asyncio.get_running_loop()
    states: asyncio.Queue[RaceState] = asyncio.Queue(maxsize=600)
    telem = LiveTelemetry(settings.ps5_ip, states, loop)

    def health() -> dict:
        return {
            "ok": True,
            "telemetry_connected": telem.connected(settings.telemetry_timeout_secs),
            "voice_connected": player.connected,
            "packets": telem.packets,
            "races_started": engine.races_started,
            "queue": len(queue),
        }

    http = HealthServer(settings.metrics_port, metrics, health)
    http.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    writer = RecordingWriter(record) if record is not None else None
    if writer is not None:
        log.info("recording telemetry frames to %s", record)

    log.info("gt7-race-engineer %s starting", __version__)
    # Pre-warm the voice so the first callout is not late.
    await loop.run_in_executor(None, speech.synthesize, "Race engineer online.")
    await player.start()
    telem.start()

    async def ingest() -> None:
        while True:
            state = await states.get()
            if writer is not None:
                writer.write(state)
            engine.process(state)
            await player.on_phase(state.phase, state.t)

    async def speak() -> None:
        while True:
            c = queue.pop(time.monotonic())
            if c is None:
                await asyncio.sleep(0.05)
                continue
            await player.play(c)

    async def watchdog() -> None:
        was: bool | None = None
        log.info("telemetry: waiting for packets from %s", settings.ps5_ip)
        while True:
            now_connected = telem.connected(settings.telemetry_timeout_secs)
            metrics.telemetry_connected.set(1 if now_connected else 0)
            if now_connected != was and (was is not None or now_connected):
                log.info("telemetry %s", "connected" if now_connected else "lost")
            was = now_connected
            await asyncio.sleep(1)

    tasks = [
        asyncio.create_task(ingest(), name="ingest"),
        asyncio.create_task(speak(), name="speak"),
        asyncio.create_task(watchdog(), name="watchdog"),
    ]
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await player.close()
        await telem.stop()
        http.stop()
        if writer is not None:
            writer.close()
            log.info("recorded %d frames to %s", writer.count, record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
