"""Health check endpoint for monitoring service status."""

from typing import Any

import docker
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return the health status of all system components.

    Checks:
    - **backend**: Always OK if this endpoint responds.
    - **database**: Executes a simple query against SQLite.
    - **docker**: Attempts to ping the Docker Engine via socket.

    Returns:
        JSON with status of each component and the app version.

    Example response:
    ```json
    {
        "status": "ok",
        "version": "0.1.0",
        "components": {
            "backend": "ok",
            "database": "ok",
            "docker": "ok"
        }
    }
    ```
    """
    components: dict[str, str] = {"backend": "ok"}

    # Check database connectivity
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as e:
        components["database"] = f"error: {e}"

    # Check Docker Engine connectivity
    try:
        client = docker.from_env()
        client.ping()
        components["docker"] = "ok"
        client.close()
    except Exception as e:
        components["docker"] = f"error: {e}"

    # Overall status is "degraded" if any component is not OK
    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"

    return {
        "status": overall,
        "version": settings.VERSION,
        "components": components,
    }
