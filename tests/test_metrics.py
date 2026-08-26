from datetime import timedelta

from app.metrics import _escape, _format_value, render_metrics
from app.models import Check, Monitor
from app.timeutil import utcnow


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


def metric_lines(output, name):
    return [line for line in output.splitlines() if line.startswith(f"uptime_{name}{{")]


def test_exposition_has_help_and_type_for_each_family(db, monitor):
    add_check(db, monitor, is_up=True)
    output = render_metrics(db)

    assert "# HELP uptime_monitor_up" in output
    assert "# TYPE uptime_monitor_up gauge" in output
    assert "# TYPE uptime_checks_total counter" in output
    assert output.endswith("\n")


def test_up_metric_reflects_state(db, monitor):
    add_check(db, monitor, is_up=True)
    assert metric_lines(render_metrics(db), "monitor_up")[0].endswith(" 1")

    add_check(db, monitor, is_up=False)
    assert metric_lines(render_metrics(db), "monitor_up")[0].endswith(" 0")


def test_never_checked_monitor_is_omitted_not_reported_down(db, monitor):
    """Absent is not the same as down — reporting 0 would page someone
    over a monitor that was added seconds ago."""
    output = render_metrics(db)

    assert metric_lines(output, "monitor_up") == []
    # It still appears as configured and enabled.
    assert metric_lines(output, "monitor_enabled")[0].endswith(" 1")


def test_uptime_ratio_is_a_fraction_not_a_percentage(db, monitor):
    for _ in range(3):
        add_check(db, monitor, is_up=True)
    add_check(db, monitor, is_up=False)

    line = metric_lines(render_metrics(db), "monitor_uptime_ratio")[0]
    assert line.endswith(" 0.75")


def test_checks_total_is_split_by_result(db, monitor):
    add_check(db, monitor, is_up=True)
    add_check(db, monitor, is_up=True)
    add_check(db, monitor, is_up=False)

    lines = metric_lines(render_metrics(db), "checks_total")
    up = next(line for line in lines if 'result="up"' in line)
    down = next(line for line in lines if 'result="down"' in line)

    assert up.endswith(" 2")
    assert down.endswith(" 1")


def test_percentiles_are_exported(db, monitor):
    for ms in (10.0, 20.0, 30.0, 400.0):
        add_check(db, monitor, is_up=True, response_ms=ms)

    output = render_metrics(db)
    assert metric_lines(output, "monitor_response_time_p50_milliseconds")
    assert metric_lines(output, "monitor_response_time_p95_milliseconds")
    assert metric_lines(output, "monitor_response_time_p99_milliseconds")


def test_last_check_age_is_exported(db, monitor):
    add_check(db, monitor, is_up=True, minutes_ago=5)

    line = metric_lines(render_metrics(db), "monitor_last_check_age_seconds")[0]
    age = float(line.rsplit(" ", 1)[1])
    assert 290 < age < 310


def test_label_values_are_escaped(db):
    """A quote or backslash in a monitor name must not break the exposition."""
    nasty = Monitor(name='we"ird\\name', url="https://example.com", interval_seconds=60)
    db.add(nasty)
    db.commit()
    db.refresh(nasty)
    add_check(db, nasty, is_up=True)

    output = render_metrics(db)
    assert 'monitor="we\\"ird\\\\name"' in output


def test_escape_helper():
    assert _escape('a"b') == 'a\\"b'
    assert _escape("a\\b") == "a\\\\b"
    assert _escape("a\nb") == "a\\nb"


def test_format_value_keeps_integers_clean():
    assert _format_value(1) == "1"
    assert _format_value(1.0) == "1"
    assert _format_value(0.75) == "0.75"
