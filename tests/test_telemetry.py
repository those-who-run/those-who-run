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


def test_a_duplicate_packet_id_is_dropped():
    tel, loop = live()
    for pid in (100, 100, 101):
        tel._on_packet(make_telemetry(packet_id=pid, current_lap=1))
    assert [s.packet_id for s in loop.calls] == [100, 101]
    assert tel.dropped_out_of_order == 1


def test_a_packet_that_fails_to_convert_does_not_count_as_connected(monkeypatch):
    tel, loop = live()

    def broken(tel, now):
        raise ValueError("bad packet")

    monkeypatch.setattr("those_who_run.telemetry.RaceState.from_telemetry", broken)
    tel._on_packet(make_telemetry(packet_id=1, current_lap=1))
    assert tel.packets == 0 and tel.last_packet_at is None and not tel.connected(5)
    assert loop.calls == []


class FakeClient:
    ip_addr = "127.0.0.1"
    RECEIVE_PORT = 9  # discard; heartbeats go nowhere
    BIND_PORT = 0  # any free port
    heartbeat_type = "A"

    def __init__(self):
        self.callbacks = []
        self.data = []
        self._callback_executor = SimpleNamespace(shutdown=lambda **kw: None)

    def register_callback(self, cb):
        self.callbacks.append(cb)

    def _handle_data(self, data):
        self.data.append(data)


def test_a_listener_that_dies_is_reported_and_restarted(monkeypatch):
    """AC1: the listen task raises, health says not ok, then it comes back."""
    client = FakeClient()

    async def go():
        loop = asyncio.get_running_loop()
        tel = LiveTelemetry(
            "127.0.0.1",
            asyncio.Queue(),
            loop,
            heartbeat_secs=10,
            backoff_secs=0.05,
            client_factory=lambda: client,
        )
        real = loop.create_datagram_endpoint
        attempts = []

        async def flaky(*a, **kw):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError(98, "Address already in use")
            return await real(*a, **kw)

        monkeypatch.setattr(loop, "create_datagram_endpoint", flaky)
        monkeypatch.setattr(tel, "send_heartbeat", lambda msg, addr: True)
        tel.start()
        await asyncio.sleep(0.01)
        down = (tel.healthy, tel.listening, tel.listener_error)
        for _ in range(100):
            if tel.listening:
                break
            await asyncio.sleep(0.01)
        up = (tel.healthy, tel.listening, tel.restarts)
        await tel.stop()
        return down, up, tel

    down, up, tel = asyncio.run(go())
    assert down[0] is False and down[1] is False and "Address already in use" in down[2]
    assert up == (True, True, 1)
    assert tel.listening is False and tel._task.done()


def test_a_listener_that_ends_on_its_own_is_restarted_with_growing_backoff(monkeypatch):
    client = FakeClient()

    async def go():
        loop = asyncio.get_running_loop()
        tel = LiveTelemetry(
            "127.0.0.1", asyncio.Queue(), loop, backoff_secs=0.01, client_factory=lambda: client
        )
        waits = []
        real_wait_for = asyncio.wait_for

        async def recording_wait_for(aw, timeout):
            waits.append(timeout)
            return await real_wait_for(aw, timeout)

        async def dies():
            raise RuntimeError("boom")

        monkeypatch.setattr(tel, "_listen", dies)
        monkeypatch.setattr(tel, "send_heartbeat", lambda msg, addr: True)
        monkeypatch.setattr("those_who_run.telemetry.asyncio.wait_for", recording_wait_for)
        tel.start()
        await asyncio.sleep(0.2)
        healthy = tel.healthy
        await tel.stop()
        return tel, waits, healthy

    tel, waits, healthy = asyncio.run(go())
    assert healthy is False and tel.restarts >= 3
    assert waits[:3] == [0.01, 0.02, 0.04]


def test_stop_does_not_swallow_its_own_cancellation():
    async def go():
        tel = LiveTelemetry("127.0.0.1", asyncio.Queue(), asyncio.get_running_loop())
        tel._token = asyncio.Event()
        tel._task = asyncio.create_task(asyncio.sleep(60))  # ignores the token
        stopper = asyncio.create_task(tel.stop())
        await asyncio.sleep(0.01)
        stopper.cancel()
        try:
            await stopper
        except asyncio.CancelledError:
            tel._task.cancel()
            return True
        return False

    assert asyncio.run(go()) is True


def test_the_discovery_patch_does_not_leak():
    import gt_telem.turismo_client as tc_mod

    before = tc_mod.get_ps_ip_type
    tel, _ = live()
    client = tel._make_client()
    assert client.ip_addr == "192.0.2.10"
    assert tc_mod.get_ps_ip_type is before
    client._callback_executor.shutdown(wait=False)


def test_a_heartbeat_that_dies_is_restarted_and_shows_in_health(monkeypatch):
    """Anything but OSError used to end the heartbeat for good, silently."""
    client = FakeClient()

    async def go():
        loop = asyncio.get_running_loop()
        tel = LiveTelemetry(
            "127.0.0.1",
            asyncio.Queue(),
            loop,
            heartbeat_secs=0.01,
            backoff_secs=0.05,
            client_factory=lambda: client,
        )
        sent = []

        def send(msg, addr):
            sent.append(msg)
            if len(sent) == 1:
                raise RuntimeError("not an OSError")
            return True

        monkeypatch.setattr(tel, "send_heartbeat", send)
        tel.start()
        await asyncio.sleep(0.02)
        down = (tel.healthy, tel.heartbeat_error)
        for _ in range(100):
            if len(sent) >= 3:
                break
            await asyncio.sleep(0.01)
        up = tel.healthy
        await tel.stop()
        return down, up, sent

    down, up, sent = asyncio.run(go())
    assert down[0] is False and "not an OSError" in down[1]
    assert up is True and len(sent) >= 3
