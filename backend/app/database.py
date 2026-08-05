"""Database engine and session management using SQLAlchemy async."""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

from typing import AsyncGenerator, Any

is_sqlite = settings.database_url.startswith("sqlite")
engine_kwargs: dict[str, Any] = {"echo": False}
if is_sqlite:
    engine_kwargs.update({"connect_args": {"check_same_thread": False}})
else:
    engine_kwargs.update({"pool_size": 20, "max_overflow": 10, "pool_pre_ping": True})

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a database session."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables from ORM metadata."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose of the engine connection pool."""
    await engine.dispose()
