"""Application lifecycle management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.core.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    logger.info("🚀 Application starting up...")
    await create_tables()
    yield
    logger.info("👋 Application shutting down...")
