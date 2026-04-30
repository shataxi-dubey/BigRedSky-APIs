"""Application lifecycle management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from .middlewares.rate_limiter import init_rate_limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    logger.info("🚀 Application starting up...")
    # await init_rate_limiter()

    from .db import engine
    async with engine.begin() as conn:
        from .db.base import Base
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created.")

    yield

    await engine.dispose()
    logger.info("👋 Application shutting down...")
