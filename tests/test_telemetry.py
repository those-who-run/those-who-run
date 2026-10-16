"""LiveTelemetry without a PS5: ordering, heartbeats and their failures."""

import asyncio
import logging
from types import SimpleNamespace

from tests.test_state import make_telemetry
from those_who_run.telemetry import LiveTelemetry


class StubLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, fn, arg):
        self.calls.append(arg)


def live(**kw) -> tuple[LiveTelemetry, StubLoop]:
    loop = StubLoop()
    return LiveTelemetry("192.0.2.10", asyncio.Queue(), loop, clock=lambda: 1.0, **kw), loop


def test_out_of_order_packets_are_dropped():
    tel, loop = live()
    for pid in (100, 101, 99, 102, 101, 103):
        tel._on_packet(make_telemetry(packet_id=pid, current_lap=1))
    assert [s.packet_id for s in loop.calls] == [100, 101, 102, 103]
    assert tel.dropped_out_of_order == 2 and tel.packets == 4


def test_a_big_jump_back_is_a_new_game_session():
    tel, loop = live()
    tel._on_packet(make_telemetry(packet_id=50_000, current_lap=1))
    tel._on_packet(make_telemetry(packet_id=12, current_lap=1))
    assert [s.packet_id for s in loop.calls] == [50_000, 12]


def test_a_failed_heartbeat_is_logged_once_and_never_raised(monkeypatch, caplog):
    tel, _ = live()

    class Down:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def sendto(self, msg, addr):
            raise OSError(101, "Network is unreachable")

    monkeypatch.setattr("those_who_run.telemetry.socket.socket", Down)
    with caplog.at_level(logging.INFO, logger="those_who_run.telemetry"):
        assert tel.send_heartbeat(b"A", ("192.0.2.10", 33739)) is False
        assert tel.send_heartbeat(b"A", ("192.0.2.10", 33739)) is False
    assert sum("heartbeat to 192.0.2.10 failed" in r.message for r in caplog.records) == 1

    sent = []

    class Up(Down):
        def sendto(self, msg, addr):
            sent.append((msg, addr))

    monkeypatch.setattr("those_who_run.telemetry.socket.socket", Up)
    with caplog.at_level(logging.INFO, logger="those_who_run.telemetry"):
        assert tel.send_heartbeat(b"A", ("192.0.2.10", 33739)) is True
    assert sent == [(b"A", ("192.0.2.10", 33739))]
    assert any("getting out again" in r.message for r in caplog.records)


def test_the_heartbeat_loop_keeps_going_through_failures(monkeypatch):
    tel, _ = live(heartbeat_secs=0.01)
    tel._client = SimpleNamespace(heartbeat_type="A", ip_addr="192.0.2.10", RECEIVE_PORT=33739)
    results = iter([False, False, True, True, True])
    calls = []

    def fake_send(msg, addr):
        calls.append(addr)
        return next(results, True)

    monkeypatch.setattr(tel, "send_heartbeat", fake_send)

    async def go():
        tel._token = asyncio.Event()
        task = asyncio.create_task(tel._heartbeat())
        await asyncio.sleep(0.08)
        tel._token.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(go())
    assert len(calls) >= 4 and set(calls) == {("192.0.2.10", 33739)}
