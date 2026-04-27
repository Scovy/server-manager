"""Unit tests for backup service volume copy fallbacks."""

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
