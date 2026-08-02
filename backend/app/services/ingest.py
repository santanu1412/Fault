"""Telemetry ingestion service — handles deduplication and pole state updates."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pole import Pole
from app.models.pole_state import PoleState
from app.models.telemetry import RawTelemetry

logger = logging.getLogger("fault_system.ingest")

# Cached device_id → pole_id mapping (rebuilt on first use or on demand)
_device_pole_cache: dict[str, str] = {}
_cache_loaded = False


async def _ensure_device_cache(session: AsyncSession) -> None:
    """Load device_id → pole_id mapping into memory cache."""
    global _device_pole_cache, _cache_loaded
    if _cache_loaded:
        return

    result = await session.execute(
        select(Pole.device_id, Pole.pole_id).where(Pole.device_id.isnot(None))
    )
    _device_pole_cache = {r[0]: r[1] for r in result.all()}
    _cache_loaded = True
    logger.info(f"Device cache loaded: {len(_device_pole_cache)} devices.")


def invalidate_device_cache() -> None:
    """Invalidate the device cache (call after seeding new data)."""
    global _device_pole_cache, _cache_loaded
    _device_pole_cache = {}
    _cache_loaded = False


async def ingest_telemetry(
    session: AsyncSession,
    messages: list[dict[str, Any]],
) -> dict[str, int]:
    """Ingest a batch of telemetry messages with dedup on (device_id, seq).

    Returns counts of accepted, duplicate, and rejected messages.
    """
    # Pre-load device → pole mapping for batch performance
    await _ensure_device_cache(session)

    accepted = 0
    duplicated = 0
    rejected = 0

    for msg in messages:
        try:
            device_id = msg.get("device_id")
            seq = msg.get("seq")
            event = msg.get("event", "heartbeat")
            energized = msg.get("energized", True)

            if not device_id or seq is None:
                rejected += 1
                continue

            # Look up pole_id from cached mapping (O(1) instead of DB query)
            pole_id = _device_pole_cache.get(device_id)

            # Insert raw telemetry (dedup via UNIQUE constraint)
            ts_raw = msg.get("ts")
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw)
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            stmt = (
                pg_insert(RawTelemetry)
                .values(
                    device_id=device_id,
                    pole_id=pole_id,
                    event=event,
                    energized=energized,
                    ts=ts,
                    seq=seq,
                    battery_mv=msg.get("battery_mv"),
                    rssi=msg.get("rssi"),
                    fw=msg.get("fw"),
                )
                .on_conflict_do_nothing(index_elements=["device_id", "seq"])
            )
            result = await session.execute(stmt)

            if result.rowcount == 0:
                duplicated += 1
                continue

            accepted += 1

            # Update pole state if we know which pole this is
            if pole_id:
                await _update_pole_state(session, pole_id, event, energized)

        except Exception as e:
            logger.error(f"Error ingesting message: {e}")
            rejected += 1

    await session.commit()

    return {
        "accepted": accepted,
        "duplicated": duplicated,
        "rejected": rejected,
        "total": len(messages),
    }


async def _update_pole_state(
    session: AsyncSession,
    pole_id: str,
    event: str,
    energized: bool,
) -> None:
    """Update the pole_state table based on incoming telemetry."""
    now = datetime.now(timezone.utc)

    if event in ("power_lost", "dying_gasp"):
        classification = "dark_confirmed"
        confidence = 0.95 if event == "power_lost" else 0.85
    elif event == "power_restored":
        classification = "ok"
        confidence = 1.0
    elif event == "heartbeat":
        if energized:
            classification = "ok"
            confidence = 1.0
        else:
            classification = "dark_confirmed"
            confidence = 0.9
    else:
        classification = "ok"
        confidence = 0.8

    stmt = (
        update(PoleState)
        .where(PoleState.pole_id == pole_id)
        .values(
            energized=energized,
            confidence=confidence,
            last_confirmed_at=now,
            last_event_type=event,
            classification=classification,
            missed_heartbeats=0 if energized else PoleState.missed_heartbeats,
        )
    )
    await session.execute(stmt)
