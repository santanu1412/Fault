"""AI narrative service — Claude API for dispatch briefs + grounded Q&A.

Falls back to template-based narratives if:
- No API key configured
- API call fails or times out (3s)
- Any other error
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("fault_system.ai")

# System prompts
NARRATIVE_SYSTEM_PROMPT = """You write short, factual dispatch briefs for electricity control-room operators from structured incident data. Given fields for fault type, location, confidence, and topology basis, produce 2–3 plain sentences: what kind of fault, where (coordinates + PIN), how many households, and one line on confidence caveats if topology was inferred rather than surveyed. Never invent facts not present in the input. No speculation about cause."""

QA_SYSTEM_PROMPT = """Answer the operator's question using only the ticket JSON provided. If the answer isn't in the data, say so plainly and suggest what data would answer it. Do not guess coordinates, times, or crew details."""


def generate_template_narrative(incident_data: dict[str, Any]) -> str:
    """Generate a deterministic template-based narrative (fallback)."""
    kind = incident_data.get("kind", "fault")
    kind_display = {
        "span": "Span fault",
        "dt": "Distribution transformer fault",
        "feeder": "Feeder-level fault",
        "sensor_only": "Sensor anomaly",
    }.get(kind, "Fault")

    lat = incident_data.get("centroid_lat", 0)
    lon = incident_data.get("centroid_lon", 0)
    pincode = incident_data.get("pincode", "unknown")
    households = incident_data.get("households_affected", 0)
    confidence = incident_data.get("confidence", 0)
    topo_basis = incident_data.get("topology_basis", "unknown")

    conf_pct = int(confidence * 100)

    # Build narrative
    parts = [
        f"{kind_display} detected near coordinates ({lat:.4f}°N, {lon:.4f}°E)",
    ]

    if pincode and pincode != "unknown":
        parts[0] += f", PIN code {pincode}"
    parts[0] += "."

    parts.append(f"Approximately {households} households affected.")

    if topo_basis == "inferred":
        parts.append(
            f"Confidence: {conf_pct}% (inferred topology — verify span boundaries before dispatch)."
        )
    elif topo_basis == "mixed":
        parts.append(
            f"Confidence: {conf_pct}% (mixed topology sources — partial verification recommended)."
        )
    else:
        parts.append(f"Confidence: {conf_pct}% (surveyed topology).")

    return " ".join(parts)


async def generate_ai_narrative(incident_data: dict[str, Any]) -> str:
    """Generate an AI-powered narrative using Claude API.

    Falls back to template if API is unavailable.
    """
    # Check if API key is configured
    if not settings.anthropic_api_key:
        logger.debug("No Anthropic API key — using template narrative.")
        return generate_template_narrative(incident_data)

    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.ai_model,
                    "max_tokens": 200,
                    "system": NARRATIVE_SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Generate a dispatch brief from this incident data:\n{incident_data}",
                        }
                    ],
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("content") and len(data["content"]) > 0:
                    return data["content"][0].get("text", generate_template_narrative(incident_data))

            logger.warning(f"Claude API returned {response.status_code} — using template.")
            return generate_template_narrative(incident_data)

    except Exception as e:
        logger.warning(f"Claude API error: {e} — using template narrative.")
        return generate_template_narrative(incident_data)


async def ask_ticket_question(
    ticket_data: dict[str, Any],
    question: str,
) -> str:
    """Answer an operator's question grounded in ticket data only.

    Falls back to a canned response if API is unavailable.
    """
    if not settings.anthropic_api_key:
        return "AI assistant is not configured. Please refer to the ticket details above."

    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.ai_model,
                    "max_tokens": 300,
                    "system": QA_SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Ticket data:\n{ticket_data}\n\n"
                                f"Operator question: {question}"
                            ),
                        }
                    ],
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("content") and len(data["content"]) > 0:
                    return data["content"][0].get("text", "Unable to process question at this time.")

            return "Unable to process question at this time. Please refer to the ticket details above."

    except Exception as e:
        logger.warning(f"Claude Q&A error: {e}")
        return "Unable to process question at this time. Please refer to the ticket details above."
