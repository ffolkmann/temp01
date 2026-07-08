"""
SQLAlchemy async engine and session management for multi-tenant Postgres connectivity.

Provides:
  - Async engine creation with connection pooling (pool_pre_ping for stale connection detection)
  - AsyncSession factory for database operations
  - get_session() dependency for FastAPI routes (yields AsyncSession instances)

Database URL is read from settings (DATABASE_URL env var).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
