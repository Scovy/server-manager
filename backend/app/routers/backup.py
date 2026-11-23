"""Backup router for config-only export/import and archive management."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.database import engine, get_db
from app.services.backup_service import BackupService
from app.services.maintenance import MaintenanceBusy, gate

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
async def import_backup(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    temp_path: Path | None = None
    try:
        with gate.restore():
            await db.commit()  # release the authentication query before touching SQLite
            with NamedTemporaryFile(prefix="upload-backup-", suffix=".tar.gz", delete=False) as f:
                temp_path = Path(f.name)
                async for chunk in request.stream():
                    if chunk:
                        await run_in_threadpool(f.write, chunk)
                if f.tell() == 0:
                    raise HTTPException(status_code=400, detail="Backup payload is empty")
            await engine.dispose()
            try:
                return await run_in_threadpool(BackupService().restore_backup, temp_path)
            finally:
                await engine.dispose()
    except MaintenanceBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        _handle_service_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {exc}") from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
