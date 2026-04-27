"""Unit tests for backup service volume copy fallbacks."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.backup_service import BackupService


def test_stage_volumes_uses_helper_when_mountpoint_unavailable(tmp_path: Path) -> None:
    service = BackupService()
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)

    checksums: dict[str, str] = {}
    volume = SimpleNamespace(
        name="server-manager_backend_data",
        attrs={
            "Mountpoint": "/definitely/missing/path",
            "Driver": "local",
            "Labels": {"managed": "true"},
        },
    )
    client = MagicMock()
    client.volumes.list.return_value = [volume]

    def fake_copy(
        _client: MagicMock,
        _helper_image: str,
        _volume_name: str,
        destination: Path,
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "db.sqlite").write_text("backup", encoding="utf-8")

    with patch("app.services.backup_service.docker.from_env", return_value=client):
        with (
            patch.object(
                service,
                "_resolve_volume_helper_image",
                return_value="helper-image",
            ) as mock_img,
            patch.object(
                service,
                "_copy_volume_with_helper",
                side_effect=fake_copy,
            ) as mock_copy,
        ):
            payload = service._stage_volumes(stage_root, checksums)

    assert payload == {
        "items": [
            {
                "name": "server-manager_backend_data",
                "driver": "local",
                "labels": {"managed": "true"},
                "archive_path": "volumes/server-manager_backend_data",
            }
        ]
    }
    assert "volumes/server-manager_backend_data/db.sqlite" in checksums
    mock_img.assert_called_once_with(client)
    mock_copy.assert_called_once_with(
        client,
        "helper-image",
        "server-manager_backend_data",
        stage_root / "volumes" / "server-manager_backend_data",
    )
    client.close.assert_called_once()


def test_restore_volumes_uses_helper_when_mountpoint_unavailable(tmp_path: Path) -> None:
    service = BackupService()
    extract_root = tmp_path / "extract"
    source_dir = extract_root / "volumes" / "server-manager_backend_data"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "db.sqlite").write_text("restore", encoding="utf-8")

    manifest = {
        "volumes": {
            "items": [
                {
                    "name": "server-manager_backend_data",
                    "driver": "local",
                    "labels": {"managed": "true"},
                    "archive_path": "volumes/server-manager_backend_data",
                }
            ]
        }
    }

    volume = MagicMock()
    volume.attrs = {"Mountpoint": "/definitely/missing/path"}
    client = MagicMock()
    client.volumes.get.return_value = volume

    with patch("app.services.backup_service.docker.from_env", return_value=client):
        with (
            patch.object(
                service,
                "_resolve_volume_helper_image",
                return_value="helper-image",
            ) as mock_img,
            patch.object(service, "_restore_volume_with_helper") as mock_restore,
        ):
            restored = service._restore_volumes(extract_root, manifest)

    assert restored == ["server-manager_backend_data"]
    mock_img.assert_called_once_with(client)
    mock_restore.assert_called_once_with(
        client,
        "helper-image",
        "server-manager_backend_data",
        source_dir,
    )
    volume.reload.assert_called_once()
    client.close.assert_called_once()


def test_restore_marketplace_apps_runs_compose_up(tmp_path: Path) -> None:
    service = BackupService()
    database_path = tmp_path / "homelab.db"
    with sqlite3.connect(str(database_path)) as conn:
        conn.execute(
            """
            CREATE TABLE apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                app_name TEXT NOT NULL,
                host_port INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO apps(template_id, app_name, host_port)
            VALUES (?, ?, ?)
            """,
            ("gitea", "gitea-restored", 3010),
        )
        conn.commit()

    apps_root = tmp_path / "apps"
    app_dir = apps_root / "gitea-restored"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "docker-compose.yml").write_text(
        (
            "services:\n"
            "  gitea-restored:\n"
            "    image: gitea/gitea:latest\n"
            '    container_name: gitea-restored\n'
            '    ports:\n      - "3010:3000"\n'
        ),
        encoding="utf-8",
    )

    with (
        patch.object(service, "_apps_dir", return_value=apps_root),
        patch("app.services.backup_service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "started"
        mock_run.return_value.stderr = ""
        result = service._restore_marketplace_apps_from_backup_database(database_path)

    assert result == {"restored": ["gitea-restored"], "errors": []}
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    assert call_args.args[0] == [
        "docker",
        "compose",
        "-f",
        str(app_dir / "docker-compose.yml"),
        "up",
        "-d",
    ]


def test_restore_marketplace_apps_falls_back_to_sdk_without_docker_cli(tmp_path: Path) -> None:
    service = BackupService()
    database_path = tmp_path / "homelab.db"
    with sqlite3.connect(str(database_path)) as conn:
        conn.execute(
            """
            CREATE TABLE apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                app_name TEXT NOT NULL,
                host_port INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO apps(template_id, app_name, host_port)
            VALUES (?, ?, ?)
            """,
            ("gitea", "gitea-restored", 3010),
        )
        conn.commit()

    apps_root = tmp_path / "apps"
    app_dir = apps_root / "gitea-restored"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "docker-compose.yml").write_text(
        (
            "services:\n"
            "  gitea-restored:\n"
            "    image: gitea/gitea:latest\n"
            '    container_name: gitea-restored\n'
            '    ports:\n      - "3010:3000"\n'
            '    volumes:\n      - "gitea-data:/data"\n'
        ),
        encoding="utf-8",
    )
    (app_dir / ".env").write_text("USER_UID=1001\nUSER_GID=1001\n", encoding="utf-8")

    with (
        patch.object(service, "_apps_dir", return_value=apps_root),
        patch(
            "app.services.backup_service.subprocess.run",
            side_effect=OSError(2, "No such file or directory"),
        ),
        patch("app.services.backup_service._deploy_with_docker_sdk") as mock_sdk,
    ):
        result = service._restore_marketplace_apps_from_backup_database(database_path)

    assert result == {"restored": ["gitea-restored"], "errors": []}
    mock_sdk.assert_called_once()
    call_kwargs = mock_sdk.call_args.kwargs
    assert call_kwargs["app_name"] == "gitea-restored"
    assert call_kwargs["host_port"] == 3010
    assert call_kwargs["env"] == {"USER_UID": "1001", "USER_GID": "1001"}
    assert call_kwargs["volumes"] == [{"name": "gitea-data", "mount_path": "/data"}]
