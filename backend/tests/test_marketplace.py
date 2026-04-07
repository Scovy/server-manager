"""Tests for marketplace catalog endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_marketplace_list_returns_templates(client: AsyncClient):
    res = await client.get("/api/marketplace")

    assert res.status_code == 200
    payload = res.json()
    assert len(payload) >= 1
    assert "id" in payload[0]
    assert "name" in payload[0]


@pytest.mark.asyncio
async def test_marketplace_filter_by_category(client: AsyncClient):
    res = await client.get("/api/marketplace?category=dev")

    assert res.status_code == 200
    payload = res.json()
    assert len(payload) >= 1
    assert all(item["category"] == "dev" for item in payload)


@pytest.mark.asyncio
async def test_marketplace_search_returns_matches(client: AsyncClient):
    res = await client.get("/api/marketplace?search=gitea")

    assert res.status_code == 200
    payload = res.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "gitea"


@pytest.mark.asyncio
async def test_marketplace_get_template(client: AsyncClient):
    res = await client.get("/api/marketplace/gitea")

    assert res.status_code == 200
    payload = res.json()
    assert payload["id"] == "gitea"
    assert payload["name"] == "Gitea"


@pytest.mark.asyncio
async def test_marketplace_get_missing_template(client: AsyncClient):
    res = await client.get("/api/marketplace/missing-template")

    assert res.status_code == 404
