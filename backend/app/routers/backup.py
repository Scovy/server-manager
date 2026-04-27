"""Backup router for config-only export/import and archive management."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.database import engine
from app.services.backup_service import BackupService

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _handle_service_error(exc: ValueError) -> NoReturn:
    message = str(exc)
    status = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status, detail=message)


@router.post("/export")
def export_backup(
    mode: str = Query("config", pattern="^(config|full)$"),
) -> FileResponse:
    service = BackupService()
    try:
        archive_path = service.create_backup(include_volumes=(mode == "full"))
        return FileResponse(
            path=archive_path,
            media_type="application/gzip",
            filename=archive_path.name,
        )
    except ValueError as exc:
        _handle_service_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {exc}") from exc


@router.get("/list")
def list_backups() -> list[dict[str, Any]]:
    service = BackupService()
    try:
        return service.list_backups()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {exc}") from exc


@router.delete("/{filename}")
def delete_backup(filename: str) -> dict[str, str]:
    service = BackupService()
    try:
        service.delete_backup(filename)
        return {"status": "ok", "message": "Backup removed"}
    except ValueError as exc:
        _handle_service_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete backup: {exc}") from exc


@router.post("/import")
async def import_backup(request: Request) -> dict[str, Any]:
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="Backup payload is empty")

    file_hint = request.headers.get("x-backup-filename", "").strip()
    safe_name = Path(file_hint).name if file_hint else "uploaded-backup.tar.gz"
    suffix = ".tar.gz" if safe_name.endswith(".tar.gz") else ".tar.gz"

    service = BackupService()
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(prefix="upload-backup-", suffix=suffix, delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)

        await engine.dispose()
        result = service.restore_backup(temp_path)
        await engine.dispose()
        return result
    except ValueError as exc:
        _handle_service_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {exc}") from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
