"""Unit tests for DockerService safety guards and compose resolution helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.docker_service import DockerService


def _mock_container(labels: dict[str, str], status: str = "running") -> MagicMock:
    c = MagicMock()
    c.status = status
    c.name = "mock-container"
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


def test_resolve_compose_file_maps_host_label_path_to_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        service = DockerService()

    compose_prod = tmp_path / "docker-compose.prod.yml"
    compose_prod.write_text("services:\n", encoding="utf-8")

    monkeypatch.setenv("SETUP_CONFIG_ROOT", str(tmp_path))
    container = _mock_container(
        {
            "com.docker.compose.project.config_files": (
                "/opt/server-manager/docker-compose.prod.yml"
            ),
            "com.docker.compose.project.working_dir": "/opt/server-manager",
        }
    )

    resolved = service._resolve_compose_file(container)
    assert resolved == compose_prod


def test_resolve_compose_file_homelab_managed_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        service = DockerService()

    apps_dir = tmp_path / "apps"
    compose = apps_dir / "jellyfin" / "docker-compose.yml"
    compose.parent.mkdir(parents=True, exist_ok=True)
    compose.write_text("services:\n", encoding="utf-8")

    monkeypatch.setattr("app.services.docker_service.settings.MARKETPLACE_APPS_DIR", str(apps_dir))
    container = _mock_container(
        {
            "com.homelab.managed": "true",
            "com.homelab.compose-project": "jellyfin",
        }
    )

    resolved = service._resolve_compose_file(container)
    assert resolved == compose


def test_resolve_env_file_homelab_managed_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        service = DockerService()

    apps_dir = tmp_path / "apps"
    env_file = apps_dir / "jellyfin" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("TZ=UTC\n", encoding="utf-8")

    monkeypatch.setattr("app.services.docker_service.settings.MARKETPLACE_APPS_DIR", str(apps_dir))
    container = _mock_container(
        {
            "com.homelab.managed": "true",
            "com.homelab.compose-project": "jellyfin",
        }
    )

    resolved = service._resolve_env_file(container)
    assert resolved == env_file
