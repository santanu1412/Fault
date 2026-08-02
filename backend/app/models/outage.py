"""Scheduled outage model — mocked load-shedding/maintenance feed."""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.database import Base


class ScheduledOutage(Base):
    __tablename__ = "scheduled_outages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(
        SAEnum("pole", "dt", "feeder", name="outage_scope_enum"),
        nullable=False,
    )
    target_id = Column(String, nullable=False, index=True)  # pole_id, dt_id, or feeder_id
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(String, nullable=True, default="Scheduled maintenance")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
