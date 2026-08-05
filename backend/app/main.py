"""KSPDB Fault Localization System — FastAPI Application Entry Point.

Handles application lifecycle (DB init, seeding, background workers),
CORS configuration, and route registration.
"""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.simulator import router as simulator_router
from app.api.telemetry import router as telemetry_router
from app.api.tickets import router as tickets_router
from app.api.topology import router as topology_router
from app.database import async_session, close_db, init_db
from app.services.redis_broadcaster import broadcaster
from app.services.scheduler import build_topology_cache, scheduler_loop
from app.services.seed import seed_if_needed
from app.services.telemetry_consumer import consumer as telemetry_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("fault_system")

# Background task references
_scheduler_task = None
_consumer_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    global _scheduler_task, _consumer_task

    logger.info("Starting KSPDB Fault Localization System...")

    # Initialize database tables
    await init_db()
    logger.info("Database tables initialized.")

    # Seed data if needed
    async with async_session() as session:
        seeded = await seed_if_needed(session)
        if seeded:
            logger.info("Database seeded with synthetic data.")

    # Build topology cache
    await build_topology_cache()

    # Only start background Redis/scheduler workers if NOT in Vercel serverless
    if not os.getenv("VERCEL"):
        await broadcaster.start()
        _consumer_task = asyncio.create_task(telemetry_consumer.start())
        _scheduler_task = asyncio.create_task(scheduler_loop())
        logger.info("Background scheduler started.")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if _consumer_task:
        await telemetry_consumer.stop()
        _consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _consumer_task

    if not os.getenv("VERCEL"):
        await broadcaster.stop()

    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    await close_db()


app = FastAPI(
    title="KSPDB Fault Localization System",
    description=(
        "Real-time fault detection and localization for radial LT power distribution networks. "
        "Ingests pole-level telemetry, localizes faults to specific spans using deterministic "
        "tree-walk algorithms, and manages tickets through a telemetry-verified lifecycle."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for the demo (no auth requirement)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all route modules
app.include_router(health_router, prefix="/api")
app.include_router(telemetry_router, prefix="/api")
app.include_router(incidents_router, prefix="/api")
app.include_router(tickets_router, prefix="/api")
app.include_router(simulator_router, prefix="/api")
app.include_router(topology_router, prefix="/api")
app.include_router(events_router, prefix="/api")

# Register non-prefixed health & root fallback routes for direct Vercel serverless calls
app.include_router(health_router)


@app.get("/")
@app.get("/api")
@app.get("/api/")
async def root():
    return {
        "status": "healthy",
        "name": "KSPDB Fault Localization System",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
    }

