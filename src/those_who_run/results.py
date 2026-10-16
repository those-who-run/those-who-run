"""Results cards: a Discord post for every session with a completed lap.

``build_card`` turns a session summary (``summary.json``) into a ``Card``; it is
pure and decides everything that ends up on screen. ``ResultsPoster`` sends
cards to a text channel from a queue, so the engine never waits on Discord,
retrying a few times before giving up. The voice bot's client is reused: one
login, no privileged intents. The bot needs View Channel, Send Messages and
Embed Links on the results channel.

Position is only shown where the engineer would say it: a field that GT7
flags (see ``Rule.has_field``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from those_who_run import brand

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Card:
    title: str
    description: str
    fields: tuple[tuple[str, str], ...]
    colour: int
    footer: str
    timestamp: datetime | None = None


def race_time(ms: int) -> str:
    """``96595`` -> "1:36.595"; ``49677`` -> "49.677"; ``3723456`` -> "1:02:03.456"."""
    seconds, millis = divmod(int(ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    if not minutes:
        return f"{seconds}.{millis:03d}"
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def build_card(summary: dict[str, Any]) -> Card | None:
    """The card for a session, or None when it is not worth posting (no full lap)."""
    laps = int(summary.get("laps_completed") or 0)
    if laps < 1:
        return None
    kind_rec = summary.get("session_kind") or {}
    kind = kind_rec.get("kind") or "unknown"
    total_laps = int(summary.get("total_laps") or 0)
    flagged_field = bool(kind_rec.get("field")) and bool(kind_rec.get("cars_on_track"))
    position = summary.get("final_position") if flagged_field else None
    cars = summary.get("total_cars")
    finished = bool(summary.get("finished"))

    title = f"{_track(summary.get('track'))} · {_kind_label(kind, total_laps, summary)}"

    of_cars = f" of {cars}" if cars else ""
    if finished:
        total = summary.get("total_time_ms")
        result = f"Finished P{position}{of_cars}" if position else "Finished"
        if total:
            result += f" in {race_time(total)}"
    elif kind == "lap_race" and total_laps:
        result = f"Retired on lap {min(laps + 1, total_laps)} of {total_laps}"
        if position:
            result += f", running P{position}"
    else:
        result = f"{laps} lap" + ("" if laps == 1 else "s")
        if position:
            result += f", P{position}{of_cars}"

    fields: list[tuple[str, str]] = []
    best_lap = _best_lap(summary.get("laps", []), skip_lap_1=kind == "lap_race")
    if best_lap is not None:
        lap_no, best = best_lap
        fields.append(("Best lap", f"{race_time(best)} (lap {lap_no})"))
    car = summary.get("car_name")
    if car:
        fields.append(("Car", car))
    used = summary.get("fuel_burned", summary.get("fuel_used")) or 0
    capacity = summary.get("fuel_capacity") or 0
    if kind_rec.get("fuel_use") and used > 0 and capacity > 0:
        fields.append(("Fuel used", f"{round(100 * used / capacity)}%"))

    started = summary.get("started_at")
    return Card(
        title=title,
        description=f"{brand.GLYPH_FLAG} {result}" if finished else result,
        fields=tuple(fields),
        colour=brand.ADVAN_RED if finished else brand.CARBON_GREY,
        footer=f"{brand.NAME} {brand.KANJI} · session {summary.get('session_id', '?')}",
        timestamp=datetime.fromtimestamp(started, UTC) if started else None,
    )


def _best_lap(laps: list[dict[str, Any]], skip_lap_1: bool) -> tuple[int, int] | None:
    """(lap, time) of the quickest complete lap. In a lap race lap 1 starts from the
    grid or behind the pace and is skipped when there are others, as the spoken
    summary does: at Suzuka East it was short, starting ahead of the line."""
    timed = [
        (x["lap"], x["lap_time_ms"]) for x in laps if x.get("complete") and x.get("lap_time_ms")
    ]
    if skip_lap_1 and any(lap != 1 for lap, _ in timed):
        timed = [(lap, ms) for lap, ms in timed if lap != 1]
    return min(timed, key=lambda x: x[1]) if timed else None


def _track(rec: dict[str, Any] | None) -> str:
    if not rec:
        return "Unknown track"
    if rec.get("confidence") in ("probable", "confirmed") and rec.get("name"):
        return str(rec["name"])
    if rec.get("family"):
        return str(rec["family"])
    return "Unknown track"


def _kind_label(kind: str, total_laps: int, summary: dict[str, Any]) -> str:
    if kind == "lap_race":
        return f"{total_laps}-lap race"
    if kind == "timed_field":
        return "timed race"
    if kind == "solo_timed":
        return "time trial"
    if kind == "solo_laps":
        return f"{total_laps}-lap run"
    return {"race": "race", "time_trial": "time trial", "practice": "practice"}.get(
        str(summary.get("type")), "session"
    )


def to_embed(card: Card) -> Any:
    import discord

    embed = discord.Embed(
        title=card.title,
        description=card.description,
        colour=card.colour,
        timestamp=card.timestamp,
    )
    for name, value in card.fields:
        embed.add_field(name=name, value=value, inline=True)
    embed.set_footer(text=card.footer)
    return embed


@dataclass
class ResultsPoster:
    """Sends results cards to one text channel, in order, off the engine's path."""

    client: Any  # a logged-in discord.Client
    channel_id: int
    on_posted: Callable[[str], None] | None = None  # session id, after a card is sent
    on_result: Callable[[str], None] | None = None  # "ok", "failed" or "skipped"
    retries: int = 3
    backoff_secs: float = 2.0
    _queue: asyncio.Queue[tuple[str, Card]] = field(default_factory=asyncio.Queue)

    def submit(self, summary: dict[str, Any]) -> None:
        """Queue the card for a finished session. Safe to call from the event loop."""
        card = build_card(summary)
        if card is None:
            log.info("results: session %s has no full lap, not posted", summary.get("session_id"))
            self._result("skipped")
            return
        self._queue.put_nowait((str(summary.get("session_id")), card))

    async def run(self) -> None:
        while True:
            session_id, card = await self._queue.get()
            await self.post(session_id, card)

    async def post(self, session_id: str, card: Card) -> bool:
        delay = self.backoff_secs
        for attempt in range(1, self.retries + 1):
            try:
                channel = self.client.get_channel(self.channel_id)
                if channel is None:
                    channel = await self.client.fetch_channel(self.channel_id)
                await channel.send(embed=to_embed(card))
            except Exception:  # noqa: BLE001
                log.exception(
                    "results: post for %s failed (attempt %d/%d)", session_id, attempt, self.retries
                )
                if attempt < self.retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                continue
            log.info("results: posted %s: %s", session_id, card.title)
            self._result("ok")
            if self.on_posted is not None:
                self.on_posted(session_id)
            return True
        self._result("failed")
        return False

    def _result(self, result: str) -> None:
        if self.on_result is not None:
            self.on_result(result)
