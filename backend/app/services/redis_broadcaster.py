"""Cross-process Redis event bus for multi-pod SSE fan-out.

Replaces single-process in-memory pub/sub with Redis Pub/Sub + Redis Streams replay buffer.
Every worker pod publishes to Redis; every pod subscribes once and fans out to local clients.

Durability model:
  - Redis Pub/Sub  -> low-latency live delivery (fire and forget)
  - Redis Stream   -> capped replay buffer for SSE Last-Event-ID reconnects
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Any

try:
    import redis.asyncio as redis
    from redis.asyncio.client import PubSub
    RedisType = redis.Redis
    PubSubType = PubSub
except ImportError:
    redis = None  # type: ignore
    PubSub = None  # type: ignore
    RedisType = Any
    PubSubType = Any

log = logging.getLogger("fault_system.redis_broadcaster")

EventType = Literal[
    "fault_detected",
    "ticket_updated",
    "override_executed",
    "heartbeat",
]

CHANNEL_PREFIX = "grid:events"
STREAM_KEY = "grid:events:stream"
STREAM_MAXLEN = 20_000           # ~ minutes of replay at peak
CLIENT_QUEUE_MAXSIZE = 500       # per-operator backlog before dropping
HEARTBEAT_SECONDS = 15           # keeps LBs / proxies from killing idle SSE


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict
    tenant_id: str | None = None
    feeder_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "type": self.type,
                "ts": self.ts,
                "tenant_id": self.tenant_id,
                "feeder_id": self.feeder_id,
                "payload": self.payload,
            },
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Event:
        d = json.loads(raw)
        return cls(
            id=d["id"],
            type=d["type"],
            ts=d["ts"],
            tenant_id=d.get("tenant_id"),
            feeder_id=d.get("feeder_id"),
            payload=d.get("payload") or {},
        )

    def channels(self) -> list[str]:
        """Channels this event should be published to."""
        chans = [f"{CHANNEL_PREFIX}:all"]
        if self.tenant_id:
            chans.append(f"{CHANNEL_PREFIX}:tenant:{self.tenant_id}")
        if self.feeder_id:
            chans.append(f"{CHANNEL_PREFIX}:feeder:{self.feeder_id}")
        return chans

    def sse(self) -> str:
        """Serialize as an SSE frame with id: tag for Last-Event-ID replay."""
        return f"id: {self.id}\nevent: {self.type}\ndata: {self.to_json()}\n\n"


@dataclass(slots=True, eq=False)
class Subscriber:
    queue: asyncio.Queue[Event]
    tenant_id: str | None
    feeder_ids: frozenset[str] | None
    dropped: int = 0

    def matches(self, event: Event) -> bool:
        if self.tenant_id and event.tenant_id and event.tenant_id != self.tenant_id:
            return False
        if self.feeder_ids is not None and event.feeder_id is not None:
            return event.feeder_id in self.feeder_ids
        return True

    def offer(self, event: Event) -> None:
        """Non-blocking put. Drop oldest on overflow so one slow client
        never stalls the shared listener task."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.dropped += 1
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(event)


class RedisBroadcaster:
    """One instance per worker process."""

    def __init__(self, url: str | None = None, *, local_only: bool = False):
        self._url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._local_only = local_only
        self._redis: RedisType | None = None
        self._pubsub: PubSubType | None = None
        self._listener: asyncio.Task | None = None
        self._heartbeat: asyncio.Task | None = None
        self._subs: set[Subscriber] = set()
        self._degraded = False          # True when Redis is unreachable
        self.stats = {"published": 0, "received": 0, "dropped": 0, "reconnects": 0}

    async def start(self) -> None:
        if self._local_only:
            log.warning("RedisBroadcaster running in LOCAL-ONLY mode (dev)")
            return
        try:
            assert self._url is not None
            self._redis = redis.from_url(
                self._url,
                decode_responses=True,
                health_check_interval=10,
                socket_keepalive=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()
            self._listener = asyncio.create_task(self._listen_forever(), name="sse-listener")
            self._heartbeat = asyncio.create_task(self._heartbeat_loop(), name="sse-heartbeat")
            log.info("RedisBroadcaster connected and active.")
        except Exception as e:
            log.warning(f"Redis unavailable ({e}); falling back to local-only SSE fanout.")
            self._degraded = True

    async def stop(self) -> None:
        for task in (self._listener, self._heartbeat):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._pubsub:
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()
        if self._redis:
            with contextlib.suppress(Exception):
                await self._redis.aclose()

    async def publish(self, event: Event) -> None:
        """Fan out to every pod. Safe to call from request handlers."""
        self.stats["published"] += 1

        if self._local_only or self._degraded or self._redis is None:
            self._fanout_local(event)   # degraded: at least serve this pod
            return

        raw = event.to_json()
        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.xadd(STREAM_KEY, {"e": raw}, maxlen=STREAM_MAXLEN, approximate=True)
            for chan in event.channels():
                pipe.publish(chan, raw)
            await pipe.execute()
        except Exception:
            log.exception("publish failed; degrading to local fan-out")
            self._degraded = True
            self._fanout_local(event)

    async def fault_detected(self, payload: dict, **scope) -> None:
        await self.publish(Event("fault_detected", payload, **scope))

    async def ticket_updated(self, payload: dict, **scope) -> None:
        await self.publish(Event("ticket_updated", payload, **scope))

    async def override_executed(self, payload: dict, **scope) -> None:
        await self.publish(Event("override_executed", payload, **scope))

    @contextlib.asynccontextmanager
    async def subscribe(
        self,
        *,
        tenant_id: str | None = None,
        feeder_ids: frozenset[str] | None = None,
    ) -> AsyncIterator[Subscriber]:
        sub = Subscriber(
            queue=asyncio.Queue(maxsize=CLIENT_QUEUE_MAXSIZE),
            tenant_id=tenant_id,
            feeder_ids=feeder_ids,
        )
        self._subs.add(sub)
        try:
            yield sub
        finally:
            self._subs.discard(sub)

    def _fanout_local(self, event: Event) -> None:
        for sub in list(self._subs):
            if sub.matches(event):
                sub.offer(event)

    async def _listen_forever(self) -> None:
        while True:
            try:
                if self._redis is None:
                    await asyncio.sleep(5)
                    continue

                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(f"{CHANNEL_PREFIX}:all")
                log.info("Subscribed to Redis channel: grid:events:all")

                async for msg in self._pubsub.listen():
                    if msg and msg.get("type") == "message":
                        self.stats["received"] += 1
                        raw_data = msg.get("data")
                        if raw_data:
                            event = Event.from_json(raw_data)
                            self._fanout_local(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats["reconnects"] += 1
                log.warning(f"Redis PubSub listener error: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                hb_event = Event("heartbeat", {})
                self._fanout_local(hb_event)
            except asyncio.CancelledError:
                break
            except Exception:
                pass


# Global singleton instance
broadcaster = RedisBroadcaster()
