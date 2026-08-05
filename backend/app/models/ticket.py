"""Ticket model — lifecycle state machine with audit trail."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
# Valid ticket statuses in lifecycle order
TICKET_STATUSES = [
    "detected",
    "acknowledged",
    "crew_assigned",
    "resolved",
    "verified",
    "closed",
]

# Valid manual transitions (from -> [to])
VALID_TRANSITIONS = {
    "detected": ["acknowledged"],
    "acknowledged": ["crew_assigned"],
    "crew_assigned": ["resolved"],
    "resolved": [],  # Only system can move to 'verified'
    "verified": ["closed"],
    "closed": [],
}


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id: int = Column(  # type: ignore
        Integer, ForeignKey("incidents.id"), nullable=False, unique=True, index=True
    )
    status: str = Column(String, nullable=False, default="detected")  # type: ignore
    history = Column(JSONType, nullable=False, default=list)
    # e.g. [{"ts": "...", "from": "detected", "to": "acknowledged", "actor": "operator", "reason": "..."}]
    ai_narrative = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    incident = relationship("Incident", back_populates="ticket")
