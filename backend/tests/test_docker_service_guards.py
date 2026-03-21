"""Unit tests for DockerService safety guards and compose resolution helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.docker_service import DockerService


def _mock_container(labels: dict[str, str], status: str = "running") -> MagicMock:
    c = MagicMock()
    c.status = status
    c.attrs = {"Config": {"Labels": labels}}
    c.id = "abcdef123456"
    return c


def test_remove_network_rejects_protected_network() -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        client = MagicMock()
        network = MagicMock()
        network.name = "bridge"
        network.attrs = {"Containers": {}}
        client.networks.get.return_value = network
        mock_from_env.return_value = client

        service = DockerService()

        with pytest.raises(ValueError, match="Protected docker network"):
            service.remove_network("bridge")


def test_remove_network_rejects_attached_containers() -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        client = MagicMock()
        network = MagicMock()
        network.name = "custom_net"
        network.attrs = {"Containers": {"id1": {}, "id2": {}}}
        client.networks.get.return_value = network
        mock_from_env.return_value = client

        service = DockerService()

        with pytest.raises(ValueError, match="attached containers"):
            service.remove_network("custom_net")


def test_remove_volume_rejects_in_use_volume() -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        client = MagicMock()
        volume = MagicMock()
        volume.attrs = {"UsageData": {"RefCount": 1}}
        client.volumes.get.return_value = volume
        mock_from_env.return_value = client

        service = DockerService()

        with pytest.raises(ValueError, match="Volume is in use"):
            service.remove_volume("db_data")


def test_resolve_compose_file_fallback_prod_name(tmp_path: Path) -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        service = DockerService()

    working_dir = tmp_path
    compose_prod = working_dir / "docker-compose.prod.yml"
    compose_prod.write_text("services:\n", encoding="utf-8")

    container = _mock_container({"com.docker.compose.project.working_dir": str(working_dir)})
    resolved = service._resolve_compose_file(container)
    assert resolved == compose_prod
