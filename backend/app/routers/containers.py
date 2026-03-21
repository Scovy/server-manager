"""Container management router (Phase 3).

Provides lifecycle actions, stats, logs, and compose/env read-write endpoints.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.docker_service import DockerService, env_to_text, parse_env_payload

router = APIRouter(prefix="/api/containers", tags=["containers"])


def _handle_service_error(exc: ValueError) -> None:
    message = str(exc)
    status = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status, detail=message)


@router.get("")
def list_containers(
    all: bool = Query(True, description="Include stopped containers"),
) -> list[dict[str, Any]]:
    service = DockerService()
    try:
        return service.list_containers(all_containers=all)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
    finally:
        service.close()


@router.get("/{container_id}")
def get_container(container_id: str) -> dict[str, Any]:
    service = DockerService()
    try:
        return service.get_container(container_id)
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.post("/{container_id}/start")
def start_container(container_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.start(container_id)
        return {"status": "ok", "message": "Container started"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.post("/{container_id}/stop")
def stop_container(container_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.stop(container_id)
        return {"status": "ok", "message": "Container stopped"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.post("/{container_id}/restart")
def restart_container(container_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.restart(container_id)
        return {"status": "ok", "message": "Container restarted"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.post("/{container_id}/kill")
def kill_container(container_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        service.kill(container_id)
        return {"status": "ok", "message": "Container killed"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.delete("/{container_id}")
def remove_container(
    container_id: str,
    volumes: bool = Query(False, description="Remove attached anonymous volumes"),
) -> dict[str, str]:
    service = DockerService()
    try:
        service.remove(container_id, remove_volumes=volumes)
        return {"status": "ok", "message": "Container removed"}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.get("/{container_id}/stats")
def get_container_stats(container_id: str) -> dict[str, Any]:
    service = DockerService()
    try:
        return service.get_stats(container_id)
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.get("/{container_id}/logs")
async def stream_logs(
    container_id: str,
    tail: int = Query(200, ge=1, le=2000),
    poll_seconds: float = Query(2.0, ge=0.5, le=10.0),
) -> StreamingResponse:
    """SSE-style log stream by polling Docker logs and sending deltas."""

    async def event_stream() -> AsyncGenerator[str, None]:
        last_payload = ""
        while True:
            service = DockerService()
            try:
                payload = await asyncio.to_thread(service.tail_logs, container_id, tail)
            except ValueError as exc:
                yield f"event: error\\ndata: {json.dumps({'detail': str(exc)})}\\n\\n"
                break
            except Exception as exc:
                error_payload = {"detail": f"Docker unavailable: {exc}"}
                yield f"event: error\\ndata: {json.dumps(error_payload)}\\n\\n"
                break
            finally:
                service.close()

            if payload != last_payload:
                last_payload = payload
                yield f"data: {json.dumps({'logs': payload})}\\n\\n"

            await asyncio.sleep(poll_seconds)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{container_id}/compose")
def get_compose(container_id: str) -> dict[str, str]:
    service = DockerService()
    try:
        path, content = service.get_compose(container_id)
        return {"path": path, "content": content}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.put("/{container_id}/compose")
def update_compose(container_id: str, payload: dict[str, str]) -> dict[str, str]:
    content = payload.get("content", "")
    service = DockerService()
    try:
        path = service.update_compose(container_id, content)
        return {"status": "ok", "path": path}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.get("/{container_id}/env")
def get_env(
    container_id: str,
    format: str = Query("map", pattern="^(map|text)$"),
) -> dict[str, Any]:
    service = DockerService()
    try:
        data = service.get_env(container_id)
        if format == "text":
            return {"content": env_to_text(data)}
        return {"env": data}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()


@router.put("/{container_id}/env")
def update_env(container_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    service = DockerService()
    try:
        env_data = payload.get("env")
        if isinstance(env_data, str):
            env_data = parse_env_payload(env_data)
        if not isinstance(env_data, dict):
            raise HTTPException(status_code=400, detail="Payload must include env map or text")
        updated = service.update_env(container_id, {str(k): str(v) for k, v in env_data.items()})
        return {"status": "ok", "env": updated}
    except ValueError as exc:
        _handle_service_error(exc)
    finally:
        service.close()
