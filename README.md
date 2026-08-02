# KSPDB Fault Localization System

Real-time fault detection and localization for radial low-tension (LT) power distribution networks. Ingests pole-level IoT telemetry, deterministically localizes faults to specific spans using tree-walk algorithms, and manages incident tickets through a telemetry-verified lifecycle.

> **⚡ One-command startup**: `docker compose up --build`

## Quick Start

```bash
# Clone and start
git clone <repo-url>
cd Fault
cp .env.example .env
docker compose up --build

# Access
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
# Health:   http://localhost:8000/api/health
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for system design, data flow, and algorithm details.

## Key Features

- **Fault Localization**: Deterministic tree-walk algorithm identifies the live/dark boundary down to a specific span
- **Topology Inference**: Handles 60% of DTs with unknown topology via geographic MST inference
- **False Positive Suppression**: Dead sensors, scheduled outages, and single-pole anomalies are filtered automatically
- **Ticket Lifecycle**: `detected → acknowledged → crew_assigned → resolved → verified → closed` with telemetry-verified closure
- **Operator Console**: Dark-themed ops console with map view, incident list, and confidence indicators
- **Fault Simulator**: Built-in scenarios to demonstrate the full pipeline end-to-end
- **AI Narrative**: Optional Claude-powered dispatch briefs with template fallback

## Documentation

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System design, data flow, algorithm deep-dive |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Docker setup, cloud deploy, environment variables |
| [DECISIONS.md](./DECISIONS.md) | Every design trade-off with rationale |
| [AI-WORKFLOW.md](./AI-WORKFLOW.md) | AI/LLM usage, prompts, guardrails |

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL + PostGIS
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, MapLibre GL
- **AI**: Anthropic Claude API (optional, with template fallback)
- **Infrastructure**: Docker Compose, nginx

## What I Cut

Per the assignment brief guidelines ("if you find yourself at 40 hours, stop, ship what you have, and write down what you cut"):

1. **Complex Graph / Looped Network Support**: Constrained scope to strict radial tree topologies (no loops). Looped networks require graph-cut or power flow solvers.
2. **Machine-Learned Confidence Calibration**: Used a transparent 4-factor expert heuristic for confidence scoring rather than training a model on historical discovery logs.
3. **Live Geocoding API Integration**: Baked PIN code geographic maps directly into synthetic seeding data to avoid runtime external API dependency failures during evaluation.

## License

MIT
