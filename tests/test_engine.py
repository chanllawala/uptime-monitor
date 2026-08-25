"""The alerting state machine — the part where bugs would be most expensive.

An uptime tool that pages on every failed poll, or that never tells you the
service came back, is worse than no tool at all.
"""

from app.checker import CheckResult
from app.engine import consecutive_failures, evaluate, open_incident_for

THRESHOLD = 3

UP = CheckResult(is_up=True, status_code=200, response_time_ms=120.0, error=None)
DOWN = CheckResult(
    is_up=False, status_code=503, response_time_ms=None, error="expected 200, got 503"
)


def fail(db, monitor, notifier, times=1):
    for _ in range(times):
        evaluate(db, monitor, DOWN, notifier=notifier, threshold=THRESHOLD)


def succeed(db, monitor, notifier, times=1):
    for _ in range(times):
        evaluate(db, monitor, UP, notifier=notifier, threshold=THRESHOLD)


def test_failures_below_threshold_do_not_alert(db, monitor, notifier):
    fail(db, monitor, notifier, times=THRESHOLD - 1)

    assert open_incident_for(db, monitor) is None
    assert notifier.messages == []


def test_reaching_threshold_opens_one_incident_and_alerts_once(db, monitor, notifier):
    fail(db, monitor, notifier, times=THRESHOLD)

    incident = open_incident_for(db, monitor)
    assert incident is not None
    assert incident.is_open
    assert incident.cause == "HTTP 503 (expected different status)"
    assert len(notifier.down_alerts) == 1


def test_staying_down_does_not_re_alert(db, monitor, notifier):
    fail(db, monitor, notifier, times=THRESHOLD)
    fail(db, monitor, notifier, times=10)

    # Still exactly one incident and one alert, no matter how long it stays down.
    assert len(notifier.down_alerts) == 1
    assert open_incident_for(db, monitor) is not None


def test_recovery_closes_the_incident_and_sends_one_notice(db, monitor, notifier):
    fail(db, monitor, notifier, times=THRESHOLD)
    succeed(db, monitor, notifier)

    assert open_incident_for(db, monitor) is None
    assert len(notifier.recovery_alerts) == 1


def test_success_without_an_open_incident_is_silent(db, monitor, notifier):
    succeed(db, monitor, notifier, times=5)

    assert notifier.messages == []


def test_intermittent_failures_reset_the_counter(db, monitor, notifier):
    """Two failures, a success, then two more must not trip a threshold of three."""
    fail(db, monitor, notifier, times=2)
    succeed(db, monitor, notifier)
    fail(db, monitor, notifier, times=2)

    assert open_incident_for(db, monitor) is None
    assert notifier.down_alerts == []


def test_a_second_outage_opens_a_second_incident(db, monitor, notifier):
    fail(db, monitor, notifier, times=THRESHOLD)
    succeed(db, monitor, notifier)
    fail(db, monitor, notifier, times=THRESHOLD)

    assert len(notifier.down_alerts) == 2
    assert len(notifier.recovery_alerts) == 1
    assert len(monitor.incidents) == 2


def test_consecutive_failures_counts_back_to_the_last_success(db, monitor, notifier):
    fail(db, monitor, notifier, times=2)
    succeed(db, monitor, notifier)
    fail(db, monitor, notifier, times=1)

    assert consecutive_failures(db, monitor, limit=10) == 1


def test_checks_are_persisted_for_history(db, monitor, notifier):
    fail(db, monitor, notifier, times=2)
    succeed(db, monitor, notifier)

    db.refresh(monitor)
    assert len(monitor.checks) == 3
    assert [c.is_up for c in monitor.checks] == [False, False, True]
