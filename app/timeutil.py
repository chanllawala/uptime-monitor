from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp.

    datetime.utcnow() is deprecated, but storing tz-aware values behaves
    differently between SQLite and Postgres and invites naive/aware comparison
    errors. Everything here is UTC by construction, so the tzinfo is dropped
    deliberately and consistently.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def humanize_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
