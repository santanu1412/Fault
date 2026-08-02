"""Topology edge model — stores both surveyed and inferred parent-child edges."""

from sqlalchemy import Column, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum

from app.database import Base


class TopologyEdge(Base):
    __tablename__ = "topology_edges"

    child_pole_id = Column(
        String, ForeignKey("poles.pole_id"), primary_key=True
    )
    parent_pole_id = Column(
        String, nullable=False, index=True
    )  # May reference ROOT-{dt_id} virtual nodes not in poles table
    dt_id = Column(String, ForeignKey("transformers.dt_id"), nullable=False, index=True)
    source = Column(
        SAEnum("surveyed", "inferred", name="topology_source_enum"),
        nullable=False,
    )
    inferred_confidence = Column(Float, nullable=True)  # 0.0-1.0, NULL for surveyed
