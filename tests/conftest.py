import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Monitor


@pytest.fixture()
def db():
    """A fresh in-memory database per test.

    StaticPool keeps every connection pointed at the same in-memory database;
    without it each connection would get its own empty one.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def monitor(db):
    m = Monitor(
        name="Example",
        url="https://example.com",
        interval_seconds=60,
        timeout_seconds=5,
        expected_status=200,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class RecordingNotifier:
    """Captures alerts instead of sending them."""

    def __init__(self):
        self.messages = []

    def send(self, text, blocks=None):
        self.messages.append(text)
        return True

    @property
    def down_alerts(self):
        return [m for m in self.messages if "DOWN" in m]

    @property
    def recovery_alerts(self):
        return [m for m in self.messages if "RECOVERED" in m]


@pytest.fixture()
def notifier():
    return RecordingNotifier()
