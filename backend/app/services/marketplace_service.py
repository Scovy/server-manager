"""Marketplace service for application template catalog operations."""

from __future__ import annotations

from typing import TypedDict


class MarketplaceTemplate(TypedDict):
    """Template metadata used by marketplace list/detail endpoints."""

    id: str
    name: str
    description: str
    category: str
    image: str
    version: str
    homepage: str
    default_port: int


_TEMPLATES: list[MarketplaceTemplate] = [
    {
        "id": "nextcloud",
        "name": "Nextcloud",
        "description": "Private cloud with files, calendar, and collaboration.",
        "category": "productivity",
        "image": "nextcloud:latest",
        "version": "latest",
        "homepage": "https://nextcloud.com",
        "default_port": 8080,
    },
    {
        "id": "gitea",
        "name": "Gitea",
        "description": "Lightweight self-hosted Git service.",
        "category": "dev",
        "image": "gitea/gitea:latest",
        "version": "latest",
        "homepage": "https://about.gitea.com",
        "default_port": 3000,
    },
    {
        "id": "vaultwarden",
        "name": "Vaultwarden",
        "description": "Bitwarden-compatible password manager server.",
        "category": "security",
        "image": "vaultwarden/server:latest",
        "version": "latest",
        "homepage": "https://github.com/dani-garcia/vaultwarden",
        "default_port": 8081,
    },
    {
        "id": "uptime-kuma",
        "name": "Uptime Kuma",
        "description": "Self-hosted monitoring and status page dashboard.",
        "category": "monitoring",
        "image": "louislam/uptime-kuma:1",
        "version": "1",
        "homepage": "https://uptime.kuma.pet",
        "default_port": 3001,
    },
    {
        "id": "jellyfin",
        "name": "Jellyfin",
        "description": "Media server for movies, shows, and music.",
        "category": "media",
        "image": "jellyfin/jellyfin:latest",
        "version": "latest",
        "homepage": "https://jellyfin.org",
        "default_port": 8096,
    },
]


def list_templates(
    category: str | None = None,
    search: str | None = None,
) -> list[MarketplaceTemplate]:
    """List templates with optional category and text filtering."""
    result = _TEMPLATES

    if category:
        lowered_category = category.strip().lower()
        result = [
            template
            for template in result
            if template["category"].lower() == lowered_category
        ]

    if search:
        needle = search.strip().lower()
        if needle:
            result = [
                template
                for template in result
                if needle in template["name"].lower()
                or needle in template["description"].lower()
                or needle in template["id"].lower()
            ]

    return sorted(result, key=lambda template: template["name"].lower())


def get_template(template_id: str) -> MarketplaceTemplate:
    """Return one template by ID.

    Raises:
        ValueError: If template ID does not exist.
    """
    lowered_id = template_id.strip().lower()
    for template in _TEMPLATES:
        if template["id"].lower() == lowered_id:
            return template
    raise ValueError("Template not found")
