"""First-install setup router for onboarding and initial configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.setup_service import (
    SetupPayload,
    get_setup_status,
    initialize_setup,
    run_preflight,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    acme_email: str = Field(min_length=3, max_length=254)
    enable_https: bool = True
    use_staging_acme: bool = False
    cors_origins: list[str] = Field(default_factory=list)


def _to_payload(request: SetupRequest) -> SetupPayload:
    origins = [origin.strip() for origin in request.cors_origins if origin.strip()]
    if not origins:
        origins = ["http://localhost:5173", "http://localhost:3000"]
    return SetupPayload(
        domain=request.domain,
        acme_email=request.acme_email,
        enable_https=request.enable_https,
        use_staging_acme=request.use_staging_acme,
        cors_origins=origins,
    )


@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    """Return whether the application has completed first-time setup."""
    return await get_setup_status(db)


@router.post("/preflight")
async def setup_preflight(request: SetupRequest) -> dict[str, object]:
    """Validate setup payload and host capabilities before initialization."""
    payload = _to_payload(request)
    result = run_preflight(payload)
    return {
        "valid": result.valid,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
        "checks": [check.__dict__ for check in result.checks],
    }


@router.post("/initialize")
async def setup_initialize(
    request: SetupRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Apply setup configuration, persist initialization state, and write env values."""
    payload = _to_payload(request)
    result = await initialize_setup(db, payload)
    if result["status"] != "ok":
        raise HTTPException(status_code=400, detail=result)
    return result
