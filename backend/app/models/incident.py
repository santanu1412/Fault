"""Incident model — a detected fault region with boundary, coordinates, and confidence."""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

JSONType = JSON().with_variant(JSONB, "postgresql")
ArrayType = JSON().with_variant(ARRAY(String), "postgresql")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind: str = Column(  # type: ignore
        SAEnum("span", "dt", "feeder", "sensor_only", name="incident_kind_enum"),
        nullable=False,
    )
    boundary_edges = Column(JSONType, nullable=False, default=list)
    # e.g. [{"parent": "P-0042", "child": "P-0043", "source": "surveyed"}]
    dark_pole_ids: list[str] = Column(ArrayType, nullable=False, default=list)  # type: ignore
    centroid_lat = Column(Float, nullable=True)
    centroid_lon = Column(Float, nullable=True)
    pincode = Column(String, nullable=True)
    dt_id = Column(String, ForeignKey("transformers.dt_id"), nullable=True, index=True)
    feeder_id = Column(String, nullable=True, index=True)
    households_affected = Column(Integer, nullable=False, default=0)
    confidence = Column(Float, nullable=False, default=0.5)
    confidence_breakdown = Column(JSONType, nullable=True, default=dict)
    # e.g. {"topology": 0.7, "device_coverage": 0.8, "recency": 0.9, "rssi": 0.5, "overall": 0.75}
    topology_basis: str = Column(  # type: ignore
        SAEnum("surveyed", "inferred", "mixed", name="topology_basis_enum"),
        nullable=False,
        default="inferred",
    )
    status = Column(String, nullable=False, default="active")  # active, resolved
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    ticket = relationship("Ticket", back_populates="incident", uselist=False)
