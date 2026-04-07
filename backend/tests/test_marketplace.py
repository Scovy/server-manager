"""Tests for marketplace catalog endpoints."""

from unittest.mock import patch

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


@pytest.mark.asyncio
async def test_marketplace_deploy_success(client: AsyncClient, tmp_path: str, monkeypatch):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )

    with patch("app.services.marketplace_service.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "deployed"
        mock_run.return_value.stderr = ""

        res = await client.post(
            "/api/marketplace/deploy",
            json={
                "template_id": "gitea",
                "app_name": "gitea-demo",
                "host_port": 3010,
                "env": {"USER_UID": "1000"},
            },
        )

    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == "gitea-demo"


@pytest.mark.asyncio
async def test_marketplace_deploy_duplicate_app_name(
    client: AsyncClient,
    tmp_path: str,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )
    (tmp_path / "gitea-demo").mkdir(parents=True)

    res = await client.post(
        "/api/marketplace/deploy",
        json={
            "template_id": "gitea",
            "app_name": "gitea-demo",
            "host_port": 3010,
            "env": {},
        },
    )

    assert res.status_code == 400
    assert "already exists" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_marketplace_deploy_port_in_use(client: AsyncClient, tmp_path: str, monkeypatch):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr("app.services.marketplace_service.is_port_available", lambda _: False)

    res = await client.post(
        "/api/marketplace/deploy",
        json={
            "template_id": "gitea",
            "app_name": "gitea-demo",
            "host_port": 3010,
            "env": {},
        },
    )

    assert res.status_code == 400
    assert "port" in res.json()["detail"].lower()
