"""Incidents API — list and view fault incidents."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.incident import Incident
from app.models.pole import Pole
from app.models.pole_state import PoleState

router = APIRouter(tags=["incidents"])


@router.get("/incidents")
async def list_incidents(
    status: str | None = Query(None, description="Filter by status: active, resolved"),
    kind: str | None = Query(None, description="Filter by kind: span, dt, feeder"),
    feeder_id: str | None = Query(None),
    dt_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List incidents, sorted by most recent first."""
    query = select(Incident).order_by(desc(Incident.created_at)).limit(limit)

    if status:
        query = query.where(Incident.status == status)
    if kind:
        query = query.where(Incident.kind == kind)
    if feeder_id:
        query = query.where(Incident.feeder_id == feeder_id)
    if dt_id:
        query = query.where(Incident.dt_id == dt_id)

    result = await session.execute(query)
    incidents = result.scalars().all()

    return [
        {
            "id": inc.id,
            "kind": inc.kind,
            "status": inc.status,
            "boundary_edges": inc.boundary_edges,
            "dark_pole_count": len(inc.dark_pole_ids) if inc.dark_pole_ids else 0,
            "centroid_lat": inc.centroid_lat,
            "centroid_lon": inc.centroid_lon,
            "pincode": inc.pincode,
            "dt_id": inc.dt_id,
            "feeder_id": inc.feeder_id,
            "households_affected": inc.households_affected,
            "confidence": inc.confidence,
            "confidence_breakdown": inc.confidence_breakdown,
            "topology_basis": inc.topology_basis,
            "created_at": inc.created_at.isoformat() if inc.created_at else None,
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        }
        for inc in incidents
    ]


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get full incident detail including dark poles and their states."""
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    inc = result.scalar_one_or_none()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Get pole details for dark poles in a single batch query
    pole_details = []
    dark_ids = inc.dark_pole_ids or []
    if dark_ids:
        pole_result = await session.execute(
            select(Pole, PoleState)
            .join(PoleState, Pole.pole_id == PoleState.pole_id, isouter=True)
            .where(Pole.pole_id.in_(dark_ids))
        )
        for row in pole_result.all():
            pole, state = row
            pole_details.append({
                "pole_id": pole.pole_id,
                "lat": pole.lat,
                "lon": pole.lon,
                "device_id": pole.device_id,
                "has_device": pole.device_id is not None,
                "energized": state.energized if state else None,
                "classification": state.classification if state else "unknown",
                "last_confirmed_at": state.last_confirmed_at.isoformat() if state and state.last_confirmed_at else None,
            })

    return {
        "id": inc.id,
        "kind": inc.kind,
        "status": inc.status,
        "boundary_edges": inc.boundary_edges,
        "dark_pole_ids": inc.dark_pole_ids,
        "dark_poles": pole_details,
        "centroid_lat": inc.centroid_lat,
        "centroid_lon": inc.centroid_lon,
        "pincode": inc.pincode,
        "dt_id": inc.dt_id,
        "feeder_id": inc.feeder_id,
        "households_affected": inc.households_affected,
        "confidence": inc.confidence,
        "confidence_breakdown": inc.confidence_breakdown,
        "topology_basis": inc.topology_basis,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
    }


@router.get("/network/stats")
async def get_network_stats(
    session: AsyncSession = Depends(get_session),
):
    """Get overall network statistics."""
    from sqlalchemy import func

    # Count poles by state
    result = await session.execute(
        select(
            PoleState.classification,
            func.count(PoleState.pole_id),
        ).group_by(PoleState.classification)
    )
    state_counts = {r[0]: r[1] for r in result.all()}

    # Count active incidents
    result = await session.execute(
        select(func.count(Incident.id)).where(Incident.status == "active")
    )
    active_incidents = result.scalar() or 0

    # Total poles and DTs
    result = await session.execute(select(func.count(Pole.pole_id)))
    total_poles = result.scalar() or 0

    from app.models.transformer import Transformer
    result = await session.execute(select(func.count(Transformer.dt_id)))
    total_dts = result.scalar() or 0

    return {
        "total_poles": total_poles,
        "total_dts": total_dts,
        "pole_states": state_counts,
        "active_incidents": active_incidents,
    }
