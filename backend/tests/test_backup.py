"""Tests for backup router endpoints."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_backup_export_success(client: AsyncClient, tmp_path: Path):
    archive = tmp_path / "config-backup.tar.gz"
    archive.write_bytes(b"backup-bytes")

    with patch("app.routers.backup.BackupService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.create_backup.return_value = archive

        res = await client.post("/api/backup/export")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/gzip")
    service.create_backup.assert_called_once_with(include_volumes=False)


@pytest.mark.asyncio
async def test_backup_export_full_mode_success(client: AsyncClient, tmp_path: Path):
    archive = tmp_path / "full-backup.tar.gz"
    archive.write_bytes(b"backup-bytes")

    with patch("app.routers.backup.BackupService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.create_backup.return_value = archive

        res = await client.post("/api/backup/export?mode=full")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/gzip")
    service.create_backup.assert_called_once_with(include_volumes=True)


@pytest.mark.asyncio
async def test_backup_list_success(client: AsyncClient):
    with patch("app.routers.backup.BackupService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.list_backups.return_value = [
            {
                "filename": "config-backup-20260427_100000.tar.gz",
                "size_bytes": 2048,
                "updated_at": "2026-04-27T10:00:00+00:00",
            }
        ]

        res = await client.get("/api/backup/list")

    assert res.status_code == 200
    assert res.json()[0]["filename"].endswith(".tar.gz")


@pytest.mark.asyncio
async def test_backup_delete_not_found(client: AsyncClient):
    with patch("app.routers.backup.BackupService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.delete_backup.side_effect = ValueError("Backup not found")

        res = await client.delete("/api/backup/missing.tar.gz")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_backup_import_success(client: AsyncClient):
    with patch("app.routers.backup.BackupService") as mock_service_cls:
        service = mock_service_cls.return_value
        service.restore_backup.return_value = {
            "status": "ok",
            "message": "Backup restored successfully",
            "restored": {
                "database": True,
                "apps_dir": True,
                "config_files": [],
                "volumes": [],
            },
        }

        mock_engine = SimpleNamespace(dispose=AsyncMock())
        with patch("app.routers.backup.engine", new=mock_engine):
            res = await client.post(
                "/api/backup/import",
                content=b"archive-content",
                headers={
                    "content-type": "application/gzip",
                    "x-backup-filename": "config-backup.tar.gz",
                },
            )

    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_backup_import_empty_payload(client: AsyncClient):
    res = await client.post(
        "/api/backup/import",
        content=b"",
        headers={"content-type": "application/gzip"},
    )

    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()
