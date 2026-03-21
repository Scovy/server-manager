"""Tests for the Phase 3 container management router."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_containers_success(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.list_containers.return_value = [
            {
                "id": "abc123",
                "name": "nginx",
                "status": "running",
                "image": "nginx:latest",
                "created": "2026-03-21T12:00:00Z",
                "labels": {},
                "ports": {},
            }
        ]

        res = await client.get("/api/containers")

    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "nginx"


@pytest.mark.asyncio
async def test_get_container_not_found(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_container.side_effect = ValueError("Container not found")

        res = await client.get("/api/containers/missing")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_start_container_success(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.start.return_value = None

        res = await client.post("/api/containers/abc123/start")

    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_get_env_text_format(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_env.return_value = {"A": "1", "B": "2"}

        res = await client.get("/api/containers/abc123/env?format=text")

    assert res.status_code == 200
    assert "A=1" in res.json()["content"]


@pytest.mark.asyncio
async def test_update_env_from_text_payload(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.update_env.return_value = {"A": "1", "B": "2"}

        res = await client.put(
            "/api/containers/abc123/env",
            json={"env": "A=1\nB=2\n"},
        )

    assert res.status_code == 200
    assert res.json()["env"]["A"] == "1"


@pytest.mark.asyncio
async def test_get_compose_returns_file_content(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.get_compose.return_value = ("/tmp/docker-compose.yml", "services:\n  app:\n")

        res = await client.get("/api/containers/abc123/compose")

    assert res.status_code == 200
    payload = res.json()
    assert payload["path"] == "/tmp/docker-compose.yml"
    assert "services:" in payload["content"]
