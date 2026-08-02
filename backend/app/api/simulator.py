"""Simulator API — endpoints for fault injection and scenario control."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.simulator import (
    get_available_targets,
    simulate_dt_fault,
    simulate_feeder_fault,
    simulate_heartbeat_burst,
    simulate_repair,
    simulate_sensor_death,
    simulate_span_fault,
)

router = APIRouter(prefix="/simulate", tags=["simulator"])


class SpanFaultRequest(BaseModel):
    dt_id: str
    start_pole_index: int = 3
    drop_dying_message_pct: float = 0.3


class DtFaultRequest(BaseModel):
    dt_id: str
    drop_dying_message_pct: float = 0.3


class FeederFaultRequest(BaseModel):
    feeder_id: str
    drop_dying_message_pct: float = 0.3


class SensorDeathRequest(BaseModel):
    pole_id: str


class RepairRequest(BaseModel):
    incident_id: int


class HeartbeatBurstRequest(BaseModel):
    count: int = 500


@router.post("/fault/span")
async def inject_span_fault(
    request: SpanFaultRequest,
    session: AsyncSession = Depends(get_session),
):
    """Inject a span fault — poles from a given index onward go dark."""
    return await simulate_span_fault(
        session, request.dt_id, request.start_pole_index, request.drop_dying_message_pct
    )


@router.post("/fault/dt")
async def inject_dt_fault(
    request: DtFaultRequest,
    session: AsyncSession = Depends(get_session),
):
    """Inject a DT-level fault — entire DT goes dark."""
    return await simulate_dt_fault(
        session, request.dt_id, request.drop_dying_message_pct
    )


@router.post("/fault/feeder")
async def inject_feeder_fault(
    request: FeederFaultRequest,
    session: AsyncSession = Depends(get_session),
):
    """Inject a feeder-level fault — all DTs on the feeder go dark."""
    return await simulate_feeder_fault(
        session, request.feeder_id, request.drop_dying_message_pct
    )


@router.post("/sensor-death")
async def inject_sensor_death(
    request: SensorDeathRequest,
    session: AsyncSession = Depends(get_session),
):
    """Simulate a dead sensor (device modem failure)."""
    return await simulate_sensor_death(session, request.pole_id)


@router.post("/repair")
async def inject_repair(
    request: RepairRequest,
    session: AsyncSession = Depends(get_session),
):
    """Simulate power restoration for an incident's poles."""
    return await simulate_repair(session, request.incident_id)


@router.post("/heartbeat-burst")
async def inject_heartbeat_burst(
    request: HeartbeatBurstRequest,
    session: AsyncSession = Depends(get_session),
):
    """Generate a burst of normal heartbeats for throughput testing."""
    return await simulate_heartbeat_burst(session, request.count)


@router.get("/targets")
async def list_targets(
    session: AsyncSession = Depends(get_session),
):
    """List available simulation targets (DTs, feeders, poles)."""
    return await get_available_targets(session)


@router.get("/scenarios")
async def list_scenarios():
    """List pre-built simulation scenarios."""
    return [
        {
            "id": "span_fault",
            "name": "Simple Span Fault",
            "description": "One wire break on a DT — poles from index 3 onward go dark",
            "endpoint": "/api/simulate/fault/span",
        },
        {
            "id": "dt_fault",
            "name": "DT Fuse Blow",
            "description": "Entire distribution transformer goes dark",
            "endpoint": "/api/simulate/fault/dt",
        },
        {
            "id": "feeder_fault",
            "name": "Feeder Fault",
            "description": "All DTs on a feeder go dark",
            "endpoint": "/api/simulate/fault/feeder",
        },
        {
            "id": "sensor_death",
            "name": "Dead Sensor (Noise)",
            "description": "Single device dies — should NOT trigger a fault ticket if children are live",
            "endpoint": "/api/simulate/sensor-death",
        },
        {
            "id": "heartbeat_burst",
            "name": "Heartbeat Burst",
            "description": "Generate a burst of normal heartbeats for throughput testing",
            "endpoint": "/api/simulate/heartbeat-burst",
        },
    ]
