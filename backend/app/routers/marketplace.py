"""Marketplace router (Phase 4 scaffold).

Provides template catalog endpoints used by the frontend marketplace page.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.marketplace_service import (
    MarketplaceDeployRequest,
    MarketplaceDeployResult,
    MarketplaceTemplate,
    deploy_template,
    get_template,
    list_templates,
)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


class DeployTemplatePayload(BaseModel):
    template_id: str = Field(min_length=1)
    app_name: str = Field(min_length=3, max_length=41)
    host_port: int = Field(ge=1, le=65535)
    env: dict[str, str] = Field(default_factory=dict)


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
def deploy_marketplace_template(payload: DeployTemplatePayload) -> MarketplaceDeployResult:
    """Deploy a marketplace template using generated docker compose files."""
    request: MarketplaceDeployRequest = {
        "template_id": payload.template_id,
        "app_name": payload.app_name,
        "host_port": payload.host_port,
        "env": payload.env,
    }
    try:
        return deploy_template(request)
    except ValueError as exc:
        _handle_marketplace_error(exc)


@router.get("/{template_id}")
def get_marketplace_template(template_id: str) -> MarketplaceTemplate:
    """Return template metadata for one marketplace item."""
    try:
        return get_template(template_id)
    except ValueError as exc:
        _handle_marketplace_error(exc)
