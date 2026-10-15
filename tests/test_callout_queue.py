from those_who_run.callouts import Callout, CalloutQueue


def c(text, priority=20, rule="r", at=0.0):
    return Callout(text=text, priority=priority, rule=rule, created_at=at)


def test_priority_then_age():
    q = CalloutQueue(max_age=None)
    q.push(c("lap", 20, at=1.0))
    q.push(c("final", 10, at=1.0))
    q.push(c("older lap", 20, at=0.5))
    assert [q.pop(2.0).text for _ in range(3)] == ["final", "older lap", "lap"]
    assert q.pop(2.0) is None


def test_stale_callouts_are_dropped_and_counted():
    q = CalloutQueue(max_age=8.0)
    q.push(c("old", at=0.0))
    q.push(c("fresh", at=10.0))
    assert q.pop(12.0).text == "fresh"
    assert q.dropped == 1
    assert q.pop(12.0) is None


def test_clear():
    q = CalloutQueue()
    q.push(c("a"))
    q.push(c("b"))
    assert q.clear() == 2
    assert len(q) == 0


def test_a_callout_can_outlive_the_queue_limit():
    # The race summary waits behind the final lap time (2026-10-15: both summaries
    # were dropped at 8 s while the lap time was still being spoken).
    q = CalloutQueue(max_age=8.0)
    q.push(Callout(text="summary", priority=25, rule="race_summary", created_at=0.0, max_age=30.0))
    q.push(c("lap", at=0.0))
    assert q.pop(12.0).text == "summary"
    assert q.dropped == 1
    q.push(Callout(text="late", priority=25, rule="race_summary", created_at=0.0, max_age=30.0))
    assert q.pop(31.0) is None


def test_replay_queue_never_drops_even_with_a_callout_limit():
    q = CalloutQueue(max_age=None)
    q.push(Callout(text="summary", priority=25, rule="r", created_at=0.0, max_age=1.0))
    assert q.pop(100.0).text == "summary"
