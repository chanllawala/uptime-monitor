"""Outbound alerting.

A Slack Incoming Webhook is used when SLACK_WEBHOOK_URL is set; otherwise
alerts are logged. That fallback keeps local development and CI from needing a
real webhook, and means a missing secret degrades to "no alerts" rather than
crashing the scheduler.
"""

import logging
from typing import Protocol

import requests

from .config import settings
from .timeutil import humanize_duration

log = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 10


class Notifier(Protocol):
    def send(self, text: str, blocks: list | None = None) -> bool: ...


class LoggingNotifier:
    """Used when no webhook is configured."""

    def send(self, text: str, blocks: list | None = None) -> bool:
        log.warning("[alert not sent - no webhook configured] %s", text)
        return False


class SlackNotifier:
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(self, text: str, blocks: list | None = None) -> bool:
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            response = requests.post(self._webhook_url, json=payload, timeout=SEND_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Deliberately not logging the exception verbatim: request
            # exceptions embed the full URL, which would leak the webhook
            # secret into the logs.
            log.error("Failed to deliver Slack alert (%s)", type(exc).__name__)
            return False
        log.info("Slack alert delivered: %s", text)
        return True


def get_notifier() -> Notifier:
    if settings.slack_enabled:
        return SlackNotifier(settings.slack_webhook_url)
    return LoggingNotifier()


def notify_down(notifier: Notifier, monitor_name: str, url: str, cause: str) -> bool:
    text = f"🔴 {monitor_name} is DOWN — {cause}"
    return notifier.send(
        text,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🔴 {monitor_name} is DOWN*"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*URL*\n{url}"},
                    {"type": "mrkdwn", "text": f"*Cause*\n{cause}"},
                ],
            },
        ],
    )


def notify_recovered(
    notifier: Notifier, monitor_name: str, url: str, downtime_seconds: float
) -> bool:
    duration = humanize_duration(downtime_seconds)
    text = f"✅ {monitor_name} has RECOVERED — down for {duration}"
    return notifier.send(
        text,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*✅ {monitor_name} has RECOVERED*"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*URL*\n{url}"},
                    {"type": "mrkdwn", "text": f"*Downtime*\n{duration}"},
                ],
            },
        ],
    )
