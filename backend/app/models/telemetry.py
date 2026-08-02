"""Raw telemetry model — append-only log of all ingested device messages."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class RawTelemetry(Base):
    __tablename__ = "raw_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, nullable=False, index=True)
    pole_id = Column(String, nullable=True, index=True)
    event = Column(String, nullable=False)  # heartbeat, power_lost, power_restored, dying_gasp
    energized = Column(Boolean, nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False)  # Device timestamp (untrusted for ordering)
    seq = Column(Integer, nullable=False)  # Sequence number (trusted for ordering)
    battery_mv = Column(Integer, nullable=True)
    rssi = Column(Float, nullable=True)
    fw = Column(String, nullable=True)  # Firmware version
    received_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_device_seq"),
    )
