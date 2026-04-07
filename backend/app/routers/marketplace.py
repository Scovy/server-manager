"""Marketplace router (Phase 4 scaffold).

Provides template catalog endpoints used by the frontend marketplace page.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query

from app.services.marketplace_service import (
    MarketplaceTemplate,
    get_template,
    list_templates,
)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


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


@router.get("/{template_id}")
def get_marketplace_template(template_id: str) -> MarketplaceTemplate:
    """Return template metadata for one marketplace item."""
    try:
        return get_template(template_id)
    except ValueError as exc:
        _handle_marketplace_error(exc)
