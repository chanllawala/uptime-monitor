"""Create a starter set of monitors. Run with: python -m app.seed

Idempotent: monitors are keyed by URL, so re-running adds only what is missing.
"""

from .database import Base, SessionLocal, engine
from .models import Monitor

Base.metadata.create_all(bind=engine)

STARTERS = [
    # A deliberate mix: things that should stay up, and one that never will,
    # so the alerting path and the incident timeline have something to show.
    ("GitHub", "https://github.com", 60, 200),
    ("Cloudflare DNS", "https://1.1.1.1", 120, 200),
    ("Python.org", "https://www.python.org", 120, 200),
    # .invalid is reserved by RFC 2606 and can never resolve, so this target
    # fails deterministically — unlike public "always 503" services, which go
    # down in their own ways and muddy the demo.
    ("Unreachable host (demo)", "https://uptime-monitor-demo.invalid", 90, 200),
]


def run() -> None:
    db = SessionLocal()
    try:
        existing = {url for (url,) in db.query(Monitor.url).all()}
        added = 0
        for name, url, interval, expected in STARTERS:
            if url in existing:
                continue
            db.add(
                Monitor(
                    name=name,
                    url=url,
                    interval_seconds=interval,
                    expected_status=expected,
                )
            )
            added += 1
        db.commit()
        print(f"Seed complete: {added} monitor(s) added, {len(existing)} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
