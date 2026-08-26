"""Prometheus exposition.

Metrics are derived from the database on each scrape rather than kept as
in-process counters. The worker and the web dashboard run as separate
containers, so a counter incremented in the worker would be invisible to the
process actually serving /metrics — the database is the only state both share.

The trade-off is that a scrape costs a few queries instead of reading memory,
which is the right way round for a handful of monitors polled every minute.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import stats
from .models import Check, Incident, Monitor
from .timeutil import utcnow

NAMESPACE = "uptime"


def _escape(value: str) -> str:
    """Escape a Prometheus label value per the exposition format."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**pairs: str) -> str:
    inner = ",".join(f'{k}="{_escape(str(v))}"' for k, v in pairs.items())
    return "{" + inner + "}"


class MetricsBuilder:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def add(self, name: str, kind: str, help_text: str, samples: list[tuple[str, float]]) -> None:
        """Emit one metric family. Skipped entirely when it has no samples."""
        if not samples:
            return
        full = f"{NAMESPACE}_{name}"
        self._lines.append(f"# HELP {full} {help_text}")
        self._lines.append(f"# TYPE {full} {kind}")
        for label_str, value in samples:
            self._lines.append(f"{full}{label_str} {_format_value(value)}")

    def render(self) -> str:
        # The exposition format requires a trailing newline.
        return "\n".join(self._lines) + "\n"


def _format_value(value: float) -> str:
    if value != value:  # NaN
        return "NaN"
    if float(value).is_integer():
        return str(int(value))
    return repr(round(float(value), 4))


def render_metrics(db: Session, hours: int = 24) -> str:
    monitors = db.query(Monitor).order_by(Monitor.id).all()
    builder = MetricsBuilder()

    up_samples: list[tuple[str, float]] = []
    enabled_samples: list[tuple[str, float]] = []
    uptime_samples: list[tuple[str, float]] = []
    last_ms_samples: list[tuple[str, float]] = []
    p50_samples: list[tuple[str, float]] = []
    p95_samples: list[tuple[str, float]] = []
    p99_samples: list[tuple[str, float]] = []
    checks_total: list[tuple[str, float]] = []
    incidents_total: list[tuple[str, float]] = []
    last_check_age: list[tuple[str, float]] = []

    now = utcnow()

    for monitor in monitors:
        labels = _labels(monitor=monitor.name, url=monitor.url)
        summary = stats.summarize(db, monitor, hours=hours)

        enabled_samples.append((labels, 1 if monitor.enabled else 0))

        # Deliberately not emitted as 0 when unknown: a monitor that has never
        # been checked is not the same as one that is down, and reporting it
        # as down would page someone over a monitor that was added a moment ago.
        if summary.status in ("up", "down"):
            up_samples.append((labels, 1 if summary.status == "up" else 0))

        if summary.uptime_percent is not None:
            uptime_samples.append((labels, summary.uptime_percent / 100))

        if summary.last_check is not None:
            age = (now - summary.last_check.checked_at).total_seconds()
            last_check_age.append((labels, age))
            if summary.last_check.response_time_ms is not None:
                last_ms_samples.append((labels, summary.last_check.response_time_ms))

        percentiles = stats.latency_percentiles(db, monitor, hours=hours)
        for bucket, target in (
            ("p50", p50_samples),
            ("p95", p95_samples),
            ("p99", p99_samples),
        ):
            if percentiles[bucket] is not None:
                target.append((labels, percentiles[bucket]))

        for is_up, result_label in ((True, "up"), (False, "down")):
            count = (
                db.query(func.count(Check.id))
                .filter(Check.monitor_id == monitor.id, Check.is_up.is_(is_up))
                .scalar()
                or 0
            )
            checks_total.append(
                (_labels(monitor=monitor.name, url=monitor.url, result=result_label), count)
            )

        incident_count = (
            db.query(func.count(Incident.id)).filter(Incident.monitor_id == monitor.id).scalar()
            or 0
        )
        incidents_total.append((labels, incident_count))

    builder.add(
        "monitor_up", "gauge", "1 if the monitor's last check succeeded, 0 if it failed", up_samples
    )
    builder.add("monitor_enabled", "gauge", "1 if the monitor is enabled", enabled_samples)
    builder.add(
        "monitor_uptime_ratio",
        "gauge",
        f"Fraction of checks that succeeded over the last {hours}h",
        uptime_samples,
    )
    builder.add(
        "monitor_last_response_time_milliseconds",
        "gauge",
        "Response time of the most recent successful check",
        last_ms_samples,
    )
    builder.add(
        "monitor_response_time_p50_milliseconds", "gauge", "Median response time", p50_samples
    )
    builder.add(
        "monitor_response_time_p95_milliseconds",
        "gauge",
        "95th percentile response time",
        p95_samples,
    )
    builder.add(
        "monitor_response_time_p99_milliseconds",
        "gauge",
        "99th percentile response time",
        p99_samples,
    )
    builder.add(
        "monitor_last_check_age_seconds",
        "gauge",
        "Seconds since the monitor was last checked; rising means the worker is stalled",
        last_check_age,
    )
    builder.add("checks_total", "counter", "Total checks recorded, by outcome", checks_total)
    builder.add("incidents_total", "counter", "Total incidents opened", incidents_total)

    builder.add(
        "monitors_configured",
        "gauge",
        "Number of configured monitors",
        [("", len(monitors))],
    )

    return builder.render()
