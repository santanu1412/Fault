"""Events API — Server-Sent Events (SSE) stream for real-time operator alerts.

Integrates with RedisBroadcaster for multi-pod cross-process SSE fan-out
and Last-Event-ID stream replay.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse

from app.services.redis_broadcaster import STREAM_KEY, Event, broadcaster

logger = logging.getLogger("fault_system.events")

router = APIRouter(tags=["events"])


from typing import Any

async def publish_event(event_type: Any, data: dict, **scope):
    """Helper function to publish an event asynchronously."""
    if event_type == "fault_detected":
        await broadcaster.fault_detected(data, **scope)
    elif event_type == "ticket_updated":
        await broadcaster.ticket_updated(data, **scope)
    elif event_type == "override_executed":
        await broadcaster.override_executed(data, **scope)
    else:
        await broadcaster.publish(Event(event_type, data, **scope))


@router.get("/events/stream")
async def event_stream(
    request: Request,
    last_event_id: str | None = Query(None, alias="last_event_id"),
):
    """SSE Endpoint for real-time operator alerts.

    Integrates cross-pod Redis fan-out with 15s keep-alive heartbeats,
    bounded client queues, and Last-Event-ID stream replay for reconnecting clients.
    """
    header_last_id = request.headers.get("last-event-id") or last_event_id

    async def generate():
        # 1. Replay missed events from Redis Stream if Last-Event-ID is provided
        if header_last_id and broadcaster._redis:
            try:
                entries = await broadcaster._redis.xread(
                    {STREAM_KEY: header_last_id}, count=50, block=500
                )
                if entries:
                    for stream_name, msgs in entries:
                        for msg_id, fields in msgs:
                            if "e" in fields:
                                event = broadcaster.Event.from_json(fields["e"])
                                yield event.sse()
            except Exception as e:
                logger.warning(f"Replay stream read error for Last-Event-ID {header_last_id}: {e}")

        # 2. Seamlessly transition into live subscription stream
        async with broadcaster.subscribe() as sub:
            try:
                while True:
                    if await request.is_disconnected():
                        break

                    try:
                        event = await asyncio.wait_for(sub.queue.get(), timeout=15.0)
                        yield event.sse()
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
            except Exception as e:
                logger.warning(f"SSE stream error: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")
