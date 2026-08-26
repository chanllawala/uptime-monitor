from datetime import timedelta

import pytest

from app.models import Check
from app.stats import (
    avg_response_ms,
    latency_percentiles,
    percentile,
    summarize,
    uptime_percent,
)
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


def test_percentile_on_empty_input():
    assert percentile([], 0.95) is None


def test_percentile_endpoints():
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 0) == 10
    assert percentile(values, 1) == 50


def test_percentile_interpolates():
    assert percentile([10, 20], 0.5) == 15
    assert percentile([0, 100], 0.9) == 90


def test_percentile_median_matches_expectation():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3


def test_percentile_rejects_out_of_range_fraction():
    with pytest.raises(ValueError):
        percentile([1, 2, 3], 1.5)


def test_percentiles_expose_the_tail_that_the_average_hides(db, monitor):
    """Nineteen fast checks and one very slow one: the mean stays low while
    p99 shows the outlier, which is the reason for tracking percentiles."""
    for _ in range(19):
        add_check(db, monitor, is_up=True, response_ms=90.0)
    add_check(db, monitor, is_up=True, response_ms=2000.0)

    result = latency_percentiles(db, monitor)

    assert avg_response_ms(db, monitor) < 200
    assert result["p50"] == 90.0
    assert result["p99"] > 1000


def test_percentiles_ignore_failed_checks(db, monitor):
    add_check(db, monitor, is_up=True, response_ms=100.0)
    add_check(db, monitor, is_up=False)

    assert latency_percentiles(db, monitor)["p50"] == 100.0


def test_percentiles_are_none_without_data(db, monitor):
    assert latency_percentiles(db, monitor) == {"p50": None, "p95": None, "p99": None}


def test_humanize_duration():
    assert humanize_duration(45) == "45s"
    assert humanize_duration(90) == "1m 30s"
    assert humanize_duration(3700) == "1h 1m"
    assert humanize_duration(90000) == "1d 1h"
