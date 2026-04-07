"""Marketplace router (Phase 4 scaffold).

Provides template catalog endpoints used by the frontend marketplace page.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.app import App
from app.services.marketplace_service import (
    MarketplaceDeployRequest,
    MarketplaceDeployResult,
    MarketplacePreflightRequest,
    MarketplacePreflightResult,
    MarketplaceTemplate,
    deploy_template,
    get_template,
    get_container_status,
    list_templates,
    preflight_deploy,
    remove_deployed_app,
)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


class DeployTemplatePayload(BaseModel):
    template_id: str = Field(min_length=1)
    app_name: str = Field(min_length=3, max_length=41)
    host_port: int = Field(ge=1, le=65535)
    env: dict[str, str] = Field(default_factory=dict)


class PreflightPayload(BaseModel):
    template_id: str = Field(min_length=1)
    app_name: str = Field(min_length=3, max_length=41)
    host_port: int = Field(ge=1, le=65535)


def _handle_marketplace_error(exc: ValueError) -> NoReturn:
    """Map service errors to HTTP responses."""
    message = str(exc)
    status = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status, detail=message)


@router.get("")
def list_marketplace_templates(
    category: str | None = Query(None, description="Filter templates by category"),
    search: str | None = Query(None, description="Search by name, id, or description"),
) -> list[MarketplaceTemplate]:
    """Return marketplace template catalog."""
    return list_templates(category=category, search=search)


@router.post("/deploy")
async def deploy_marketplace_template(
    payload: DeployTemplatePayload,
    db: AsyncSession = Depends(get_db),
) -> MarketplaceDeployResult:
    """Deploy a marketplace template using generated docker compose files."""
    existing = await db.execute(select(App).where(App.app_name == payload.app_name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Application with this name already exists")

    request: MarketplaceDeployRequest = {
        "template_id": payload.template_id,
        "app_name": payload.app_name,
        "host_port": payload.host_port,
        "env": payload.env,
    }
    try:
        result = deploy_template(request)
        db.add(
            App(
                template_id=result["template_id"],
                app_name=result["app_name"],
                container_name=result["app_name"],
                host_port=result["host_port"],
                app_dir=result["app_dir"],
                compose_path=result["compose_path"],
                status="deployed",
            )
        )
        return result
    except ValueError as exc:
        _handle_marketplace_error(exc)


@router.post("/preflight")
async def preflight_marketplace_deploy(
    payload: PreflightPayload,
    db: AsyncSession = Depends(get_db),
) -> MarketplacePreflightResult:
    """Validate deploy inputs before executing deployment."""
    rows = await db.execute(select(App.app_name))
    existing_names = {name for name in rows.scalars().all()}
    request: MarketplacePreflightRequest = {
        "template_id": payload.template_id,
        "app_name": payload.app_name,
        "host_port": payload.host_port,
    }
    return preflight_deploy(request, existing_names)


@router.get("/installed")
async def list_installed_apps(db: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    """List apps deployed from marketplace and their runtime status."""
    rows = await db.execute(select(App).order_by(App.created_at.desc()))
    apps = rows.scalars().all()
    payload: list[dict[str, object]] = []
    for app in apps:
        payload.append(
            {
                "id": app.id,
                "template_id": app.template_id,
                "app_name": app.app_name,
                "container_name": app.container_name,
                "host_port": app.host_port,
                "app_dir": app.app_dir,
                "compose_path": app.compose_path,
                "status": get_container_status(app.container_name),
                "created_at": app.created_at.isoformat(),
                "updated_at": app.updated_at.isoformat(),
            }
        )
    return payload


@router.delete("/installed/{app_name}")
async def remove_installed_app(
    app_name: str,
    purge_files: bool = Query(False, description="Delete app directory and compose files"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a deployed app and optionally its local app files."""
    row = await db.execute(select(App).where(App.app_name == app_name))
    app = row.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="Installed app not found")

    try:
        message = remove_deployed_app(app.container_name, app.app_dir, purge_files)
    except ValueError as exc:
        _handle_marketplace_error(exc)

    await db.delete(app)
    return {"status": "ok", "message": message}


@router.get("/{template_id}")
def get_marketplace_template(template_id: str) -> MarketplaceTemplate:
    """Return template metadata for one marketplace item."""
    try:
        return get_template(template_id)
    except ValueError as exc:
        _handle_marketplace_error(exc)
