"""Concurrent checking.

The point of the thread pool is that one slow endpoint must not delay every
other monitor queued behind it, so the timing assertion here is the actual
feature rather than incidental.
"""

import time

import pytest
import responses

from app.engine import run_due_checks
from app.models import Monitor

SLOW_SECONDS = 0.3
MONITOR_COUNT = 6


@pytest.fixture()
def many_monitors(db):
    monitors = []
    for i in range(MONITOR_COUNT):
        m = Monitor(
            name=f"Slow {i}",
            url=f"https://slow-{i}.example.com/",
            interval_seconds=60,
            timeout_seconds=5,
        )
        db.add(m)
        monitors.append(m)
    db.commit()
    for m in monitors:
        db.refresh(m)
    return monitors


def _register_slow(monitors):
    def slow_callback(_request):
        time.sleep(SLOW_SECONDS)
        return (200, {}, "ok")

    for m in monitors:
        responses.add_callback(responses.GET, m.url, callback=slow_callback)


@responses.activate
def test_checks_run_in_parallel(db, many_monitors, notifier):
    _register_slow(many_monitors)

    started = time.monotonic()
    checks = run_due_checks(db, many_monitors, notifier=notifier, concurrency=MONITOR_COUNT)
    elapsed = time.monotonic() - started

    assert len(checks) == MONITOR_COUNT
    assert all(c.is_up for c in checks)
    # Sequentially this would take MONITOR_COUNT * SLOW_SECONDS (1.8s).
    # Allow generous headroom for slow CI while still proving overlap.
    assert elapsed < SLOW_SECONDS * MONITOR_COUNT * 0.6


@responses.activate
def test_results_are_applied_in_input_order(db, many_monitors, notifier):
    """Completion order is nondeterministic; recorded order must not be."""
    _register_slow(many_monitors)

    checks = run_due_checks(db, many_monitors, notifier=notifier, concurrency=MONITOR_COUNT)

    assert [c.monitor_id for c in checks] == [m.id for m in many_monitors]


@responses.activate
def test_one_failing_monitor_does_not_affect_the_others(db, many_monitors, notifier):
    for i, m in enumerate(many_monitors):
        status = 500 if i == 2 else 200
        responses.add(responses.GET, m.url, status=status)

    checks = run_due_checks(db, many_monitors, notifier=notifier)

    assert [c.is_up for c in checks] == [True, True, False, True, True, True]


def test_empty_input_is_a_no_op(db, notifier):
    assert run_due_checks(db, [], notifier=notifier) == []


@responses.activate
def test_concurrency_is_capped_at_the_number_of_monitors(db, many_monitors, notifier):
    """A pool larger than the work must not error."""
    for m in many_monitors:
        responses.add(responses.GET, m.url, status=200)

    checks = run_due_checks(db, many_monitors, notifier=notifier, concurrency=100)

    assert len(checks) == MONITOR_COUNT
