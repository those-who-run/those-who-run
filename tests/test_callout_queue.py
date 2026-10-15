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
