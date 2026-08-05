"""High-throughput Redis Streams Telemetry Consumer Service.

Implements a reliable consumer group pattern with auto-claim for stale messages,
deduplication by (device_id, sequence_number), and batch Postgres insertion.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.database import async_session
from app.services.ingest import ingest_telemetry

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # type: ignore

logger = logging.getLogger("fault_system.telemetry_consumer")

STREAM_NAME = "grid:telemetry:stream"
CONSUMER_GROUP = "telemetry_processor_group"
CONSUMER_NAME = "worker_1"
BATCH_SIZE = 2000
MIN_IDLE_TIME_MS = 10000  # 10s for claiming stale messages


@dataclass(slots=True)
class TelemetryPing:
    device_id: str
    seq: int
    event: str
    energized: bool
    payload: dict[str, Any]
    msg_id: str


class TelemetryConsumer:
    """Consumer group worker for high-throughput stream ingestion."""

    def __init__(self, redis_url: str | None = None):
        self._url = redis_url or settings.redis_url
        self._redis: redis.Redis | None = None
        self._running = False

    async def setup(self) -> None:
        """Initialize Redis connection and ensure consumer group exists."""
        if redis is None:
            logger.warning("Redis module unavailable; TelemetryConsumer running in degraded mode.")
            return

        try:
            self._redis = redis.from_url(
                self._url,
                decode_responses=True,
                socket_keepalive=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()

            try:
                await self._redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
                logger.info(f"Created Redis Consumer Group '{CONSUMER_GROUP}' for stream '{STREAM_NAME}'")
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.warning(f"Error setting up consumer group: {e}")

        except Exception as e:
            logger.warning(f"Could not connect TelemetryConsumer to Redis ({e})")
            self._redis = None

    async def start(self) -> None:
        """Start the background consumer loop."""
        await self.setup()
        if self._redis is None:
            return

        self._running = True
        logger.info("TelemetryConsumer started consuming from Redis Stream.")

        while self._running:
            try:
                # 1. Read new pending messages for this consumer group
                entries = await self._redis.xreadgroup(  # type: ignore
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_NAME: ">"},
                    count=BATCH_SIZE,
                    block=2000,
                )

                if entries:
                    for stream_name, messages in entries:  # type: ignore
                        await self.process_batch(messages)

                # 2. Periodically claim stale pending messages from crashed workers
                await self._claim_stale_messages()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TelemetryConsumer loop: {e}. Retrying in 2s...")
                await asyncio.sleep(2)

    async def stop(self) -> None:
        """Stop consumer loop and close Redis connection."""
        self._running = False
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def process_batch(self, messages: list[tuple[str, dict[str, str]]]) -> None:
        """Group, deduplicate, and persist telemetry data to Postgres."""
        if not messages:
            return

        parsed_messages: list[dict[str, Any]] = []
        msg_ids: list[str] = []

        for msg_id, data in messages:
            msg_ids.append(msg_id)
            try:
                raw_payload = data.get("payload")
                if raw_payload:
                    payload_dict = json.loads(raw_payload)
                else:
                    payload_dict = data

                device_id = payload_dict.get("device_id")
                seq = payload_dict.get("seq")

                if device_id and seq is not None:
                    parsed_messages.append({
                        "device_id": str(device_id),
                        "seq": int(seq),
                        "event": payload_dict.get("event", "heartbeat"),
                        "energized": bool(payload_dict.get("energized", True)),
                        "battery_mv": payload_dict.get("battery_mv"),
                        "rssi": payload_dict.get("rssi"),
                        "fw": payload_dict.get("fw"),
                        "ts": payload_dict.get("ts"),
                    })
            except Exception as e:
                logger.warning(f"Failed to parse stream message {msg_id}: {e}")

        # Batch ingestion into PostgreSQL via AsyncSession
        if parsed_messages:
            async with async_session() as session:
                stats = await ingest_telemetry(session, parsed_messages)
                logger.debug(f"Telemetry batch processed: {stats}")

        # Acknowledge processed messages in Redis Stream
        if msg_ids and self._redis:
            try:
                await self._redis.xack(STREAM_NAME, CONSUMER_GROUP, *msg_ids)
            except Exception as e:
                logger.warning(f"Failed to xack messages: {e}")

    async def _claim_stale_messages(self) -> None:
        """Claim and re-process pending messages that have been idle for >10 seconds."""
        if not self._redis:
            return
        try:
            claimed = await self._redis.xautoclaim(
                name=STREAM_NAME,
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                min_idle_time=MIN_IDLE_TIME_MS,
                start_id="0-0",
                count=500,
            )
            if claimed and len(claimed) > 1 and claimed[1]:
                stale_msgs = claimed[1]
                logger.info(f"Auto-claimed {len(stale_msgs)} stale telemetry messages from Redis.")
                await self.process_batch(stale_msgs)
        except Exception as e:
            logger.debug(f"XAUTOCLAIM check: {e}")


# Global singleton instance
consumer = TelemetryConsumer()
