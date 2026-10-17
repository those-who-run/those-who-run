"""Results cards: a Discord post for every session with a completed lap.

``build_card`` turns a session summary (``summary.json``) into a ``Card``; it is
pure and decides everything that ends up on screen. ``ResultsPoster`` sends
cards to a text channel from a queue, so the engine never waits on Discord,
retrying a few times before giving up (a missing channel or permission is
tried once), and one bad card never stops the next. The voice bot's client is
reused: one login, no privileged intents. The bot needs View Channel, Send
Messages and Embed Links on the results channel.

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
    position = summary.get("final_position") if position_shown(kind_rec) else None
    cars = summary.get("total_cars")
    finished = bool(summary.get("finished"))

    title = f"{track_label(summary.get('track'))} · {kind_label(kind, total_laps, summary)}"

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
    quickest = best_lap(summary.get("laps", []), kind == "lap_race", summary.get("gt7_best_lap_ms"))
    if quickest is not None:
        lap_no, best = quickest
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
        # Discord renders the timestamp in each viewer's time and ages it ("Today at",
        # "Yesterday at", then the date). The session id stays in the logs.
        footer=f"{brand.NAME} {brand.KANJI}",
        timestamp=datetime.fromtimestamp(started, UTC) if started else None,
    )


def position_shown(kind_rec: dict[str, Any] | None) -> bool:
    """Whether a position means anything: a field GT7 flags, as the engineer says it."""
    rec = kind_rec or {}
    return bool(rec.get("field")) and bool(rec.get("cars_on_track"))


def best_lap(
    laps: list[dict[str, Any]], skip_lap_1: bool, gt7_best: int | None = None
) -> tuple[int, int] | None:
    """(lap, time) of the quickest lap. GT7's own best wins when the session has
    one (it leaves out a start lap from a grid ahead of the line). Without it, the
    quickest complete lap, skipping lap 1 of a lap race when there are others, as
    the spoken summary does."""
    if gt7_best:
        lap_no = next((x["lap"] for x in laps if x.get("lap_time_ms") == gt7_best), None)
        if lap_no is not None:
            return lap_no, gt7_best
    timed = [
        (x["lap"], x["lap_time_ms"]) for x in laps if x.get("complete") and x.get("lap_time_ms")
    ]
    if skip_lap_1 and any(lap != 1 for lap, _ in timed):
        timed = [(lap, ms) for lap, ms in timed if lap != 1]
    return min(timed, key=lambda x: x[1]) if timed else None


def track_label(rec: dict[str, Any] | None) -> str:
    if not rec:
        return "Unknown track"
    if rec.get("confidence") in ("probable", "confirmed") and rec.get("name"):
        return str(rec["name"])
    if rec.get("family"):
        return str(rec["family"])
    return "Unknown track"


def kind_label(kind: str, total_laps: int, summary: dict[str, Any]) -> str:
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
        """Post queued cards for the life of the process. A card that fails in an
        unexpected way is logged and dropped; the next one is still posted."""
        while True:
            session_id, card = await self._queue.get()
            try:
                await self.post(session_id, card)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("results: post for %s failed", session_id)

    async def post(self, session_id: str, card: Card) -> bool:
        """Send one card, retrying with backoff. A missing channel or a missing
        permission (``discord.NotFound``, ``discord.Forbidden``) will not change
        on a retry, so it is tried once."""
        import discord

        delay = self.backoff_secs
        for attempt in range(1, self.retries + 1):
            try:
                channel = self.client.get_channel(self.channel_id)
                if channel is None:
                    channel = await self.client.fetch_channel(self.channel_id)
                await channel.send(embed=to_embed(card))
            except (discord.Forbidden, discord.NotFound) as exc:
                log.error(
                    "results: post for %s failed, not retried (check the channel id and the"
                    " bot's permissions): %s",
                    session_id,
                    exc,
                )
                break
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
                try:
                    self.on_posted(session_id)
                except Exception:  # noqa: BLE001
                    log.exception("results: recording the post for %s failed", session_id)
            return True
        self._result("failed")
        return False

    def _result(self, result: str) -> None:
        if self.on_result is not None:
            try:
                self.on_result(result)
            except Exception:  # noqa: BLE001
                log.exception("results: result hook failed for %r", result)
