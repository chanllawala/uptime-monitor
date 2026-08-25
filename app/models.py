from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base
from .timeutil import utcnow


class Monitor(Base):
    """A thing we watch: a URL, how often to poll it, and what counts as healthy."""

    __tablename__ = "monitors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    url = Column(String(500), nullable=False)
    method = Column(String(10), nullable=False, default="GET")
    expected_status = Column(Integer, nullable=False, default=200)
    interval_seconds = Column(Integer, nullable=False, default=60)
    timeout_seconds = Column(Integer, nullable=False, default=10)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    # Ordered by id rather than timestamp: consecutive checks can land on the
    # same clock tick, which would make checked_at an ambiguous sort key and
    # the history order nondeterministic.
    checks = relationship(
        "Check",
        back_populates="monitor",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Check.id",
    )
    incidents = relationship(
        "Incident",
        back_populates="monitor",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Incident.id",
    )


class Check(Base):
    """One poll of one monitor."""

    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, index=True)
    monitor_id = Column(
        Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    is_up = Column(Boolean, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    error = Column(Text, nullable=True)

    monitor = relationship("Monitor", back_populates="checks")


# The dashboard's most common query is "recent checks for this monitor",
# which this composite index serves directly.
Index("ix_checks_monitor_checked_at", Check.monitor_id, Check.checked_at.desc())


class Incident(Base):
    """A continuous period during which a monitor was considered down.

    Alerting is driven off incidents rather than individual failed checks, so a
    site that stays down for an hour produces one alert and one recovery
    notice, not one alert per poll.
    """

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    monitor_id = Column(
        Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at = Column(DateTime, nullable=False, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    cause = Column(Text, nullable=True)

    monitor = relationship("Monitor", back_populates="incidents")

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def duration_seconds(self, now=None) -> float:
        end = self.resolved_at or (now or utcnow())
        return (end - self.started_at).total_seconds()
