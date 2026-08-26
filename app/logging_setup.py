"""Logging configuration.

Text output is for reading over someone's shoulder; JSON output is for
shipping into a log aggregator, where per-field querying beats regex over
free-form message strings.
"""

import json
import logging
from datetime import UTC, datetime

from .config import settings

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Attributes LogRecord always carries. Anything outside this set was attached
# by the caller via `extra=` and is worth promoting to a top-level JSON field.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure(service: str) -> None:
    """Install the configured handler. Safe to call once per process."""
    handler = logging.StreamHandler()
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Tags every line from this process, so worker and web output stay
    # distinguishable once both are shipped to the same place.
    old_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.service = service
        return record

    logging.setLogRecordFactory(factory)
