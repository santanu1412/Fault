"""Pole state model — derived real-time state of each pole from telemetry."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PoleState(Base):
    __tablename__ = "pole_state"

    pole_id = Column(
        String, ForeignKey("poles.pole_id"), primary_key=True
    )
    energized = Column(Boolean, nullable=False, default=True)
    confidence = Column(Float, nullable=False, default=1.0)
    last_confirmed_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_event_type = Column(String, nullable=True)  # heartbeat, power_lost, power_restored
    classification: str = Column(  # type: ignore
        SAEnum("ok", "dark_confirmed", "sensor_suspect", name="pole_classification_enum"),
        nullable=False,
        default="ok",
    )
    missed_heartbeats = Column(Float, nullable=False, default=0)

    # Relationships
    pole = relationship("Pole", back_populates="state")
