"""Worker entrypoint: poll due monitors forever.

Run with `python -m app.scheduler`. This is the `worker` service in
docker-compose, kept as a separate process from the web dashboard so a slow or
hanging check can never block page rendering.
"""

import logging
import signal
import sys
import threading
import time
from types import FrameType

from . import logging_setup
from .config import settings
from .database import Base, SessionLocal, engine
from .engine import due_monitors, run_due_checks
from .notifier import get_notifier

logging_setup.configure("worker")
log = logging.getLogger("scheduler")

_shutdown = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    # Docker stops containers with SIGTERM; finish the current tick and exit
    # cleanly rather than dying mid-check and leaving a half-written row.
    global _shutdown
    log.info("Received signal %s, shutting down after current tick", signum)
    _shutdown = True


def run_forever(install_signal_handlers: bool = True) -> None:
    # signal.signal() only works on the main thread, so the in-process mode
    # (see start_background_thread) opts out and relies on the daemon thread
    # dying with the process instead.
    if install_signal_handlers:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    Base.metadata.create_all(bind=engine)
    notifier = get_notifier()

    if not settings.slack_enabled:
        log.warning("SLACK_WEBHOOK_URL is not set — alerts will be logged, not delivered")

    log.info(
        "Scheduler started",
        extra={
            "tick_seconds": settings.scheduler_tick_seconds,
            "failure_threshold": settings.failure_threshold,
            "concurrency": settings.check_concurrency,
        },
    )

    while not _shutdown:
        started = time.monotonic()
        try:
            db = SessionLocal()
            try:
                monitors = due_monitors(db)
                checks = run_due_checks(db, monitors, notifier=notifier)
                for monitor, check in zip(monitors, checks, strict=False):
                    log.info(
                        "%s %s",
                        "UP  " if check.is_up else "DOWN",
                        monitor.name,
                        extra={
                            "monitor": monitor.name,
                            "url": monitor.url,
                            "is_up": check.is_up,
                            "status_code": check.status_code,
                            "response_time_ms": check.response_time_ms,
                            "error": check.error,
                        },
                    )
                if monitors:
                    log.debug(
                        "Tick complete",
                        extra={
                            "checked": len(checks),
                            "duration_ms": round((time.monotonic() - started) * 1000, 1),
                        },
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


def start_background_thread() -> threading.Thread:
    """Run the scheduler inside the web process.

    Two processes is the better shape and stays the default: a hung check
    cannot then stall page rendering. This mode exists for hosts whose free
    tier has no worker process type, where the alternative is not deploying
    the poller at all.
    """
    thread = threading.Thread(
        target=run_forever,
        kwargs={"install_signal_handlers": False},
        name="scheduler",
        daemon=True,
    )
    thread.start()
    log.info("Scheduler started in-process alongside the web server")
    return thread


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        sys.exit(0)
