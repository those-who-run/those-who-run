"""Live telemetry from the PS5 via gt-telem, delivered as RaceState on an asyncio queue."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from gt7_race_engineer.state import RaceState

log = logging.getLogger(__name__)


class LiveTelemetry:
    """Wraps ``gt_telem.TurismoClient``.

    gt-telem fires callbacks from a thread pool at 60 Hz. The callback converts
    the packet to a ``RaceState`` and hands it to the event loop thread-safely.
    If the queue is full the oldest state is discarded; rules only care about
    transitions and the next frame carries the same information.
    """

    def __init__(
        self,
        ps5_ip: str | None,
        queue: asyncio.Queue[RaceState],
        loop: asyncio.AbstractEventLoop,
        clock: Any = time.monotonic,
        discover: bool = False,
    ) -> None:
        self.ps5_ip = ps5_ip
        self.queue = queue
        self.loop = loop
        self.clock = clock
        self.discover = discover
        self.last_packet_at: float | None = None
        self.packets = 0
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
        self._client = tc_mod.TurismoClient(is_gt7=True, ps_ip=self.ps5_ip, heartbeat_type="A")
        self._client.register_callback(self._on_packet)
        self._token = asyncio.Event()
        self._task = self.loop.create_task(self._client.run_async(self._token), name="gt-telem")
        log.info(
            "telemetry: heartbeat to %s:%d, listening on udp/%d",
            self._client.ip_addr,
            self._client.RECEIVE_PORT,
            self._client.BIND_PORT,
        )

    def _on_packet(self, tel: Any) -> None:
        now = self.clock()
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
