"""Tests for the Phase 3 container management router."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app


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


@pytest.mark.asyncio
async def test_update_compose_success(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.update_compose.return_value = "/tmp/docker-compose.yml"

        res = await client.put(
            "/api/containers/abc123/compose",
            json={"content": "services:\n  app:\n"},
        )

    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_apply_changes_success(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.apply_compose.return_value = {
            "status": "ok",
            "output": "recreated",
        }

        res = await client.post("/api/containers/abc123/apply")

    assert res.status_code == 200
    assert res.json()["output"] == "recreated"


@pytest.mark.asyncio
async def test_apply_changes_failure(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.apply_compose.side_effect = ValueError("Apply failed: bad compose")

        res = await client.post("/api/containers/abc123/apply")

    assert res.status_code == 400


@pytest.mark.asyncio
async def test_logs_stream_error_event_on_missing_container(client: AsyncClient):
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.tail_logs.side_effect = ValueError("Container not found")

        res = await client.get("/api/containers/missing/logs?tail=10&poll_seconds=0.5")

    assert res.status_code == 200
    assert "data:" in res.text
    assert "Container not found" in res.text


def test_exec_websocket_returns_error_when_container_missing():
    with patch("app.routers.containers.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.resolve_exec_command.side_effect = ValueError("Container not found")

        with TestClient(app) as sync_client:
            with sync_client.websocket_connect("/api/containers/missing/exec") as ws:
                error_text = ws.receive_text()

    assert "Container not found" in error_text
