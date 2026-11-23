"""FastAPI application entrypoint.

This module creates the FastAPI app instance, configures middleware,
and includes all routers. Database migrations run automatically on startup,
and the background metrics scheduler is started during lifespan.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import async_session
from app.dependencies.auth import require_admin_user, require_websocket_admin
from app.routers import (
    auth,
    backup,
    containers,
    docker_resources,
    domains,
    health,
    marketplace,
    metrics,
    setup,
)
from app.services.maintenance import MaintenanceMiddleware
from app.services.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    On startup:
    - Runs Alembic migrations to ensure the database schema is current.
    - Starts the APScheduler background job that records metrics every 60 s
      and prunes history older than 7 days.

    On shutdown:
    - Stops the scheduler gracefully.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    # Start background metrics scheduler
    scheduler: AsyncIOScheduler = start_scheduler(async_session)

    yield  # Application runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    stop_scheduler(scheduler)
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
app.add_middleware(MaintenanceMiddleware)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(setup.router)

management = APIRouter(dependencies=[Depends(require_admin_user)])
management.include_router(backup.router)
management.include_router(metrics.router)
management.include_router(containers.router)
management.include_router(docker_resources.router)
management.include_router(marketplace.router)
management.include_router(domains.router)
app.include_router(management)

streams = APIRouter(dependencies=[Depends(require_websocket_admin)])
streams.include_router(metrics.streams)
streams.include_router(containers.streams)
app.include_router(streams)
