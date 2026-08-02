import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings loaded from environment variables with sensible defaults."""

    # Database & Redis
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./fault.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    log_level: str = "info"

    # Seed configuration
    seed_substations: int = 4
    seed_feeders_per_sub: int = 3
    seed_dts_per_feeder: int = 8
    seed_poles_per_dt_min: int = 15
    seed_poles_per_dt_max: int = 60
    seed_known_topology_pct: float = 0.40
    seed_device_coverage_pct: float = 0.91
    seed_missing_pincode_pct: float = 0.03

    # Localization engine
    poll_interval_seconds: int = 3
    heartbeat_timeout_minutes: int = 16
    debounce_missed_heartbeats: int = 2
    outage_buffer_minutes: int = 15

    # AI / LLM (optional)
    anthropic_api_key: str | None = None
    ai_model: str = "claude-sonnet-4-20250514"
    ai_timeout_seconds: int = 3

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
