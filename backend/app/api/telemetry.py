"""Telemetry ingestion API endpoint."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.ingest import ingest_telemetry

router = APIRouter(tags=["telemetry"])


class TelemetryMessage(BaseModel):
    device_id: str
    seq: int
    event: str = "heartbeat"
    energized: bool = True
    ts: Any = None
    battery_mv: int | None = None
    rssi: float | None = None
    fw: str | None = None


class TelemetryBatch(BaseModel):
    messages: list[TelemetryMessage]


class TelemetryResponse(BaseModel):
    accepted: int
    duplicated: int
    rejected: int
    total: int


@router.post("/telemetry", response_model=TelemetryResponse)
async def post_telemetry(
    batch: TelemetryBatch,
    session: AsyncSession = Depends(get_session),
):
    """Ingest a batch of telemetry messages.

    Deduplicates on (device_id, seq). Handles clock skew — ts is stored
    but seq is the ordering authority.
    """
    messages = [msg.model_dump() for msg in batch.messages]
    result = await ingest_telemetry(session, messages)
    return result


@router.post("/telemetry/single", response_model=TelemetryResponse)
async def post_single_telemetry(
    msg: TelemetryMessage,
    session: AsyncSession = Depends(get_session),
):
    """Ingest a single telemetry message (convenience endpoint)."""
    result = await ingest_telemetry(session, [msg.model_dump()])
    return result
