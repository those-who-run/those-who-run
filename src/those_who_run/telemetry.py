"""Live telemetry from the PS5 via gt-telem, delivered as RaceState on an asyncio queue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from typing import Any

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
    no error handling, so a single failed send (the NUC losing its route while
    the network is pulled) ended it for good, silently, and GT7 stops
    streaming without one. Ours sends every ``heartbeat_secs``, so the stream
    comes back quickly after an outage, and logs send errors without stopping.
    """

    REORDER_WINDOW = 600  # packet ids; a bigger jump back is a new game session

    def __init__(
        self,
        ps5_ip: str | None,
        queue: asyncio.Queue[RaceState],
        loop: asyncio.AbstractEventLoop,
        clock: Any = time.monotonic,
        discover: bool = False,
        heartbeat_secs: float = 2.0,
    ) -> None:
        self.ps5_ip = ps5_ip
        self.queue = queue
        self.loop = loop
        self.clock = clock
        self.discover = discover
        self.heartbeat_secs = heartbeat_secs
        self.last_packet_at: float | None = None
        self.last_packet_id: int | None = None
        self.packets = 0
        self.dropped_out_of_order = 0
        self._send_failing = False
        self._client: Any = None
        self._token: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        import gt_telem.turismo_client as tc_mod

        if not self.discover:
            # gt-telem always tries UDP broadcast discovery before using ps_ip.
            # Broadcast does not work from a pod and costs a second on every
            # start, so skip it whenever an IP is configured.
            tc_mod.get_ps_ip_type = lambda: (None, None)
        self._client = tc_mod.TurismoClient(
            is_gt7=True, ps_ip=self.ps5_ip, heartbeat_type="A", max_callback_workers=1
        )
        self._client._send_heartbeat = self._heartbeat  # run_async gathers this instead
        self._client.register_callback(self._on_packet)
        self._token = asyncio.Event()
        self._task = self.loop.create_task(self._client.run_async(self._token), name="gt-telem")
        self._task.add_done_callback(self._on_client_done)
        log.info(
            "telemetry: heartbeat to %s:%d, listening on udp/%d",
            self._client.ip_addr,
            self._client.RECEIVE_PORT,
            self._client.BIND_PORT,
        )

    async def _heartbeat(self) -> None:
        assert self._client is not None and self._token is not None
        msg = self._client.heartbeat_type.encode("ascii")
        addr = (self._client.ip_addr, self._client.RECEIVE_PORT)
        while not self._token.is_set():
            self.send_heartbeat(msg, addr)
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

    def _on_client_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or (self._token is not None and self._token.is_set()):
            return
        exc = task.exception()
        log.error("telemetry: the gt-telem client stopped unexpectedly: %r", exc)

    def _on_packet(self, tel: Any) -> None:
        now = self.clock()
        pid = int(getattr(tel, "packet_id", 0))
        last = self.last_packet_id
        if last is not None and 0 < last - pid < self.REORDER_WINDOW:
            self.dropped_out_of_order += 1
            return
        self.last_packet_id = pid
        self.last_packet_at = now
        self.packets += 1
        try:
            state = RaceState.from_telemetry(tel, now)
        except Exception:  # noqa: BLE001
            log.exception("could not convert telemetry packet")
            return
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
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                self._task.cancel()
        if self._client is not None:
            self._client._callback_executor.shutdown(wait=False, cancel_futures=True)
