from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings

_settings = get_settings()

# m65: pool 15 -> 50 (pool_size+max_overflow). A chat-keres a teljes futasa alatt
# (embedding + qdrant + LLM, akar 25 mp) fogja a kapcsolatot ("idle in transaction"),
# igy 15 konkurens keresnel a pool kimerult es 500-akat dobtunk (eles eset: 2026-07-18).
# Strukturalis fix (session elengedese az LLM-hivas idejere) a backlogban.
engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=30,
    pool_recycle=1800,
    connect_args={
        # m67: az m66-os ALTER SYSTEM idle_in_transaction_session_timeout párja
        # REPO-perzisztensen — minden app-kapcsolatra él, DB-konténer/volume
        # újralétrehozása után is.
        "server_settings": {"idle_in_transaction_session_timeout": "90000"},
    },
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
