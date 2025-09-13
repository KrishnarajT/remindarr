# db.py
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession  # <- use SQLModel's AsyncSession type

from constants.constants import DATABASE_URL, DB_SCHEMA

# Create async engine and sessionmaker
engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=True, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """
    One-time DB initialization:
    - Create schema if missing
    - Create all tables from SQLModel metadata
    Call this once during app startup (lifespan).
    """
    async with engine.begin() as conn:
        # create schema if not exists
        await conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")
        # create tables in the engine's metadata context
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency. Yields an AsyncSession per request and closes it after.
    Use: session: AsyncSession = Depends(get_session)
    """
    async with async_session() as session:
        yield session
