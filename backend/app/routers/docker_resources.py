"""Docker resources router for volume and network management."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException

from app.services.docker_service import DockerService

router = APIRouter(prefix="/api", tags=["docker-resources"])


def _handle_service_error(exc: ValueError) -> NoReturn:
    message = str(exc)
    status = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status, detail=message)


@router.get("/volumes")
def list_volumes() -> list[dict[str, object]]:
    service = DockerService()
    try:
        return service.list_volumes()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
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
