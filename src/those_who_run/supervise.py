"""Keep the live engineer's long-running tasks alive and report which are up.

A loop that raises, or returns when it should run forever, is logged at once
and restarted after a backoff. While it waits to restart it counts as dead, so
``/healthz`` goes red instead of staying green over a mute or deaf engineer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


class Supervisor:
    """Runs named forever-loops, restarting each with capped exponential backoff.

    ``stable_secs`` resets the backoff once a restarted loop has stayed up that
    long. ``max_restarts`` (None is unlimited) sets ``stop`` instead of
    restarting once a loop has died that many times in a row, so the process
    exits rather than limping on.
    """

    def __init__(
        self,
        stop: asyncio.Event | None = None,
        backoff_secs: float = 1.0,
        max_backoff_secs: float = 30.0,
        stable_secs: float = 60.0,
        max_restarts: int | None = None,
    ) -> None:
        self.stop = stop if stop is not None else asyncio.Event()
        self._backoff = backoff_secs
        self._max_backoff = max_backoff_secs
        self._stable = stable_secs
        self._max_restarts = max_restarts
        self._alive: dict[str, bool] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self.restarts: dict[str, int] = {}
        self.failed = False  # a loop gave up and set stop: exit non-zero
        self._closing = False

    def spawn(self, name: str, loop_fn: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
        self._alive[name] = False
        self.restarts[name] = 0
        task = asyncio.create_task(self._run(name, loop_fn), name=name)
        task.add_done_callback(self._on_done)
        self._tasks[name] = task
        return task

    def alive(self) -> dict[str, bool]:
        """Per-task liveness: True while the loop is running, False while it is
        dead and waiting to restart, or gone."""
        return {name: self._alive[name] and not t.done() for name, t in self._tasks.items()}

    def ok(self) -> bool:
        return all(self.alive().values())

    async def close(self) -> None:
        self._closing = True
        for t in self._tasks.values():
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _run(self, name: str, loop_fn: Callable[[], Awaitable[None]]) -> None:
        delay = self._backoff
        failures = 0
        while True:
            started = time.monotonic()
            self._alive[name] = True
            try:
                await loop_fn()
                log.error("task %s returned unexpectedly", name)
            except asyncio.CancelledError:
                if self._cancelled_by_us():
                    self._alive[name] = False
                    raise
                # A cancel we did not ask for, leaking out of an inner await:
                # a crash like any other, not a reason to die silently.
                log.exception("task %s crashed with a stray cancellation", name)
            except Exception:
                log.exception("task %s crashed", name)
            self._alive[name] = False
            if time.monotonic() - started >= self._stable:
                delay, failures = self._backoff, 0
            failures += 1
            if self._max_restarts is not None and failures > self._max_restarts:
                log.error("task %s died %d times in a row, stopping", name, failures)
                self.failed = True
                self.stop.set()
                return
            self.restarts[name] += 1
            log.warning("restarting task %s in %.1fs", name, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_backoff)

    def _cancelled_by_us(self) -> bool:
        task = asyncio.current_task()
        return self._closing or (task is not None and task.cancelling() > 0)

    def _on_done(self, task: asyncio.Task[None]) -> None:
        # _run only ends by cancellation or by giving up; anything else is a bug
        # in the supervisor itself, so stop rather than run without the loop.
        if task.cancelled() or self.failed:
            return
        exc = task.exception()
        log.error("supervisor for %s ended", task.get_name(), exc_info=exc)
        self.failed = True
        self.stop.set()
