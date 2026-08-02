"""Transformer model — distribution transformer (DT) that is the root of each pole tree."""

from sqlalchemy import Column, Float, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Transformer(Base):
    __tablename__ = "transformers"

    dt_id = Column(String, primary_key=True)
    feeder_id = Column(String, nullable=False, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    capacity_kva = Column(Float, nullable=False, default=100.0)
    households_served = Column(Integer, nullable=False, default=50)

    # Relationships
    poles = relationship("Pole", back_populates="transformer")
