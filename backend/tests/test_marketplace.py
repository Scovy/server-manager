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
    monkeypatch.setattr(
        "app.routers.marketplace.sync_caddy_marketplace_routes",
        lambda *_args, **_kwargs: "ok",
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
    assert payload["app_url"] == "http://127.0.0.1:3010"


@pytest.mark.asyncio
async def test_marketplace_deploy_with_named_volume_writes_compose(
    client: AsyncClient,
    tmp_path: str,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "app.routers.marketplace.sync_caddy_marketplace_routes",
        lambda *_args, **_kwargs: "ok",
    )

    with patch("app.services.marketplace_service.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "deployed"
        mock_run.return_value.stderr = ""

        res = await client.post(
            "/api/marketplace/deploy",
            json={
                "template_id": "gitea",
                "app_name": "gitea-storage-demo",
                "host_port": 3013,
                "env": {},
                "volumes": [{"name": "gitea-data", "mount_path": "/data"}],
            },
        )

    assert res.status_code == 200
    compose = (tmp_path / "gitea-storage-demo" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "volumes:" in compose
    assert '"gitea-data:/data"' in compose


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


@pytest.mark.asyncio
async def test_marketplace_deploy_falls_back_to_docker_sdk(
    client: AsyncClient,
    tmp_path: str,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "app.routers.marketplace.sync_caddy_marketplace_routes",
        lambda *_args, **_kwargs: "ok",
    )

    with patch("app.services.marketplace_service.subprocess.run") as mock_run:
        mock_run.side_effect = OSError(2, "No such file or directory")

        with patch("app.services.marketplace_service.docker.from_env") as mock_from_env:
            mock_client = mock_from_env.return_value
            mock_client.containers.get.side_effect = Exception("not found")
            mock_client.containers.run.return_value.short_id = "abc123"

            # Simulate expected NotFound behavior for get(name)
            from docker.errors import NotFound

            mock_client.containers.get.side_effect = NotFound("not found")

            res = await client.post(
                "/api/marketplace/deploy",
                json={
                    "template_id": "gitea",
                    "app_name": "sdk-fallback-demo",
                    "host_port": 3011,
                    "env": {},
                },
            )

    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "ok"
    assert "container started" in payload["output"].lower()


@pytest.mark.asyncio
async def test_marketplace_preflight_rejects_invalid_payload(
    client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr("app.services.marketplace_service.is_port_available", lambda _: False)

    res = await client.post(
        "/api/marketplace/preflight",
        json={
            "template_id": "missing-template",
            "app_name": "bad name",
            "host_port": 3010,
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["valid"] is False
    assert any("template" in err.lower() for err in payload["errors"])
    assert any("app name" in err.lower() for err in payload["errors"])
    assert any("port" in err.lower() for err in payload["errors"])


@pytest.mark.asyncio
async def test_marketplace_preflight_rejects_invalid_volume_spec(client: AsyncClient):
    res = await client.post(
        "/api/marketplace/preflight",
        json={
            "template_id": "gitea",
            "app_name": "gitea-valid",
            "host_port": 3014,
            "volumes": [{"name": "bad volume", "mount_path": "data"}],
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["valid"] is False
    assert any("volume" in err.lower() for err in payload["errors"])


@pytest.mark.asyncio
async def test_marketplace_installed_list_and_remove(
    client: AsyncClient,
    tmp_path: str,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.marketplace_service.settings.MARKETPLACE_APPS_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "app.routers.marketplace.sync_caddy_marketplace_routes",
        lambda *_args, **_kwargs: "ok",
    )
    monkeypatch.setattr("app.routers.marketplace.get_container_status", lambda _: "running")
    monkeypatch.setattr(
        "app.routers.marketplace.remove_deployed_app",
        lambda *_args, **_kwargs: "Application removed",
    )

    with patch("app.services.marketplace_service.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "deployed"
        mock_run.return_value.stderr = ""

        deploy_res = await client.post(
            "/api/marketplace/deploy",
            json={
                "template_id": "gitea",
                "app_name": "gitea-installed",
                "host_port": 3012,
                "env": {},
            },
        )

    assert deploy_res.status_code == 200

    list_res = await client.get("/api/marketplace/installed")
    assert list_res.status_code == 200
    apps = list_res.json()
    assert len(apps) == 1
    assert apps[0]["app_name"] == "gitea-installed"
    assert apps[0]["status"] == "running"
    assert apps[0]["app_url"] == "http://127.0.0.1:3012"

    remove_res = await client.delete("/api/marketplace/installed/gitea-installed")
    assert remove_res.status_code == 200

    list_after = await client.get("/api/marketplace/installed")
    assert list_after.status_code == 200
    assert list_after.json() == []
