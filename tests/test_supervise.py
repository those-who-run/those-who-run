"""The live loops survive one bad callout or frame, and a dead task shows in health."""

import asyncio
import logging

from tests.conftest import make_state
from those_who_run.app import ingest_loop, speak_loop
from those_who_run.callouts import Callout, CalloutQueue
from those_who_run.supervise import Supervisor


def callout(text, t=0.0):
    return Callout(text=text, priority=10, rule="test", created_at=t)


class FlakyPlayer:
    """Raises like discord.py does when voice drops between check and play."""

    def __init__(self, fail_first=1):
        self.fail_first = fail_first
        self.spoken = []
        self.attempts = 0

    async def play(self, c):
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise RuntimeError("Not connected to voice.")
        self.spoken.append(c.text)


async def wait_for(cond, timeout=2.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_speak_loop_keeps_speaking_after_a_failed_play(caplog):
    queue = CalloutQueue(max_age=None)
    queue.push(callout("Pit this lap.", 0.0))
    queue.push(callout("Final lap.", 1.0))
    player = FlakyPlayer()
    task = asyncio.create_task(speak_loop(queue, player, clock=lambda: 2.0))
    with caplog.at_level(logging.ERROR):
        await wait_for(lambda: player.spoken)
    task.cancel()
    assert player.spoken == ["Final lap."]
    assert any("Pit this lap." in r.getMessage() and r.exc_info for r in caplog.records)


async def test_ingest_loop_processes_frames_after_one_raises(caplog):
    states = asyncio.Queue()
    seen = []

    async def handle(state):
        if state.t == 1.0:
            raise ValueError("detector blew up")
        seen.append(state.t)

    for t in (1.0, 2.0, 3.0):
        states.put_nowait(make_state(t=t))
    task = asyncio.create_task(ingest_loop(states, handle))
    with caplog.at_level(logging.ERROR):
        await wait_for(lambda: len(seen) == 2)
    task.cancel()
    assert seen == [2.0, 3.0]
    assert any("processing frame" in r.getMessage() and r.exc_info for r in caplog.records)


async def test_ingest_loop_with_engine_that_raises_once():
    from those_who_run.engine import Engine

    class Store:
        session = None

        def __getattr__(self, name):
            return lambda *a, **k: None

    engine = Engine([], CalloutQueue(), Store())
    real = engine.process
    calls = []

    def process(state):
        calls.append(state.t)
        if len(calls) == 1:
            raise RuntimeError("sqlite is locked")
        return real(state)

    engine.process = process

    async def handle(state):
        engine.process(state)

    states = asyncio.Queue()
    for t in (1.0, 2.0, 3.0):
        states.put_nowait(make_state(t=t))
    task = asyncio.create_task(ingest_loop(states, handle))
    await wait_for(lambda: len(calls) == 3)
    task.cancel()
    assert calls == [1.0, 2.0, 3.0]


async def test_a_crashed_task_shows_dead_then_restarts(caplog):
    sup = Supervisor(backoff_secs=0.2)
    runs = []
    hold = asyncio.Event()

    async def loop():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("boom")
        await hold.wait()

    async def forever():
        await asyncio.Event().wait()

    with caplog.at_level(logging.WARNING):
        sup.spawn("watchdog", loop)
        sup.spawn("speak", forever)
        await wait_for(lambda: runs and not sup.alive()["watchdog"])
        assert sup.ok() is False
        assert sup.alive() == {"watchdog": False, "speak": True}
        await wait_for(lambda: len(runs) == 2)
        await asyncio.sleep(0)
        assert sup.ok() is True
    assert sup.restarts["watchdog"] == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("task watchdog crashed" in m for m in messages)
    assert any("restarting task watchdog" in m for m in messages)
    await sup.close()
    assert not sup.stop.is_set()


async def test_a_task_that_returns_is_reported_and_restarted(caplog):
    sup = Supervisor(backoff_secs=0.01)
    runs = []

    async def loop():
        runs.append(1)
        if len(runs) < 3:
            return
        await asyncio.Event().wait()

    with caplog.at_level(logging.ERROR):
        sup.spawn("ingest", loop)
        await wait_for(lambda: len(runs) == 3)
    assert any("task ingest returned unexpectedly" in r.getMessage() for r in caplog.records)
    await sup.close()


async def test_giving_up_sets_stop_and_marks_failed():
    stop = asyncio.Event()
    sup = Supervisor(stop, backoff_secs=0.01, max_restarts=2)

    async def loop():
        raise RuntimeError("always")

    sup.spawn("results", loop)
    await asyncio.wait_for(stop.wait(), 2)
    assert sup.failed and sup.restarts["results"] == 2
    assert sup.alive() == {"results": False} and not sup.ok()
    await sup.close()


async def test_close_cancels_everything():
    sup = Supervisor()

    async def forever():
        await asyncio.Event().wait()

    t = sup.spawn("speak", forever)
    await asyncio.sleep(0)
    await sup.close()
    assert t.cancelled()
    assert not sup.failed and not sup.stop.is_set()


async def test_a_stray_cancellation_is_a_crash_not_a_silent_death(caplog):
    """A CancelledError leaking out of an inner await (not from close) is logged
    and the loop restarted, instead of the task ending with no trace."""
    sup = Supervisor(backoff_secs=0.01)
    runs = []

    async def loop():
        runs.append(1)
        if len(runs) == 1:
            inner = asyncio.create_task(asyncio.sleep(60))
            inner.cancel()
            await inner  # raises CancelledError into this loop
        await asyncio.Event().wait()

    with caplog.at_level(logging.ERROR):
        t = sup.spawn("speak", loop)
        await wait_for(lambda: len(runs) == 2)
        await asyncio.sleep(0)
    assert not t.done() and sup.alive() == {"speak": True}
    assert sup.restarts["speak"] == 1
    assert any("stray cancellation" in r.getMessage() for r in caplog.records)
    await sup.close()
    assert t.cancelled() and not sup.failed


async def test_cancelling_the_task_directly_still_stops_it():
    sup = Supervisor(backoff_secs=0.01)

    async def forever():
        await asyncio.Event().wait()

    t = sup.spawn("watchdog", forever)
    await asyncio.sleep(0)
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    assert t.cancelled() and sup.restarts["watchdog"] == 0
