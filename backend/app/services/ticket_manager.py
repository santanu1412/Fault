"""Ticket manager — state machine with audit trail and telemetry-verified closure."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import publish_event
from app.models.incident import Incident
from app.models.pole_state import PoleState
from app.models.ticket import VALID_TRANSITIONS, Ticket

logger = logging.getLogger("fault_system.tickets")


class TransitionError(Exception):
    """Raised when a ticket transition is invalid."""


async def create_ticket_for_incident(
    session: AsyncSession,
    incident_id: int,
    ai_narrative: str | None = None,
) -> Ticket | None:
    """Create a ticket for a new incident, if one doesn't already exist."""
    # Check if ticket already exists for this incident
    result = await session.execute(
        select(Ticket).where(Ticket.incident_id == incident_id)  # type: ignore
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    now = datetime.now(timezone.utc)

    ticket = Ticket(
        incident_id=incident_id,
        status="detected",
        history=[{
            "ts": now.isoformat(),
            "from": None,
            "to": "detected",
            "actor": "system",
            "reason": "Fault detected by localization engine",
        }],
        ai_narrative=ai_narrative,
    )
    session.add(ticket)
    await session.flush()

    logger.info(f"Created ticket #{ticket.id} for incident #{incident_id}")
    return ticket


async def transition_ticket(
    session: AsyncSession,
    ticket_id: int,
    target_status: str,
    actor: str = "operator",
    reason: str | None = None,
) -> Ticket:
    """Transition a ticket to a new status with validation.

    Raises TransitionError if:
    - The transition is not valid per the state machine
    - Moving to 'resolved' but poles are still dark (telemetry-verified rejection)
    """
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise TransitionError(f"Ticket #{ticket_id} not found")

    current_status = str(ticket.status)

    # Check if transition is valid
    valid_targets = VALID_TRANSITIONS.get(current_status, [])
    if target_status not in valid_targets:
        raise TransitionError(
            f"Cannot transition from '{current_status}' to '{target_status}'. "
            f"Valid transitions: {valid_targets}"
        )

    # Special validation: cannot resolve if poles are still dark
    if target_status == "resolved":
        still_dark = await _check_poles_still_dark(session, int(ticket.incident_id))
        if still_dark:
            dark_ids = ", ".join(still_dark[:5])
            suffix = f" and {len(still_dark) - 5} more" if len(still_dark) > 5 else ""
            raise TransitionError(
                f"Cannot resolve: {len(still_dark)} poles still reporting dark "
                f"({dark_ids}{suffix}). Telemetry must confirm restoration before resolution."
            )

    # Apply transition
    now = datetime.now(timezone.utc)
    history_entry = {
        "ts": now.isoformat(),
        "from": current_status,
        "to": target_status,
        "actor": actor,
        "reason": reason or f"Manual transition by {actor}",
    }

    new_history = list(ticket.history) + [history_entry]

    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status=target_status, history=new_history)
    )
    await session.commit()

    # Refresh to get updated values
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one()

    logger.info(
        f"Ticket #{ticket_id}: {current_status} → {target_status} (by {actor})"
    )
    try:
        await publish_event("ticket_updated", {
            "ticket_id": ticket_id,
            "status": target_status,
            "actor": actor,
        })
    except Exception as e:
        logger.warning(f"Failed to publish SSE event: {e}")

    return ticket


async def auto_verify_ticket(
    session: AsyncSession,
    ticket_id: int,
) -> bool:
    """Auto-verify a ticket if all its incident's poles are now live.

    This is called by the scheduler when restoration telemetry arrives.
    Returns True if verification succeeded.
    """
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket or ticket.status != "resolved":
        return False

    still_dark = await _check_poles_still_dark(session, int(ticket.incident_id))
    if still_dark:
        return False

    # All poles live — auto-verify the ticket
    now = datetime.now(timezone.utc)
    history_entry = {
        "ts": now.isoformat(),
        "from": "resolved",
        "to": "verified",
        "actor": "system",
        "reason": "All poles confirmed energized via telemetry",
    }

    new_history = list(ticket.history) + [history_entry]

    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status="verified", history=new_history)
    )

    # Also mark the associated incident as resolved
    await session.execute(
        update(Incident)
        .where(Incident.id == ticket.incident_id)
        .values(status="resolved", resolved_at=now)
    )

    await session.commit()

    logger.info(f"Ticket #{ticket_id}: auto-verified — all poles restored. Incident #{ticket.incident_id} resolved.")
    return True


async def _check_poles_still_dark(
    session: AsyncSession,
    incident_id: int,
) -> list[str]:
    """Return list of pole IDs from an incident that are still dark.

    Uses a single batched query instead of per-pole lookups.
    """
    result = await session.execute(
        select(Incident.dark_pole_ids).where(Incident.id == incident_id)  # type: ignore
    )
    row = result.one_or_none()
    if not row or not row[0]:
        return []

    dark_pole_ids = row[0]

    # Batch query: get all pole states at once
    result = await session.execute(
        select(PoleState.pole_id, PoleState.classification)  # type: ignore
        .where(
            PoleState.pole_id.in_(dark_pole_ids),
            PoleState.classification == "dark_confirmed",
        )
    )

    return [r[0] for r in result.all()]


async def force_close_ticket(
    session: AsyncSession,
    ticket_id: int,
    supervisor_id: str,
    override_reason: str,
) -> Ticket:
    """Supervisor escape hatch to force-close a ticket when hardware is destroyed.

    Bypasses telemetry verification check while capturing a telemetry snapshot
    and logging a detailed audit entry.
    """
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise TransitionError(f"Ticket #{ticket_id} not found")

    # Idempotent: return existing ticket if already closed
    if ticket.status == "closed":
        return ticket

    now = datetime.now(timezone.utc)
    still_dark = await _check_poles_still_dark(session, int(ticket.incident_id))

    history_entry = {
        "ts": now.isoformat(),
        "from": ticket.status,
        "to": "closed",
        "actor": "supervisor",
        "actor_id": supervisor_id,
        "reason": override_reason,
        "close_method": "supervisor_override",
        "telemetry_snapshot": {"dark_poles_at_override": still_dark},
    }

    new_history = list(ticket.history) + [history_entry]

    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status="closed", history=new_history)
    )

    # Also resolve the associated incident
    await session.execute(
        update(Incident)
        .where(Incident.id == ticket.incident_id)
        .values(status="resolved", resolved_at=now)
    )

    await session.commit()

    # Re-fetch ticket to return
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one()

    logger.warning(
        f"FORCE_CLOSE Ticket #{ticket_id} (Incident #{ticket.incident_id}) "
        f"by {supervisor_id}. Reason: {override_reason}"
    )
    try:
        await publish_event("override_executed", {
            "ticket_id": ticket_id,
            "supervisor_id": supervisor_id,
            "reason": override_reason,
            "message": f"Supervisor override executed for Ticket #{ticket_id}",
        })
    except Exception as e:
        logger.warning(f"Failed to publish SSE event: {e}")

    return ticket
