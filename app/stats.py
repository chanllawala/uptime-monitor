"""Aggregations backing the dashboard."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .models import Check, Incident, Monitor
from .timeutil import utcnow

DEFAULT_WINDOW_HOURS = 24


@dataclass
class MonitorSummary:
    monitor: Monitor
    status: str  # "up" | "down" | "unknown"
    uptime_percent: float | None
    avg_response_ms: float | None
    last_check: Check | None
    open_incident: Incident | None
    check_count: int

    @property
    def status_label(self) -> str:
        return {"up": "Up", "down": "Down", "unknown": "No data"}[self.status]


def _window_start(hours: int):
    return utcnow() - timedelta(hours=hours)


def uptime_percent(db: Session, monitor: Monitor, hours: int = DEFAULT_WINDOW_HOURS):
    """Share of checks in the window that succeeded, or None if nothing was recorded."""
    since = _window_start(hours)
    total, up = (
        db.query(
            func.count(Check.id),
            func.count(case((Check.is_up.is_(True), 1))),
        )
        .filter(Check.monitor_id == monitor.id, Check.checked_at >= since)
        .one()
    )
    if not total:
        return None
    return round(up / total * 100, 2)


def avg_response_ms(db: Session, monitor: Monitor, hours: int = DEFAULT_WINDOW_HOURS):
    """Mean response time over successful checks only.

    Failed checks either have no timing at all or record the time spent failing,
    neither of which says anything useful about how fast the service is.
    """
    value = (
        db.query(func.avg(Check.response_time_ms))
        .filter(
            Check.monitor_id == monitor.id,
            Check.checked_at >= _window_start(hours),
            Check.is_up.is_(True),
            Check.response_time_ms.isnot(None),
        )
        .scalar()
    )
    return round(float(value), 1) if value is not None else None


def latest_check(db: Session, monitor: Monitor) -> Check | None:
    return (
        db.query(Check)
        .filter(Check.monitor_id == monitor.id)
        .order_by(Check.checked_at.desc(), Check.id.desc())
        .first()
    )


def open_incident(db: Session, monitor: Monitor) -> Incident | None:
    return (
        db.query(Incident)
        .filter(Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None))
        .order_by(Incident.started_at.desc())
        .first()
    )


def summarize(db: Session, monitor: Monitor, hours: int = DEFAULT_WINDOW_HOURS) -> MonitorSummary:
    last = latest_check(db, monitor)
    incident = open_incident(db, monitor)

    if last is None:
        status = "unknown"
    elif incident is not None:
        status = "down"
    else:
        status = "up" if last.is_up else "down"

    count = (
        db.query(func.count(Check.id))
        .filter(Check.monitor_id == monitor.id, Check.checked_at >= _window_start(hours))
        .scalar()
        or 0
    )

    return MonitorSummary(
        monitor=monitor,
        status=status,
        uptime_percent=uptime_percent(db, monitor, hours),
        avg_response_ms=avg_response_ms(db, monitor, hours),
        last_check=last,
        open_incident=incident,
        check_count=count,
    )


def summarize_all(db: Session, hours: int = DEFAULT_WINDOW_HOURS) -> list[MonitorSummary]:
    monitors = db.query(Monitor).order_by(Monitor.name).all()
    return [summarize(db, m, hours) for m in monitors]


def check_series(
    db: Session, monitor: Monitor, hours: int = DEFAULT_WINDOW_HOURS, limit: int = 200
):
    """Oldest-first check history, for the response-time chart."""
    rows = (
        db.query(Check)
        .filter(Check.monitor_id == monitor.id, Check.checked_at >= _window_start(hours))
        .order_by(Check.checked_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def recent_incidents(db: Session, monitor: Monitor | None = None, limit: int = 20):
    query = db.query(Incident)
    if monitor is not None:
        query = query.filter(Incident.monitor_id == monitor.id)
    return query.order_by(Incident.started_at.desc()).limit(limit).all()
