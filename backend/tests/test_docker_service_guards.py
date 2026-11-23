"""Unit tests for DockerService safety guards and compose resolution helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import APIError

from app.services.docker_service import DockerService
from app.services.marketplace_service import ENV_FILE_REFERENCE


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


def test_resolve_compose_file_fallback_prod_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The test image inherits HOMELAB_DATA_MOUNT from backend/Dockerfile; this test
    # covers the native-path fallback, host-label mapping has its own test below.
    monkeypatch.delenv("HOMELAB_DATA_MOUNT", raising=False)
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

    monkeypatch.setenv("HOMELAB_DATA_MOUNT", "/app/data")
    service.client.containers.get.return_value.attrs = {
        "Mounts": [{"Source": "/opt/server-manager", "Destination": str(tmp_path), "Type": "bind"}]
    }
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


def _generated_compose(
    installation: str,
    app: str = "audp2-app",
    port: int = 41280,
    labelled: bool = True,
) -> str:
    lines: list[str] = []
    if labelled:
        lines.append(f"name: homelab-{installation}")
    lines.extend(
        [
            "services:",
            f"  {app}:",
            "    image: caddy:2-alpine",
            f"    container_name: {app}",
            "    restart: unless-stopped",
        ]
    )
    if labelled:
        lines.extend(
            [
                "    labels:",
                '      com.homelab.managed: "true"',
                f'      com.homelab.compose-project: "{app}"',
                '      com.homelab.template: "synthetic"',
                f'      com.homelab.installation: "{installation}"',
            ]
        )
    lines.extend(
        [
            "    ports:",
            f'      - "{port}:80"',
            "    environment:",
            '      SEED: "one"',
        ]
    )
    return "\n".join(lines) + "\n"


def _env_save_service(appdir: Path) -> tuple[DockerService, MagicMock]:
    """Service with a mocked container whose project dir is `appdir`."""
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        client = MagicMock()
        mock_from_env.return_value = client
        service = DockerService()
        container = _mock_container({"com.docker.compose.project.working_dir": str(appdir)})
        client.containers.get.return_value = container
        return service, container


def test_update_env_switches_pristine_generated_compose_to_raw_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOMELAB_DATA_MOUNT", raising=False)
    for labelled in (True, False):
        appdir = tmp_path / f"app-{labelled}"
        appdir.mkdir()
        (appdir / "docker-compose.yml").write_text(
            _generated_compose("a" * 32, labelled=labelled), encoding="utf-8"
        )
        (appdir / ".env").write_text("SEED=one\n", encoding="utf-8")
        service, _ = _env_save_service(appdir)

        updated = service.update_env("c", {"SEED": "two"})

        assert updated == {"SEED": "two"}
        text = (appdir / "docker-compose.yml").read_text(encoding="utf-8")
        assert ENV_FILE_REFERENCE in text
        assert "environment:" not in text
        assert (appdir / ".env").read_text(encoding="utf-8") == "SEED=two\n"
        assert not list(appdir.glob("docker-compose.yml.*"))  # no temp leftovers


def test_update_env_refuses_when_inline_and_dotenv_diverge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOMELAB_DATA_MOUNT", raising=False)
    # Hand-edited inline VALUE, keys unchanged: the switch must refuse rather
    # than silently replace the edit with .env's stale value.
    valued = tmp_path / "valued"
    valued.mkdir()
    compose_a = valued / "docker-compose.yml"
    compose_a.write_text(
        _generated_compose("b" * 32).replace('SEED: "one"', 'SEED: "hand-edited"'),
        encoding="utf-8",
    )
    (valued / ".env").write_text("SEED=one\n", encoding="utf-8")
    service, _ = _env_save_service(valued)

    with pytest.raises(ValueError, match="SEED") as excinfo:
        service.update_env("c", {"SEED": "two"})

    assert "disagree" in str(excinfo.value) and "save again" in str(excinfo.value)
    assert "hand-edited" in compose_a.read_text(encoding="utf-8")  # edit preserved
    assert (valued / ".env").read_text(encoding="utf-8") == "SEED=one\n"  # save refused

    # Hand-ADDED inline key missing from .env: same refusal, key named.
    keyed = tmp_path / "keyed"
    keyed.mkdir()
    compose_b = keyed / "docker-compose.yml"
    compose_b.write_text(
        _generated_compose("c" * 32).replace(
            '      SEED: "one"', '      SEED: "one"\n      ADMIN_EMAIL: "ops@example.test"'
        ),
        encoding="utf-8",
    )
    (keyed / ".env").write_text("SEED=one\n", encoding="utf-8")
    service, _ = _env_save_service(keyed)

    with pytest.raises(ValueError, match="ADMIN_EMAIL"):
        service.update_env("c", {"SEED": "two"})
    assert compose_b.read_text(encoding="utf-8").endswith('ADMIN_EMAIL: "ops@example.test"\n')
    assert (keyed / ".env").read_text(encoding="utf-8") == "SEED=one\n"


def test_update_env_leaves_custom_and_already_switched_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOMELAB_DATA_MOUNT", raising=False)
    manual = tmp_path / "manual"
    manual.mkdir()
    manual_compose = manual / "docker-compose.yml"
    manual_compose.write_text(
        "# tuned by admin\nservices:\n  audp2-app:\n    image: caddy:2-alpine\n",
        encoding="utf-8",
    )
    (manual / ".env").write_text("SEED=one\n", encoding="utf-8")

    switched = tmp_path / "switched"
    switched.mkdir()
    switched_compose = switched / "docker-compose.yml"
    switched_compose.write_text(
        _generated_compose("d" * 32).replace(
            '    environment:\n      SEED: "one"\n', ENV_FILE_REFERENCE + "\n"
        ),
        encoding="utf-8",
    )
    (switched / ".env").write_text("SEED=one\n", encoding="utf-8")

    for appdir, compose in ((manual, manual_compose), (switched, switched_compose)):
        before = compose.read_bytes()
        service, _ = _env_save_service(appdir)
        assert service.update_env("c", {"SEED": "two"}) == {"SEED": "two"}
        assert compose.read_bytes() == before
        assert (appdir / ".env").read_text(encoding="utf-8") == "SEED=two\n"


def test_update_env_compose_switch_is_atomic_and_collision_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOMELAB_DATA_MOUNT", raising=False)
    appdir = tmp_path / "app"
    appdir.mkdir()
    compose = appdir / "docker-compose.yml"
    original = _generated_compose("e" * 32)
    compose.write_text(original, encoding="utf-8")
    (appdir / ".env").write_text("SEED=one\n", encoding="utf-8")

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.services.docker_service.os.replace", broken_replace)
    service, _ = _env_save_service(appdir)

    with pytest.raises(ValueError, match="Failed to write compose file"):
        service.update_env("c", {"SEED": "two"})

    assert compose.read_text(encoding="utf-8") == original
    assert not list(appdir.glob("docker-compose.yml.*"))  # unique temp cleaned up


def _legacy_apply_service() -> tuple[DockerService, MagicMock]:
    with patch("app.services.docker_service.docker.from_env") as mock_from_env:
        client = MagicMock()
        mock_from_env.return_value = client
        service = DockerService()
        return service, client


def _legacy_container() -> MagicMock:
    container = _mock_container({"com.homelab.managed": "true"})
    container.name = "audp2-app"
    container.short_id = "abc123def"
    return container


def test_apply_legacy_compose_keeps_uncertain_replacement_and_restores_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, client = _legacy_apply_service()
    # Name that only real Compose parsing can resolve (quoted/commented forms).
    identity = {"name": "audp2-quoted", "services": {"audp2-app": {}}}
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> dict[str, str]:
        calls.append(command)
        if "config" in command:
            return {"status": "ok", "output": json.dumps(identity)}
        raise ValueError("Apply failed: port busy")

    monkeypatch.setattr(service, "_run_compose", fake_run)
    container = _legacy_container()
    squatter = MagicMock()
    squatter.attrs = {
        "Config": {
            "Labels": {
                "com.docker.compose.project": "somebody-else",
                "com.docker.compose.service": "audp2-app",
            }
        }
    }
    client.containers.get.return_value = squatter

    with pytest.raises(ValueError, match="port busy") as excinfo:
        service._apply_legacy_compose(container, ["docker", "compose"])

    squatter.remove.assert_not_called()
    container.rename.assert_any_call("audp2-app")
    container.start.assert_called_once()
    container.remove.assert_not_called()
    up_call = next(command for command in calls if "up" in command)
    assert up_call[up_call.index("--project-name") + 1] == "audp2-quoted"
    assert "available as 'audp2-app'" in str(excinfo.value)


def test_apply_legacy_compose_removes_only_its_own_failed_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, client = _legacy_apply_service()
    identity = {"name": "audp2-quoted", "services": {"audp2-app": {}}}

    def fake_run(command: list[str]) -> dict[str, str]:
        if "config" in command:
            return {"status": "ok", "output": json.dumps(identity)}
        raise ValueError("Apply failed: port busy")

    monkeypatch.setattr(service, "_run_compose", fake_run)
    container = _legacy_container()
    replacement = MagicMock()
    replacement.attrs = {
        "Config": {
            "Labels": {
                "com.docker.compose.project": "audp2-quoted",
                "com.docker.compose.service": "audp2-app",
            }
        }
    }
    client.containers.get.return_value = replacement

    with pytest.raises(ValueError, match="port busy") as excinfo:
        service._apply_legacy_compose(container, ["docker", "compose"])

    replacement.remove.assert_called_once_with(force=True)
    container.rename.assert_any_call("audp2-app")
    container.start.assert_called_once()
    container.remove.assert_not_called()
    assert "available as 'audp2-app'" in str(excinfo.value)


def test_apply_legacy_compose_name_collision_keeps_foreign_container_and_backup_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, client = _legacy_apply_service()
    identity = {"name": "audp2-quoted", "services": {"audp2-app": {}}}

    def fake_run(command: list[str]) -> dict[str, str]:
        if "config" in command:
            return {"status": "ok", "output": json.dumps(identity)}
        raise ValueError("Apply failed: up exploded")

    monkeypatch.setattr(service, "_run_compose", fake_run)
    container = _legacy_container()
    backup = "audp2-app-before-compose-abc123def"
    container.rename.side_effect = [None, APIError("409 name already in use")]
    foreign = MagicMock()
    foreign.attrs = {"Config": {"Labels": {"com.docker.compose.project": "somebody-else"}}}
    client.containers.get.return_value = foreign

    with pytest.raises(ValueError, match="up exploded") as excinfo:
        service._apply_legacy_compose(container, ["docker", "compose"])

    foreign.remove.assert_not_called()  # a name squatter is never removed
    container.start.assert_called_once()  # the old container must keep serving
    container.remove.assert_not_called()
    assert f"available as '{backup}'" in str(excinfo.value)  # recovery name is explicit
