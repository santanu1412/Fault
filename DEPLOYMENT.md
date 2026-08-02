# Deployment Guide

> Docker setup, cloud deployment, and environment configuration.

## Local Development (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

### Services

| Service | Port | Purpose |
|---------|------|---------|
| `frontend` | 3000 | React operator console (nginx) |
| `backend` | 8000 | FastAPI API + workers |
| `db` | 5432 | PostgreSQL + PostGIS |

### Cold Start Behavior

On first start, the backend automatically:
1. Creates all database tables
2. Generates synthetic network data (~3,000 poles across ~100 DTs)
3. Starts the background localization worker

This may take 10-30 seconds. The health endpoint at `/api/health` will report `healthy` once ready.

### Development Without Docker

```bash
# Backend
cd backend
pip install -r requirements.txt
# Requires a running PostgreSQL instance with PostGIS
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/fault_db
uvicorn app.main:app --reload --port 8000

# Frontend  
cd frontend
npm install
npm run dev  # Vite dev server on :3000, proxies /api to :8000
```

## Environment Variables

See [.env.example](./.env.example) for all configurable variables with descriptions.

### Required Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (see .env.example) | PostgreSQL connection string |
| `POSTGRES_*` | (see .env.example) | DB credentials for docker compose |

### Optional Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | _(empty)_ | Enables AI narrative generation. System works without it. |
| `POLL_INTERVAL_SECONDS` | `3` | Localization engine polling interval |
| `SEED_*` | (see .env.example) | Synthetic data generation parameters |

## Cloud Deployment

### Render (Recommended for Demo)

Render supports Docker-based deployments with a free PostgreSQL tier.

1. **Database**: Create a PostgreSQL instance on Render. Enable PostGIS extension.

2. **Backend**: Deploy as a Docker web service:
   - Root directory: `backend/`
   - Docker command: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
   - Environment: Set `DATABASE_URL` to the Render PostgreSQL connection string (use the `Internal Database URL` and replace `postgresql://` with `postgresql+asyncpg://`)

3. **Frontend**: Deploy as a static site:
   - Build command: `npm install && npm run build`
   - Publish directory: `dist/`
   - Environment: Set `VITE_API_URL` to the backend's public URL

4. **CORS**: The backend allows all origins by default. Restrict in production.

### Fly.io

1. Add a `fly.toml` for each service (backend and frontend)
2. Create a Fly PostgreSQL cluster: `fly postgres create`
3. Deploy: `fly deploy`

### Key Considerations

- **PostGIS**: The database MUST support PostGIS. Most managed PostgreSQL services offer this as an extension.
- **Cold Start**: Free-tier services may spin down. The first request after a cold start takes 10-30s for seeding.
- **WebSocket Alternative**: The system uses HTTP polling (2-3s), which works reliably on all hosting platforms including free tiers with proxy timeouts.
- **AI Features**: The `ANTHROPIC_API_KEY` is optional. Without it, the system generates template-based narratives instead of AI-powered ones.
