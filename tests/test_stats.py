from datetime import timedelta

from app.models import Check
from app.stats import avg_response_ms, summarize, uptime_percent
from app.timeutil import humanize_duration, utcnow


def add_check(db, monitor, *, is_up, response_ms=100.0, minutes_ago=0):
    db.add(
        Check(
            monitor_id=monitor.id,
            checked_at=utcnow() - timedelta(minutes=minutes_ago),
            is_up=is_up,
            status_code=200 if is_up else 503,
            response_time_ms=response_ms if is_up else None,
        )
    )
    db.commit()


def test_uptime_is_none_without_data(db, monitor):
    assert uptime_percent(db, monitor) is None


def test_uptime_percentage(db, monitor):
    for _ in range(3):
        add_check(db, monitor, is_up=True)
    add_check(db, monitor, is_up=False)

    assert uptime_percent(db, monitor) == 75.0


def test_checks_outside_the_window_are_excluded(db, monitor):
    add_check(db, monitor, is_up=True)
    add_check(db, monitor, is_up=False, minutes_ago=60 * 48)  # two days ago

    assert uptime_percent(db, monitor, hours=24) == 100.0


def test_average_response_ignores_failed_checks(db, monitor):
    add_check(db, monitor, is_up=True, response_ms=100.0)
    add_check(db, monitor, is_up=True, response_ms=200.0)
    add_check(db, monitor, is_up=False)

    assert avg_response_ms(db, monitor) == 150.0


def test_summary_reports_unknown_before_any_check(db, monitor):
    summary = summarize(db, monitor)
    assert summary.status == "unknown"
    assert summary.status_label == "No data"


def test_summary_reflects_latest_check(db, monitor):
    add_check(db, monitor, is_up=True)
    assert summarize(db, monitor).status == "up"

    add_check(db, monitor, is_up=False)
    assert summarize(db, monitor).status == "down"


def test_humanize_duration():
    assert humanize_duration(45) == "45s"
    assert humanize_duration(90) == "1m 30s"
    assert humanize_duration(3700) == "1h 1m"
    assert humanize_duration(90000) == "1d 1h"
