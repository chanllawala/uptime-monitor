import json
import logging

from app.logging_setup import JsonFormatter


def make_record(**extra):
    record = logging.LogRecord(
        name="scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Monitor %s checked",
        args=("GitHub",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_output_is_valid_json_with_core_fields():
    payload = json.loads(JsonFormatter().format(make_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "scheduler"
    assert payload["message"] == "Monitor GitHub checked"
    assert "ts" in payload


def test_extra_fields_are_promoted_to_top_level():
    """The point of structured logs: query on response_time_ms, not regex the message."""
    payload = json.loads(
        JsonFormatter().format(make_record(monitor="GitHub", response_time_ms=83.2))
    )

    assert payload["monitor"] == "GitHub"
    assert payload["response_time_ms"] == 83.2


def test_exceptions_are_included():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = make_record()
        record.exc_info = sys.exc_info()
        payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in payload["exception"]


def test_non_serialisable_values_do_not_raise():
    payload = json.loads(JsonFormatter().format(make_record(obj=object())))

    assert isinstance(payload["obj"], str)
