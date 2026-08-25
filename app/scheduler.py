"""Worker entrypoint: poll due monitors forever.

Run with `python -m app.scheduler`. This is the `worker` service in
docker-compose, kept as a separate process from the web dashboard so a slow or
hanging check can never block page rendering.
"""

import logging
import signal
import sys
import time
from types import FrameType

from .config import settings
from .database import Base, SessionLocal, engine
from .engine import check_monitor, due_monitors
from .notifier import get_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("scheduler")

_shutdown = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    # Docker stops containers with SIGTERM; finish the current tick and exit
    # cleanly rather than dying mid-check and leaving a half-written row.
    global _shutdown
    log.info("Received signal %s, shutting down after current tick", signum)
    _shutdown = True


def run_forever() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    Base.metadata.create_all(bind=engine)
    notifier = get_notifier()

    if not settings.slack_enabled:
        log.warning("SLACK_WEBHOOK_URL is not set — alerts will be logged, not delivered")

    log.info(
        "Scheduler started (tick=%ss, failure threshold=%s)",
        settings.scheduler_tick_seconds,
        settings.failure_threshold,
    )

    while not _shutdown:
        started = time.monotonic()
        try:
            db = SessionLocal()
            try:
                monitors = due_monitors(db)
                for monitor in monitors:
                    if _shutdown:
                        break
                    check = check_monitor(db, monitor, notifier=notifier)
                    log.info(
                        "%s %s -> %s",
                        "UP  " if check.is_up else "DOWN",
                        monitor.name,
                        check.error
                        or f"HTTP {check.status_code} in {check.response_time_ms:.0f}ms",
                    )
            finally:
                db.close()
        except Exception:
            # A bad tick must not kill the worker; log it and try again next time.
            log.exception("Scheduler tick failed")

        elapsed = time.monotonic() - started
        remaining = max(0.0, settings.scheduler_tick_seconds - elapsed)
        # Sleep in short slices so shutdown is responsive.
        while remaining > 0 and not _shutdown:
            nap = min(0.5, remaining)
            time.sleep(nap)
            remaining -= nap

    log.info("Scheduler stopped")


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        sys.exit(0)
