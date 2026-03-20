"""Tests for the health check endpoint."""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    """Health endpoint should return 200 even if Docker is unavailable."""
    with patch("app.routers.health.docker") as mock_docker:
        # Mock Docker client to simulate Docker being available
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.ping.return_value = True

        response = await client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data
    assert "components" in data
    assert data["components"]["backend"] == "ok"
    assert data["components"]["database"] == "ok"


@pytest.mark.asyncio
async def test_health_components_structure(client: AsyncClient):
    """Health response should contain all expected component keys."""
    with patch("app.routers.health.docker") as mock_docker:
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.ping.return_value = True

        response = await client.get("/api/health")

    data = response.json()
    assert "backend" in data["components"]
    assert "database" in data["components"]
    assert "docker" in data["components"]


@pytest.mark.asyncio
async def test_health_docker_unavailable(client: AsyncClient):
    """Health should report degraded status when Docker is unreachable."""
    with patch("app.routers.health.docker") as mock_docker:
        mock_docker.from_env.side_effect = Exception("Docker not available")

        response = await client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["backend"] == "ok"
    assert data["components"]["database"] == "ok"
    assert "error" in data["components"]["docker"]


@pytest.mark.asyncio
async def test_health_version_matches_config(client: AsyncClient):
    """Health endpoint should return the version from config."""
    with patch("app.routers.health.docker") as mock_docker:
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.ping.return_value = True

        response = await client.get("/api/health")

    data = response.json()
    assert data["version"] == "0.1.0"
