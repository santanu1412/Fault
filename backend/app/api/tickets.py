"""Tickets API — lifecycle management with audit trail."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.incident import Incident
from app.models.ticket import Ticket
from app.services.ai_narrative import ask_ticket_question
from app.services.ticket_manager import TransitionError, force_close_ticket, transition_ticket

router = APIRouter(tags=["tickets"])


class TransitionRequest(BaseModel):
    target_status: str
    reason: str | None = None


class ForceCloseRequest(BaseModel):
    supervisor_id: str = Field(..., pattern=r"^SUP-\d{3,6}$")
    override_reason: str = Field(..., min_length=20, max_length=1000)

    @field_validator("override_reason")
    @classmethod
    def reason_must_be_substantive(cls, v: str) -> str:
        v = v.strip()
        # Block low-effort audit entries: "done", "fixed", "asdfasdfasdfasdfasdf"
        if len(set(v.lower().replace(" ", ""))) < 8:
            raise ValueError("override_reason must be a substantive explanation")
        return v


class AskRequest(BaseModel):
    question: str


@router.get("/tickets")
async def list_tickets(
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List tickets, sorted by most recent first."""
    query = (
        select(Ticket, Incident)
        .join(Incident, Ticket.incident_id == Incident.id)  # type: ignore
        .order_by(desc(Ticket.created_at))
        .limit(limit)
    )

    if status:
        query = query.where(Ticket.status == status)  # type: ignore

    result = await session.execute(query)
    rows = result.all()

    return [
        {
            "id": ticket.id,
            "incident_id": ticket.incident_id,
            "status": ticket.status,
            "ai_narrative": ticket.ai_narrative,
            "history": ticket.history,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
            "incident": {
                "id": incident.id,
                "kind": incident.kind,
                "status": incident.status,
                "centroid_lat": incident.centroid_lat,
                "centroid_lon": incident.centroid_lon,
                "pincode": incident.pincode,
                "dt_id": incident.dt_id,
                "feeder_id": incident.feeder_id,
                "households_affected": incident.households_affected,
                "confidence": incident.confidence,
                "confidence_breakdown": incident.confidence_breakdown,
                "topology_basis": incident.topology_basis,
                "dark_pole_count": len(incident.dark_pole_ids) if incident.dark_pole_ids else 0,
                "boundary_edges": incident.boundary_edges,
            },
        }
        for ticket, incident in rows
    ]


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get full ticket detail with incident information."""
    result = await session.execute(
        select(Ticket, Incident)
        .join(Incident, Ticket.incident_id == Incident.id)  # type: ignore
        .where(Ticket.id == ticket_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket, incident = row

    return {
        "id": ticket.id,
        "incident_id": ticket.incident_id,
        "status": ticket.status,
        "ai_narrative": ticket.ai_narrative,
        "history": ticket.history,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "incident": {
            "id": incident.id,
            "kind": incident.kind,
            "status": incident.status,
            "boundary_edges": incident.boundary_edges,
            "dark_pole_ids": incident.dark_pole_ids,
            "centroid_lat": incident.centroid_lat,
            "centroid_lon": incident.centroid_lon,
            "pincode": incident.pincode,
            "dt_id": incident.dt_id,
            "feeder_id": incident.feeder_id,
            "households_affected": incident.households_affected,
            "confidence": incident.confidence,
            "confidence_breakdown": incident.confidence_breakdown,
            "topology_basis": incident.topology_basis,
            "created_at": incident.created_at.isoformat() if incident.created_at else None,
        },
    }


@router.patch("/tickets/{ticket_id}/transition")
async def transition(
    ticket_id: int,
    request: TransitionRequest,
    session: AsyncSession = Depends(get_session),
):
    """Transition a ticket to a new status.

    Returns 409 if the transition is invalid (e.g., resolving when poles are still dark).
    """
    try:
        ticket = await transition_ticket(
            session,
            ticket_id,
            request.target_status,
            actor="operator",
            reason=request.reason,
        )
        return {
            "id": ticket.id,
            "status": ticket.status,
            "history": ticket.history,
            "message": f"Ticket transitioned to '{request.target_status}'",
        }
    except TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/tickets/{ticket_id}/ask")
async def ask_question(
    ticket_id: int,
    request: AskRequest,
    session: AsyncSession = Depends(get_session),
):
    """Ask a question about a ticket — answered using only the ticket's data."""
    result = await session.execute(
        select(Ticket, Incident)
        .join(Incident, Ticket.incident_id == Incident.id)  # type: ignore
        .where(Ticket.id == ticket_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket, incident = row

    ticket_data = {
        "ticket_id": ticket.id,
        "status": ticket.status,
        "kind": incident.kind,
        "boundary_edges": incident.boundary_edges,
        "dark_pole_ids": incident.dark_pole_ids,
        "dark_pole_count": len(incident.dark_pole_ids) if incident.dark_pole_ids else 0,
        "centroid_lat": incident.centroid_lat,
        "centroid_lon": incident.centroid_lon,
        "pincode": incident.pincode,
        "dt_id": incident.dt_id,
        "feeder_id": incident.feeder_id,
        "households_affected": incident.households_affected,
        "confidence": incident.confidence,
        "topology_basis": incident.topology_basis,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "history": ticket.history,
    }

    answer = await ask_ticket_question(ticket_data, request.question)
    return {"answer": answer}


@router.post("/tickets/{ticket_id}/force-close")
async def force_close(
    ticket_id: int,
    request: ForceCloseRequest,
    session: AsyncSession = Depends(get_session),
):
    """Supervisor override close (bypasses telemetry verification check for destroyed hardware)."""
    try:
        ticket = await force_close_ticket(
            session,
            ticket_id,
            request.supervisor_id,
            request.override_reason,
        )
        return {
            "id": ticket.id,
            "status": ticket.status,
            "history": ticket.history,
            "message": f"Ticket #{ticket.id} force-closed by supervisor {request.supervisor_id}",
        }
    except TransitionError as e:
        raise HTTPException(status_code=404, detail=str(e))
