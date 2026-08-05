"""Fault simulator — generates realistic telemetry events to drive the pipeline.

All simulation works by injecting telemetry messages into the same ingest pipeline
that real devices would use. This ensures the full pipeline is always exercised.
"""

import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.pole import Pole
from app.models.transformer import Transformer
from app.services.ingest import ingest_telemetry

logger = logging.getLogger("fault_system.simulator")

# Global sequence counter for simulated messages
_sim_seq_counter = 100000


def _next_seq() -> int:
    """Get next unique sequence number for simulated messages."""
    global _sim_seq_counter
    _sim_seq_counter += 1
    return _sim_seq_counter


async def simulate_span_fault(
    session: AsyncSession,
    dt_id: str,
    start_pole_index: int = 3,
    drop_dying_message_pct: float = 0.3,
) -> dict:
    """Simulate a span fault — poles from start_pole_index onward go dark.

    Args:
        dt_id: Target distribution transformer
        start_pole_index: Which pole in the branch to start the fault at
        drop_dying_message_pct: Fraction of dying messages dropped (FW 1.2 simulation)
    """
    # Get poles for this DT, ordered by pole_id
    result = await session.execute(
        select(Pole).where(Pole.dt_id == dt_id).order_by(Pole.pole_id)
    )
    poles = result.scalars().all()

    if not poles:
        return {"error": f"No poles found for DT {dt_id}"}

    affected_poles = poles[start_pole_index:]
    now = datetime.now(timezone.utc)
    messages = []

    for pole in affected_poles:
        if not pole.device_id:
            continue  # No device — can't send telemetry

        # Simulate: some poles send dying_gasp, some just go silent (FW 1.2)
        if random.random() > drop_dying_message_pct:
            messages.append({
                "device_id": pole.device_id,
                "seq": _next_seq(),
                "event": "power_lost",
                "energized": False,
                "ts": now.isoformat(),
                "battery_mv": random.randint(2800, 3200),
                "rssi": random.uniform(-85, -60),
                "fw": random.choice(["1.0", "1.1", "2.0", "2.1"]),
            })
        # else: FW 1.2 silent death — no message sent

    # Ingest the generated telemetry
    ingest_res = await ingest_telemetry(session, messages)

    return {
        "scenario": "span_fault",
        "dt_id": dt_id,
        "affected_poles": len(affected_poles),
        "messages_sent": len(messages),
        "messages_dropped": len(affected_poles) - len(messages),
        "ingest_result": ingest_res,
    }


async def simulate_dt_fault(
    session: AsyncSession,
    dt_id: str,
    drop_dying_message_pct: float = 0.3,
) -> dict:
    """Simulate a DT-level fault — entire DT goes dark."""
    return await simulate_span_fault(
        session, dt_id, start_pole_index=0, drop_dying_message_pct=drop_dying_message_pct
    )


async def simulate_feeder_fault(
    session: AsyncSession,
    feeder_id: str,
    drop_dying_message_pct: float = 0.3,
) -> dict:
    """Simulate a feeder-level fault — all DTs on the feeder go dark."""
    result = await session.execute(
        select(Transformer.dt_id).where(Transformer.feeder_id == feeder_id)
    )
    dt_ids = [r[0] for r in result.all()]

    results = []
    for dt_id in dt_ids:
        r = await simulate_dt_fault(session, dt_id, drop_dying_message_pct)
        results.append(r)

    return {
        "scenario": "feeder_fault",
        "feeder_id": feeder_id,
        "dts_affected": len(dt_ids),
        "results": results,
    }


async def simulate_sensor_death(
    session: AsyncSession,
    pole_id: str,
) -> dict:
    """Simulate a dead sensor — the device goes silent without sending power_lost.

    This should NOT trigger a fault ticket if children are live.
    """
    result = await session.execute(
        select(Pole).where(Pole.pole_id == pole_id)
    )
    pole = result.scalar_one_or_none()
    if not pole or not pole.device_id:
        return {"error": f"Pole {pole_id} not found or has no device"}

    now = datetime.now(timezone.utc)

    # Send a dying_gasp-like message (low battery) then go silent
    messages = [{
        "device_id": pole.device_id,
        "seq": _next_seq(),
        "event": "power_lost",
        "energized": False,
        "ts": now.isoformat(),
        "battery_mv": 2200,  # Very low battery
        "rssi": -95,  # Very weak signal
        "fw": "1.2",  # Known problematic firmware
    }]

    ingest_res = await ingest_telemetry(session, messages)

    return {
        "scenario": "sensor_death",
        "pole_id": pole_id,
        "device_id": pole.device_id,
        "ingest_result": ingest_res,
    }


async def simulate_repair(
    session: AsyncSession,
    incident_id: int,
) -> dict:
    """Simulate power restoration for all poles in an incident."""
    result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
    )
    incident = result.scalar_one_or_none()
    if not incident:
        return {"error": f"Incident #{incident_id} not found"}

    now = datetime.now(timezone.utc)
    messages = []

    dark_ids = incident.dark_pole_ids or []
    if dark_ids:
        result = await session.execute(
            select(Pole.device_id)
            .where(Pole.pole_id.in_(dark_ids), Pole.device_id.isnot(None))
        )
        for device_id in result.scalars().all():
            messages.append({
                "device_id": device_id,
                "seq": _next_seq(),
                "event": "power_restored",
                "energized": True,
                "ts": now.isoformat(),
                "battery_mv": random.randint(3400, 3600),
                "rssi": random.uniform(-70, -40),
                "fw": random.choice(["2.0", "2.1"]),
            })

    ingest_res = await ingest_telemetry(session, messages)

    return {
        "scenario": "repair",
        "incident_id": incident_id,
        "poles_restored": len(messages),
        "ingest_result": ingest_res,
    }


async def simulate_heartbeat_burst(
    session: AsyncSession,
    count: int = 500,
) -> dict:
    """Generate a burst of normal heartbeats for throughput testing."""
    result = await session.execute(
        select(Pole.device_id).where(Pole.device_id.isnot(None)).limit(count)
    )
    device_ids = [r[0] for r in result.all()]

    now = datetime.now(timezone.utc)
    messages = []

    for device_id in device_ids:
        messages.append({
            "device_id": device_id,
            "seq": _next_seq(),
            "event": "heartbeat",
            "energized": True,
            "ts": now.isoformat(),
            "battery_mv": random.randint(3200, 3600),
            "rssi": random.uniform(-75, -40),
            "fw": random.choice(["1.0", "1.1", "2.0", "2.1"]),
        })

    ingest_res = await ingest_telemetry(session, messages)

    return {
        "scenario": "heartbeat_burst",
        "messages_sent": len(messages),
        "ingest_result": ingest_res,
    }


async def get_available_targets(session: AsyncSession) -> dict:
    """Return available simulation targets (DTs, feeders, poles)."""
    # Get some DTs
    result = await session.execute(
        select(Transformer.dt_id, Transformer.feeder_id, Transformer.households_served)
        .limit(20)
    )
    dts = [{"dt_id": r[0], "feeder_id": r[1], "households": r[2]} for r in result.all()]

    # Get unique feeder IDs
    feeder_ids = list({dt["feeder_id"] for dt in dts})

    # Get some poles with devices
    result = await session.execute(
        select(Pole.pole_id, Pole.dt_id, Pole.device_id)
        .where(Pole.device_id.isnot(None))
        .limit(20)
    )
    poles = [{"pole_id": r[0], "dt_id": r[1], "device_id": r[2]} for r in result.all()]

    return {
        "transformers": dts,
        "feeders": feeder_ids,
        "poles": poles,
    }
