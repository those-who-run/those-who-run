"""Live telemetry from the PS5 via gt-telem, delivered as RaceState on an asyncio queue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from collections.abc import Callable
from typing import Any
from unittest import mock

from those_who_run.state import RaceState

log = logging.getLogger(__name__)


class LiveTelemetry:
    """Wraps ``gt_telem.TurismoClient``.

    gt-telem fires callbacks from a thread pool at 60 Hz. The callback converts
    the packet to a ``RaceState`` and hands it to the event loop thread-safely.
    If the queue is full the oldest state is discarded; rules only care about
    transitions and the next frame carries the same information.

    Order matters (a lap counter seen going backwards reads as a restart), so
    the pool has one worker, and a packet older than the last one handed over
    is dropped as well.

    The heartbeat is ours, not gt-telem's: gt-telem sends one every 10 s with
    no error handling, so a single failed send (the host losing its route while
    the network is pulled) ended it for good, silently, and GT7 stops
    streaming without one. Ours sends every ``heartbeat_secs``, so the stream
    comes back quickly after an outage, and logs send errors without stopping.

    The listener is ours too. gt-telem's ``run_async`` calls
    ``loop.shutdown_asyncgens()`` on the shared loop when it ends, so we bind
    the UDP socket ourselves and hand datagrams to the client to decrypt and
    parse. When the listener dies (port 33740 busy because ``record`` and
    ``run`` are both up, say) it is logged, ``healthy`` goes false and it is
    restarted with exponential backoff until it binds again.

    This uses gt-telem internals (``_handle_data``, ``_callback_executor``),
    which is why ``pyproject.toml`` pins gt-telem to an exact version.
    """

    REORDER_WINDOW = 600  # packet ids; a bigger jump back is a new game session
    BACKOFF_MAX_SECS = 30.0

    def __init__(
        self,
        ps5_ip: str | None,
        queue: asyncio.Queue[RaceState],
        loop: asyncio.AbstractEventLoop,
        clock: Any = time.monotonic,
        discover: bool = False,
        heartbeat_secs: float = 2.0,
        backoff_secs: float = 1.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.ps5_ip = ps5_ip
        self.queue = queue
        self.loop = loop
        self.clock = clock
        self.discover = discover
        self.heartbeat_secs = heartbeat_secs
        self.backoff_secs = backoff_secs
        self.client_factory = client_factory
        self.last_packet_at: float | None = None
        self.last_packet_id: int | None = None
        self.packets = 0
        self.dropped_out_of_order = 0
        self.listening = False
        self.listener_error: str | None = None
        self.heartbeat_error: str | None = None
        self.restarts = 0
        self._send_failing = False
        self._client: Any = None
        self._token: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._client = self._make_client()
        self._client.register_callback(self._on_packet)
        self._token = asyncio.Event()
        self._task = self.loop.create_task(self._supervise(), name="gt-telem")
        self._task.add_done_callback(self._on_supervisor_done)
        log.info(
            "telemetry: heartbeat to %s:%d, listening on udp/%d",
            self._client.ip_addr,
            self._client.RECEIVE_PORT,
            self._client.BIND_PORT,
        )

    def _make_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        import gt_telem.turismo_client as tc_mod

        kwargs = {
            "is_gt7": True,
            "ps_ip": self.ps5_ip,
            "heartbeat_type": "A",
            "max_callback_workers": 1,
        }
        if self.discover:
            return tc_mod.TurismoClient(**kwargs)
        # gt-telem always tries UDP broadcast discovery before using ps_ip.
        # Broadcast does not work from a pod and costs a second on every
        # start, so skip it whenever an IP is configured. The patch lasts only
        # as long as the constructor.
        with mock.patch.object(tc_mod, "get_ps_ip_type", lambda: (None, None)):
            return tc_mod.TurismoClient(**kwargs)

    @property
    def healthy(self) -> bool:
        """False from the moment the listener or the heartbeat dies until it is
        running again."""
        return self.listener_error is None and self.heartbeat_error is None

    async def _supervise(self) -> None:
        assert self._token is not None
        heartbeat = asyncio.create_task(self._keep_heartbeat(), name="gt-telem-heartbeat")
        delay = self.backoff_secs
        try:
            while not self._token.is_set():
                try:
                    await self._listen()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.listener_error = repr(exc)
                    log.error("telemetry: the listener stopped unexpectedly: %r", exc)
                else:
                    if self._token.is_set():
                        break
                    self.listener_error = "listener ended"
                    log.error("telemetry: the listener ended unexpectedly")
                finally:
                    if self.listening:
                        delay = self.backoff_secs  # it did bind: back off afresh
                    self.listening = False
                log.info("telemetry: restarting the listener in %.0f s", delay)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._token.wait(), timeout=delay)
                delay = min(delay * 2, self.BACKOFF_MAX_SECS)
                self.restarts += 1
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _listen(self) -> None:
        """Bind the UDP port and feed datagrams to the client until stopped."""
        assert self._client is not None and self._token is not None
        client = self._client

        class Protocol(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                client._handle_data(data)

            def error_received(self, exc: Exception) -> None:
                log.debug("telemetry: udp error %r", exc)

        transport, _ = await self.loop.create_datagram_endpoint(
            Protocol, local_addr=("0.0.0.0", client.BIND_PORT)
        )
        try:
            if self.listener_error is not None:
                log.info("telemetry: listening on udp/%d again", client.BIND_PORT)
            self.listening = True
            self.listener_error = None
            await self._token.wait()
        finally:
            transport.close()

    async def _keep_heartbeat(self) -> None:
        """Run the heartbeat, restarting it if it ever dies: without it GT7
        stops sending. ``healthy`` is false while it is down."""
        assert self._token is not None
        delay = self.backoff_secs
        while not self._token.is_set():
            try:
                await self._heartbeat()
                return  # the token was set
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if self._token.is_set() or (task is not None and task.cancelling()):
                    raise
                self.heartbeat_error = "cancelled"
                log.exception("telemetry: the heartbeat was cancelled unexpectedly")
            except Exception as exc:  # noqa: BLE001
                self.heartbeat_error = repr(exc)
                log.exception("telemetry: the heartbeat stopped unexpectedly")
            log.info("telemetry: restarting the heartbeat in %.0f s", delay)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._token.wait(), timeout=delay)
            delay = min(delay * 2, self.BACKOFF_MAX_SECS)

    async def _heartbeat(self) -> None:
        assert self._client is not None and self._token is not None
        msg = self._client.heartbeat_type.encode("ascii")
        addr = (self._client.ip_addr, self._client.RECEIVE_PORT)
        while not self._token.is_set():
            self.send_heartbeat(msg, addr)
            if self.heartbeat_error is not None:
                log.info("telemetry: the heartbeat is running again")
                self.heartbeat_error = None
            await asyncio.sleep(self.heartbeat_secs)

    def send_heartbeat(self, msg: bytes, addr: tuple[str, int]) -> bool:
        """One heartbeat. A failure is logged once per outage and never raised."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(msg, addr)
        except OSError as exc:
            if not self._send_failing:
                log.warning("telemetry: heartbeat to %s failed (%s), retrying", addr[0], exc)
            self._send_failing = True
            return False
        if self._send_failing:
            log.info("telemetry: heartbeat to %s is getting out again", addr[0])
        self._send_failing = False
        return True

    def _on_supervisor_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or (self._token is not None and self._token.is_set()):
            return
        exc = task.exception()
        self.listener_error = repr(exc)
        log.error("telemetry: the listener supervisor stopped unexpectedly: %r", exc)

    def _on_packet(self, tel: Any) -> None:
        now = self.clock()
        pid = int(getattr(tel, "packet_id", 0))
        last = self.last_packet_id
        if last is not None and 0 <= last - pid < self.REORDER_WINDOW:
            self.dropped_out_of_order += 1  # older than the last one, or a duplicate
            return
        self.last_packet_id = pid
        try:
            state = RaceState.from_telemetry(tel, now)
        except Exception:  # noqa: BLE001
            log.exception("could not convert telemetry packet")
            return
        # Only a packet we could use counts as being connected.
        self.last_packet_at = now
        self.packets += 1
        self.loop.call_soon_threadsafe(self._enqueue, state)

    def _enqueue(self, state: RaceState) -> None:
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        self.queue.put_nowait(state)

    def connected(self, timeout: float) -> bool:
        return self.last_packet_at is not None and self.clock() - self.last_packet_at < timeout

    async def stop(self) -> None:
        if self._token is not None:
            self._token.set()
        if self._task is not None:
            # asyncio.wait never raises the task's own error, and a cancel of
            # stop() itself propagates rather than being swallowed.
            _, pending = await asyncio.wait({self._task}, timeout=5)
            if pending:
                self._task.cancel()
        if self._client is not None:
            self._client._callback_executor.shutdown(wait=False, cancel_futures=True)
