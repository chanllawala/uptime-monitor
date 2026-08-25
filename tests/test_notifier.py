import json

import responses

from app.notifier import LoggingNotifier, SlackNotifier, notify_down, notify_recovered

WEBHOOK = "https://hooks.slack.com/services/T000/B000/secret-token"


@responses.activate
def test_slack_notifier_posts_payload():
    responses.add(responses.POST, WEBHOOK, status=200, body="ok")

    assert SlackNotifier(WEBHOOK).send("hello") is True

    body = json.loads(responses.calls[0].request.body)
    assert body["text"] == "hello"


@responses.activate
def test_slack_failure_is_reported_without_raising():
    """A dead webhook must not take the scheduler down with it."""
    responses.add(responses.POST, WEBHOOK, status=500)

    assert SlackNotifier(WEBHOOK).send("hello") is False


@responses.activate
def test_slack_failure_does_not_leak_the_webhook_url(caplog):
    responses.add(responses.POST, WEBHOOK, status=500)

    SlackNotifier(WEBHOOK).send("hello")

    assert "secret-token" not in caplog.text


def test_logging_notifier_reports_not_delivered():
    assert LoggingNotifier().send("hello") is False


@responses.activate
def test_down_alert_names_the_monitor_and_cause():
    responses.add(responses.POST, WEBHOOK, status=200)
    notifier = SlackNotifier(WEBHOOK)

    notify_down(notifier, "API", "https://api.example.com", "HTTP 503")

    body = json.loads(responses.calls[0].request.body)
    assert "API" in body["text"] and "DOWN" in body["text"]
    assert "https://api.example.com" in json.dumps(body["blocks"])


@responses.activate
def test_recovery_alert_includes_downtime():
    responses.add(responses.POST, WEBHOOK, status=200)
    notifier = SlackNotifier(WEBHOOK)

    notify_recovered(notifier, "API", "https://api.example.com", 3700)

    body = json.loads(responses.calls[0].request.body)
    assert "RECOVERED" in body["text"]
    assert "1h 1m" in body["text"]
