"""Topology and network data API — serves pole, DT, and topology data for the map."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.pole import Pole
from app.models.pole_state import PoleState
from app.models.topology import TopologyEdge
from app.models.transformer import Transformer
from app.services.scheduler import build_topology_cache

router = APIRouter(tags=["topology"])


@router.get("/poles")
async def list_poles(
    dt_id: str | None = Query(None),
    feeder_id: str | None = Query(None),
    limit: int = Query(500, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """List poles with their current state (for map rendering)."""
    query = (
        select(Pole, PoleState)
        .join(PoleState, Pole.pole_id == PoleState.pole_id, isouter=True)
        .limit(limit)
    )

    if dt_id:
        query = query.where(Pole.dt_id == dt_id)
    if feeder_id:
        query = query.where(Pole.feeder_id == feeder_id)

    result = await session.execute(query)
    rows = result.all()

    return [
        {
            "pole_id": pole.pole_id,
            "lat": pole.lat,
            "lon": pole.lon,
            "dt_id": pole.dt_id,
            "feeder_id": pole.feeder_id,
            "device_id": pole.device_id,
            "has_device": pole.device_id is not None,
            "pincode": pole.pincode,
            "energized": state.energized if state else None,
            "classification": state.classification if state else "unknown",
        }
        for pole, state in rows
    ]


@router.get("/transformers")
async def list_transformers(
    feeder_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """List distribution transformers."""
    query = select(Transformer)
    if feeder_id:
        query = query.where(Transformer.feeder_id == feeder_id)

    result = await session.execute(query)
    dts = result.scalars().all()

    return [
        {
            "dt_id": dt.dt_id,
            "feeder_id": dt.feeder_id,
            "lat": dt.lat,
            "lon": dt.lon,
            "capacity_kva": dt.capacity_kva,
            "households_served": dt.households_served,
        }
        for dt in dts
    ]


@router.get("/topology/edges")
async def list_topology_edges(
    dt_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """List topology edges (for tree visualization)."""
    query = select(TopologyEdge)
    if dt_id:
        query = query.where(TopologyEdge.dt_id == dt_id)

    result = await session.execute(query)
    edges = result.scalars().all()

    return [
        {
            "child_pole_id": e.child_pole_id,
            "parent_pole_id": e.parent_pole_id,
            "dt_id": e.dt_id,
            "source": e.source,
            "inferred_confidence": e.inferred_confidence,
        }
        for e in edges
    ]


@router.post("/topology/rebuild")
async def rebuild_topology():
    """Rebuild the topology cache (re-runs MST inference)."""
    await build_topology_cache()
    return {"message": "Topology cache rebuilt."}
