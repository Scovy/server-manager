"""FastAPI application entrypoint.

This module creates the FastAPI app instance, configures middleware,
and includes all routers. Database migrations run automatically on startup.
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Runs Alembic migrations on startup to ensure the database schema
    is always up to date. This replaces the need for manual migration commands.
    """
    # Run migrations on startup
    logger.info("Running database migrations...")
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed.")
    except Exception as e:
        logger.warning(f"Migration warning: {e}")
        logger.info("If this is the first run, migrations may not exist yet.")

    yield  # Application runs here

    # Shutdown cleanup (if needed in the future)
    logger.info("Shutting down Homelab Dashboard...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Web-based management panel for homelab servers. "
        "Provides system monitoring, Docker container management, "
        "app marketplace, and automated SSL with reverse proxy."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS middleware — required for frontend dev server (Vite on port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# Include routers
app.include_router(health.router)
