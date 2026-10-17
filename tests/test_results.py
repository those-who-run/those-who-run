"""Results cards for the race-feed channel (#69)."""

import asyncio
import dataclasses
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from those_who_run.__main__ import main
from those_who_run.audio.player import ConsolePlayer
from those_who_run.callouts import CalloutQueue
from those_who_run.config import DEFAULT_RULES, ConfigError, Settings
from those_who_run.engine import Engine
from those_who_run.replay import read_recording, replay
from those_who_run.results import ResultsPoster, build_card, race_time, session_link, to_embed
from those_who_run.rules import build_rules
from those_who_run.store import SessionStore

FIXTURES = Path(__file__).parent / "fixtures"


def summaries(fixture: str, tmp_path: Path) -> list[dict]:
    out: list[dict] = []
    store = SessionStore(tmp_path, on_end=out.append)
    engine = Engine(build_rules(DEFAULT_RULES["rules"]), CalloutQueue(max_age=None), store)
    asyncio.run(
        replay(read_recording(FIXTURES / f"{fixture}.jsonl", strict=True), engine, ConsolePlayer())
    )
    if store.session is not None and engine.prev is not None:
        store.end_session(engine.prev)
    store.close()
    return out


def card_text(summary: dict) -> tuple:
    card = build_card(summary)
    assert card is not None
    return (card.title, card.description, dict(card.fields))


def test_race_time():
    assert race_time(96595) == "1:36.595"
    assert race_time(49677) == "49.677"
    assert race_time(494302) == "8:14.302"
    assert race_time(3723456) == "1:02:03.456"


# real sessions


def test_real_finished_race(tmp_path):
    (s,) = summaries("real-nuc-suzuka-no-stop-2026-10-15", tmp_path)
    assert card_text(s) == (
        "Suzuka Circuit East Course · 6-lap race",
        "🚩 Finished P2 of 20 in 6:16.641",
        # lap 1 starts ahead of the line and is short: skipped, as the engineer does
        {"Best lap": "1:01.186 (lap 4)", "Car": "Honda Civic Si Group A version '87",
         "Fuel used": "97%"},
    )  # fmt: skip
    assert build_card(s).colour == 0xD21F1B


def test_real_race_with_a_pit_stop_counts_both_stints(tmp_path):
    (s,) = summaries("real-nuc-suzuka-pit-stop-2026-10-15", tmp_path)
    title, description, fields = card_text(s)
    assert description == "🚩 Finished P1 of 2 in 6:29.934"
    # each stint, not the 130% they add up to; the refuel does not cancel the first
    assert fields["Fuel used"] == "74%, then 57%"
    assert fields["Best lap"] == "59.541 (lap 5)"


def test_real_time_trial_has_no_position(tmp_path):
    (s,) = summaries("real-nuc-fuji-timed-2026-10-15", tmp_path)
    assert card_text(s) == (
        "Fuji International Speedway · time trial",
        "2 laps",
        {"Best lap": "2:00.314 (lap 2)", "Car": "NISMO 400R '95"},
    )
    assert build_card(s).colour == 0x333333


def test_real_retirement_from_a_race_gt7_does_not_flag(tmp_path):
    (s,) = summaries("real-nuc-tokyo-east-race-2026-10-15", tmp_path)
    title, description, fields = card_text(s)
    assert title == "Tokyo Expressway - East Clockwise · 3-lap race"
    assert description == "Retired on lap 2 of 3", "no position without GT7's flag"
    assert "Fuel used" not in fields, "fuel use is off"


def test_real_qualifying_quit_keeps_the_last_position(tmp_path):
    first, second = summaries("real-quali-restart-quit-2026-10-14", tmp_path)
    assert card_text(first)[:2] == ("Nurburgring 24h · timed race", "1 lap, P1 of 20")
    assert card_text(second)[1].startswith("2 laps, P")


def test_real_race_links_to_the_pit_wall_only_when_set(tmp_path):
    (s,) = summaries("real-nuc-gilles-villeneuve-race-2026-10-17", tmp_path)
    plain = build_card(s)
    assert card_text(s) == (
        "Circuit Gilles Villeneuve · 12-lap race",
        "Retired on lap 3 of 12, running P15",
        {"Best lap": "1:37.524 (lap 1)", "Car": "Mazda RX-VISION GT3 EVO '26",
         "Fuel used": "34%"},
    )  # fmt: skip
    assert plain.url is None
    linked = build_card(s, "http://pitwall.nuc.home.arpa/")
    assert linked.url == f"http://pitwall.nuc.home.arpa/?session={s['session_id']}"
    assert linked == dataclasses.replace(plain, url=linked.url), "only the link changes"


def test_session_link():
    assert session_link(None, "20261017-162118") is None
    assert session_link("", "20261017-162118") is None
    assert session_link("http://pw", None) is None
    assert session_link("http://pw", "20261017-162118") == "http://pw/?session=20261017-162118"
    assert session_link("http://pw//", "a b&c/d") == "http://pw/?session=a%20b%26c%2Fd"


def test_embed_title_links_to_the_card_url():
    card = build_card(SUMMARY, "http://pw")
    assert to_embed(card).url == "http://pw/?session=20261016-190000"
    assert to_embed(build_card(SUMMARY)).url is None


def test_no_card_without_a_full_lap():
    assert build_card({"laps_completed": 0, "session_id": "x"}) is None


def test_track_name_needs_confidence_or_a_family():
    base = {"laps_completed": 1, "session_kind": {"kind": "solo_timed"}}
    unsure = {"name": "Fuji International Speedway (Short)", "confidence": "ambiguous"}
    assert build_card({**base, "track": unsure}).title == "Unknown track · time trial"
    family = {**unsure, "family": "Fuji International Speedway"}
    assert build_card({**base, "track": family}).title.startswith("Fuji International Speedway ·")
    assert build_card({**base, "track": None}).title.startswith("Unknown track")


# posting


class FakeChannel:
    def __init__(self, fail: int = 0):
        self.fail = fail
        self.sent: list = []

    async def send(self, embed):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("discord said no")
        self.sent.append(embed)


class FakeClient:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel


SUMMARY = {
    "session_id": "20261016-190000",
    "laps_completed": 3,
    "finished": True,
    "total_time_ms": 300000,
    "laps": [{"lap": n, "lap_time_ms": 100000, "complete": True} for n in (1, 2, 3)],
    "session_kind": {"kind": "solo_timed"},
}


def test_poster_sends_an_embed_and_reports():
    channel = FakeChannel()
    posted, results = [], []
    poster = ResultsPoster(FakeClient(channel), 1, posted.append, results.append, backoff_secs=0)

    async def go():
        poster.submit(SUMMARY)
        poster.submit({"session_id": "empty", "laps_completed": 0})
        task = asyncio.create_task(poster.run())
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(go())
    (embed,) = channel.sent
    assert embed.title == "Unknown track · time trial" and embed.colour.value == 0xD21F1B
    assert [f.name for f in embed.fields] == ["Best lap"]
    assert posted == ["20261016-190000"] and results == ["skipped", "ok"]
    assert embed.url is None


def test_poster_links_cards_to_the_pit_wall():
    channel = FakeChannel()
    poster = ResultsPoster(FakeClient(channel), 1, backoff_secs=0, pitwall_url="http://pw/")

    async def go():
        poster.submit(SUMMARY)
        task = asyncio.create_task(poster.run())
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(go())
    (embed,) = channel.sent
    assert embed.url == "http://pw/?session=20261016-190000"


def test_poster_retries_then_gives_up():
    results: list[str] = []
    card = build_card(SUMMARY)
    flaky = ResultsPoster(FakeClient(FakeChannel(fail=2)), 1, on_result=results.append,
                          backoff_secs=0)  # fmt: skip
    assert asyncio.run(flaky.post("a", card)) is True
    broken = ResultsPoster(FakeClient(FakeChannel(fail=9)), 1, on_result=results.append,
                           backoff_secs=0)  # fmt: skip
    assert asyncio.run(broken.post("b", card)) is False
    assert results == ["ok", "failed"]


def _run_queue(poster: ResultsPoster, *summaries: dict) -> None:
    async def go():
        for s in summaries:
            poster.submit(s)
        task = asyncio.create_task(poster.run())
        await asyncio.sleep(0.05)
        assert not task.done()  # still running for the next card
        task.cancel()

    asyncio.run(go())


def test_poster_carries_on_when_recording_the_post_fails():
    """``on_posted`` is ``store.mark_posted``, a SQLite commit that can raise
    "database is locked" (#146): the next card is still posted."""
    channel = FakeChannel()
    tried: list[str] = []

    def locked(session_id):
        tried.append(session_id)
        raise sqlite3.OperationalError("database is locked")

    poster = ResultsPoster(FakeClient(channel), 1, on_posted=locked, backoff_secs=0)
    _run_queue(poster, SUMMARY, {**SUMMARY, "session_id": "next"})
    assert len(channel.sent) == 2 and tried == ["20261016-190000", "next"]


def test_poster_carries_on_when_the_result_hook_fails():
    channel = FakeChannel()

    def broken(result):
        raise RuntimeError("metrics are down")

    poster = ResultsPoster(FakeClient(channel), 1, on_result=broken, backoff_secs=0)
    _run_queue(poster, {"session_id": "empty", "laps_completed": 0}, SUMMARY, SUMMARY)
    assert len(channel.sent) == 2


def test_poster_carries_on_after_an_unexpected_error(monkeypatch):
    """Anything escaping one post (a bug, say) is logged; the next card goes out."""
    channel = FakeChannel()
    poster = ResultsPoster(FakeClient(channel), 1, backoff_secs=0)
    real_post = poster.post

    async def post(session_id, card):
        if session_id == "bad":
            raise RuntimeError("a bug")
        return await real_post(session_id, card)

    monkeypatch.setattr(poster, "post", post)
    _run_queue(poster, {**SUMMARY, "session_id": "bad"}, SUMMARY)
    assert len(channel.sent) == 1


class ForbiddenChannel(FakeChannel):
    def __init__(self, exc_type):
        super().__init__()
        self.exc_type = exc_type
        self.attempts = 0

    async def send(self, embed):
        self.attempts += 1
        raise self.exc_type(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")


@pytest.mark.parametrize("exc_type", [discord.Forbidden, discord.NotFound])
def test_poster_does_not_retry_a_permanent_failure(exc_type):
    channel = ForbiddenChannel(exc_type)
    results: list[str] = []
    poster = ResultsPoster(FakeClient(channel), 1, on_result=results.append, backoff_secs=0)
    assert asyncio.run(poster.post("a", build_card(SUMMARY))) is False
    assert channel.attempts == 1 and results == ["failed"]


# plumbing


def test_store_hands_over_the_summary_and_records_the_post(tmp_path):
    def boom(summary):
        raise RuntimeError("a hook must not break the store")

    (s,) = summaries("real-nuc-fuji-timed-2026-10-15", tmp_path / "a")
    assert s["finished"] is False and s["total_time_ms"] is None
    store = SessionStore(tmp_path / "a")
    store.mark_posted(s["session_id"], at=123.0)
    store.close()
    db = sqlite3.connect(tmp_path / "a" / "index.sqlite")
    assert db.execute("SELECT posted_at FROM sessions").fetchall() == [(123.0,)]

    store = SessionStore(tmp_path / "b", on_end=boom)
    engine = Engine([], CalloutQueue(max_age=None), store)
    for state in read_recording(FIXTURES / "real-nuc-fuji-timed-2026-10-15.jsonl", strict=True):
        engine.process(state)
    store.close()
    assert len(list((tmp_path / "b" / "sessions").glob("*/summary.json"))) == 1


def test_results_channel_setting():
    assert Settings.from_env({}).results_channel_id is None
    assert Settings.from_env({"DISCORD_RESULTS_CHANNEL_ID": "42"}).results_channel_id == 42
    assert Settings.from_env({"DISCORD_RESULTS_CHANNEL_ID": "0"}).results_channel_id is None
    with pytest.raises(ConfigError, match="DISCORD_RESULTS_CHANNEL_ID"):
        Settings.from_env({"DISCORD_RESULTS_CHANNEL_ID": "abc"})


def test_pitwall_url_setting():
    assert Settings.from_env({}).pitwall_url is None
    assert Settings.from_env({"PITWALL_URL": ""}).pitwall_url is None
    url = "http://pitwall.nuc.home.arpa"
    assert Settings.from_env({"PITWALL_URL": url}).pitwall_url == url


def test_post_dry_run_prints_the_card(tmp_path, monkeypatch, capsys):
    (s,) = summaries("real-nuc-fuji-timed-2026-10-15", tmp_path)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
    assert main(["post", s["session_id"], "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Fuji International Speedway · time trial" in out and "Best lap: 2:00.314" in out
    assert json.loads((tmp_path / "sessions" / s["session_id"] / "summary.json").read_text())
    assert "?session=" not in out, "no link without PITWALL_URL"


def test_post_dry_run_prints_the_link(tmp_path, monkeypatch, capsys):
    (s,) = summaries("real-nuc-fuji-timed-2026-10-15", tmp_path)
    monkeypatch.setenv("GT7_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PITWALL_URL", "http://pitwall.nuc.home.arpa/")
    assert main(["post", s["session_id"], "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"http://pitwall.nuc.home.arpa/?session={s['session_id']}\n" in out
