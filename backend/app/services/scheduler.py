"""Background scheduler — runs the localization engine periodically.

Polls for state changes, runs localization, creates/updates incidents and tickets,
and checks for restoration on open tickets.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.incident import Incident
from app.models.outage import ScheduledOutage
from app.models.pole import Pole
from app.models.pole_state import PoleState
from app.models.ticket import Ticket
from app.services.ai_narrative import generate_ai_narrative
from app.services.localization import DetectedIncident, PoleStateInfo, localize_all
from app.services.ticket_manager import auto_verify_ticket, create_ticket_for_incident
from app.services.topology_builder import DtTree, build_all_trees

logger = logging.getLogger("fault_system.scheduler")

# Cached topology trees (rebuilt on demand)
_trees_cache: dict[str, DtTree] = {}
_trees_built = False


async def build_topology_cache():
    """Build and cache all DT trees."""
    global _trees_cache, _trees_built
    async with async_session() as session:
        _trees_cache = await build_all_trees(session)
        _trees_built = True
        logger.info(f"Topology cache built: {len(_trees_cache)} DT trees.")


def get_trees_cache() -> dict[str, DtTree]:
    """Get the cached topology trees."""
    return _trees_cache


async def _load_pole_states(session: AsyncSession) -> dict[str, PoleStateInfo]:
    """Load all pole states into a dict for localization."""
    result = await session.execute(
        select(
            PoleState.pole_id,
            PoleState.energized,
            PoleState.classification,
            PoleState.confidence,
            PoleState.last_confirmed_at,
        )
    )

    # Also need to know which poles have devices
    device_result = await session.execute(
        select(Pole.pole_id, Pole.device_id)
    )
    device_map = {r[0]: r[1] for r in device_result.all()}

    states = {}
    for r in result.all():
        states[r[0]] = PoleStateInfo(
            pole_id=r[0],
            energized=r[1],
            classification=r[2],
            confidence=r[3],
            last_confirmed_at=r[4],
            has_device=device_map.get(r[0]) is not None,
        )

    return states


async def _load_scheduled_outage_targets(session: AsyncSession) -> set[str]:
    """Load currently active scheduled outage targets with buffer."""
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(ScheduledOutage.target_id).where(
            ScheduledOutage.start_at <= now,
            ScheduledOutage.end_at >= now,
        )
    )

    return {r[0] for r in result.all()}


async def _create_or_update_incident(
    session: AsyncSession,
    detected: DetectedIncident,
) -> int | None:
    """Create a new incident or skip if it overlaps with an existing one."""
    # Check for overlapping active incidents (same dark poles)
    dark_set = set(detected.dark_pole_ids)

    result = await session.execute(
        select(Incident).where(Incident.status == "active")
    )
    existing_incidents = result.scalars().all()

    for existing in existing_incidents:
        existing_dark = set(existing.dark_pole_ids or [])
        # If the new incident's dark poles are a subset of an existing incident, skip
        if dark_set.issubset(existing_dark):
            return None
        # If there's significant overlap (>50%), skip
        if existing_dark and len(dark_set & existing_dark) / len(dark_set) > 0.5:
            return None

    # Look up pincode from the nearest pole with a known pincode
    pincode = detected.pincode
    if not pincode:
        for pid in detected.dark_pole_ids:
            result = await session.execute(
                select(Pole.pincode).where(
                    Pole.pole_id == pid,
                    Pole.pincode.isnot(None),
                )
            )
            pin = result.scalar()
            if pin:
                pincode = pin
                break

    # Create incident
    boundary_data = [
        {
            "parent": e.parent_pole_id,
            "child": e.child_pole_id,
            "source": e.edge_source,
            "confidence": e.edge_confidence,
        }
        for e in detected.boundary_edges
    ]

    incident = Incident(
        kind=detected.kind,
        boundary_edges=boundary_data,
        dark_pole_ids=detected.dark_pole_ids,
        centroid_lat=detected.centroid_lat,
        centroid_lon=detected.centroid_lon,
        pincode=pincode,
        dt_id=detected.dt_id,
        feeder_id=detected.feeder_id,
        households_affected=detected.households_affected,
        confidence=detected.confidence,
        topology_basis=detected.topology_basis,
        confidence_breakdown=detected.confidence_breakdown,
        status="active",
    )
    session.add(incident)
    await session.flush()

    logger.info(
        f"Created incident #{incident.id}: {detected.kind} on {detected.dt_id or detected.feeder_id}, "
        f"{len(detected.dark_pole_ids)} dark poles, confidence={detected.confidence}"
    )

    return incident.id


async def run_localization_cycle():
    """Run one cycle of the localization engine."""
    global _trees_cache

    if not _trees_built:
        await build_topology_cache()

    async with async_session() as session:
        # Load current pole states
        pole_states = await _load_pole_states(session)

        # Load scheduled outage targets
        outage_targets = await _load_scheduled_outage_targets(session)

        # Run localization
        detected_incidents = localize_all(_trees_cache, pole_states, outage_targets)

        # Create incidents and tickets for new detections
        for detected in detected_incidents:
            incident_id = await _create_or_update_incident(session, detected)

            if incident_id:
                # Generate AI narrative
                incident_data = {
                    "kind": detected.kind,
                    "boundary_edges": [
                        {"parent": e.parent_pole_id, "child": e.child_pole_id}
                        for e in detected.boundary_edges
                    ],
                    "centroid_lat": detected.centroid_lat,
                    "centroid_lon": detected.centroid_lon,
                    "pincode": detected.pincode,
                    "households_affected": detected.households_affected,
                    "confidence": detected.confidence,
                    "topology_basis": detected.topology_basis,
                    "confidence_breakdown": detected.confidence_breakdown,
                }
                narrative = await generate_ai_narrative(incident_data)

                # Create ticket
                await create_ticket_for_incident(session, incident_id, narrative)

        # Check for restoration on open resolved tickets
        result = await session.execute(
            select(Ticket).where(Ticket.status == "resolved")
        )
        resolved_tickets = result.scalars().all()

        for ticket in resolved_tickets:
            await auto_verify_ticket(session, ticket.id)

        await session.commit()


async def scheduler_loop():
    """Main scheduler loop — runs localization periodically."""
    interval = settings.poll_interval_seconds
    logger.info(f"Scheduler started. Polling every {interval}s.")

    while True:
        try:
            await run_localization_cycle()
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)

        await asyncio.sleep(interval)
