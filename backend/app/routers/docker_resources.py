"""Docker resources router for volume and network management."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.docker_service import DockerService

router = APIRouter(prefix="/api", tags=["docker-resources"])


def _handle_service_error(exc: ValueError) -> NoReturn:
    message = str(exc)
    status = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status, detail=message)


class CreateVolumePayload(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    labels: dict[str, str] = Field(default_factory=dict)


@router.get("/volumes")
def list_volumes() -> list[dict[str, object]]:
    service = DockerService()
    try:
        return service.list_volumes()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
    finally:
        service.close()


@router.post("/volumes")
def create_volume(payload: CreateVolumePayload) -> dict[str, object]:
    service = DockerService()
    try:
        volume = service.create_volume(payload.name, payload.labels)
        return {
            "status": "ok",
            "volume": volume,
        }
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.delete("/volumes/{volume_name}")
def remove_volume(volume_name: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.remove_volume(volume_name)
        return {"status": "ok", "message": "Volume removed"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.get("/disks")
def list_disks() -> list[dict[str, object]]:
    service = DockerService()
    try:
        return service.list_disks()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Disk scan unavailable: {exc}") from exc
    finally:
        service.close()


@router.get("/networks")
def list_networks() -> list[dict[str, object]]:
    service = DockerService()
    try:
        return service.list_networks()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
    finally:
        service.close()


@router.delete("/networks/{network_id}")
def remove_network(network_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.remove_network(network_id)
        return {"status": "ok", "message": "Network removed"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()
