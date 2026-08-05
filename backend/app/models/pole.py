"""Pole model — represents a physical utility pole in the LT network."""

from sqlalchemy import Column, Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.database import Base


class Pole(Base):
    __tablename__ = "poles"

    pole_id = Column(String, primary_key=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    feeder_id = Column(String, nullable=False, index=True)
    dt_id = Column(String, ForeignKey("transformers.dt_id"), nullable=False, index=True)
    seq_on_line = Column(Float, nullable=True)  # NULL for ~60% of DTs
    parent_pole_id = Column(String, nullable=True)  # May reference ROOT-{dt_id} virtual node
    pole_type: str = Column(
        SAEnum("wooden", "steel", "concrete", "rcc", name="pole_type_enum"),
        nullable=False,
        default="concrete",
    )
    ward = Column(String, nullable=True)
    pincode = Column(String, nullable=True)  # NULL for ~3%
    device_id = Column(String, nullable=True, unique=True)  # NULL for ~9%

    # Relationships
    transformer = relationship("Transformer", back_populates="poles")
    state = relationship("PoleState", back_populates="pole", uselist=False)
