"""Tests for docker volume/network resource endpoints."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_volumes_success(client: AsyncClient):
    with patch("app.routers.docker_resources.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.list_volumes.return_value = [
            {
                "name": "db_data",
                "driver": "local",
                "mountpoint": "/var/lib/docker/volumes/db_data",
                "scope": "local",
                "labels": {},
            }
        ]

        res = await client.get("/api/volumes")

    assert res.status_code == 200
    assert res.json()[0]["name"] == "db_data"


@pytest.mark.asyncio
async def test_remove_volume_not_found(client: AsyncClient):
    with patch("app.routers.docker_resources.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.remove_volume.side_effect = ValueError("Volume not found")

        res = await client.delete("/api/volumes/missing")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_networks_success(client: AsyncClient):
    with patch("app.routers.docker_resources.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.list_networks.return_value = [
            {
                "id": "123456789abc",
                "name": "bridge",
                "driver": "bridge",
                "scope": "local",
                "containers": 2,
                "labels": {},
            }
        ]

        res = await client.get("/api/networks")

    assert res.status_code == 200
    assert res.json()[0]["name"] == "bridge"


@pytest.mark.asyncio
async def test_remove_network_success(client: AsyncClient):
    with patch("app.routers.docker_resources.DockerService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.remove_network.return_value = None

        res = await client.delete("/api/networks/123")

    assert res.status_code == 200
    assert res.json()["status"] == "ok"
