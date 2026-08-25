"""The monitoring state machine.

Kept separate from the scheduler loop so the interesting logic — when a
monitor is considered down, when an incident opens or closes, when an alert
fires — can be tested without any sleeping or threading.
"""

import logging

from sqlalchemy.orm import Session

from . import notifier as notifications
from .checker import CheckResult, perform_check
from .config import settings
from .models import Check, Incident, Monitor
from .timeutil import utcnow

log = logging.getLogger(__name__)


def open_incident_for(db: Session, monitor: Monitor) -> Incident | None:
    return (
        db.query(Incident)
        .filter(Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None))
        .order_by(Incident.started_at.desc())
        .first()
    )


def recent_checks(db: Session, monitor: Monitor, limit: int) -> list[Check]:
    return (
        db.query(Check)
        .filter(Check.monitor_id == monitor.id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .limit(limit)
        .all()
    )


def consecutive_failures(db: Session, monitor: Monitor, limit: int) -> int:
    """How many of the most recent checks failed, counting back until the first success."""
    count = 0
    for check in recent_checks(db, monitor, limit):
        if check.is_up:
            break
        count += 1
    return count


def record_check(db: Session, monitor: Monitor, result: CheckResult) -> Check:
    check = Check(
        monitor_id=monitor.id,
        checked_at=utcnow(),
        is_up=result.is_up,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        error=result.error,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


def evaluate(
    db: Session,
    monitor: Monitor,
    result: CheckResult,
    notifier: notifications.Notifier | None = None,
    threshold: int | None = None,
) -> Check:
    """Persist a check result and open or close an incident if the state changed.

    Alerts fire only on transitions. A monitor that fails once does not alert
    until it has failed `threshold` times in a row, and a monitor that stays
    down produces no further alerts until it recovers.
    """
    notifier = notifier or notifications.get_notifier()
    threshold = threshold if threshold is not None else settings.failure_threshold

    check = record_check(db, monitor, result)
    incident = open_incident_for(db, monitor)

    if result.is_up:
        if incident is not None:
            incident.resolved_at = check.checked_at
            db.commit()
            log.info("Monitor %r recovered", monitor.name)
            notifications.notify_recovered(
                notifier, monitor.name, monitor.url, incident.duration_seconds(check.checked_at)
            )
        return check

    if incident is not None:
        # Already down and already alerted; nothing new to say.
        return check

    failures = consecutive_failures(db, monitor, threshold)
    if failures >= threshold:
        cause = result.summary
        incident = Incident(monitor_id=monitor.id, started_at=check.checked_at, cause=cause)
        db.add(incident)
        db.commit()
        log.warning("Monitor %r declared down after %d failures: %s", monitor.name, failures, cause)
        notifications.notify_down(notifier, monitor.name, monitor.url, cause)
    else:
        log.info(
            "Monitor %r failed (%d/%d before alerting): %s",
            monitor.name,
            failures,
            threshold,
            result.summary,
        )
    return check


def check_monitor(
    db: Session, monitor: Monitor, notifier: notifications.Notifier | None = None
) -> Check:
    """Poll one monitor and process the outcome."""
    result = perform_check(
        url=monitor.url,
        method=monitor.method,
        expected_status=monitor.expected_status,
        timeout_seconds=monitor.timeout_seconds,
    )
    return evaluate(db, monitor, result, notifier=notifier)


def due_monitors(db: Session) -> list[Monitor]:
    """Enabled monitors whose interval has elapsed since their last check."""
    now = utcnow()
    due: list[Monitor] = []
    for monitor in db.query(Monitor).filter(Monitor.enabled.is_(True)).all():
        latest = recent_checks(db, monitor, 1)
        if not latest:
            due.append(monitor)
            continue
        elapsed = (now - latest[0].checked_at).total_seconds()
        if elapsed >= monitor.interval_seconds:
            due.append(monitor)
    return due
