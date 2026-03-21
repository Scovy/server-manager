"""Container management router (Phase 3).

Provides lifecycle actions, stats, logs, and compose/env read-write endpoints.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.services.docker_service import DockerService, env_to_text, parse_env_payload

router = APIRouter(prefix="/api/containers", tags=["containers"])


def _handle_service_error(exc: ValueError) -> NoReturn:
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
) -> StreamingResponse:
    """SSE log stream using Docker's native follow mode."""

    def stream_generator() -> Any:
        service = DockerService()
        try:
            iterator = service.stream_logs_follow(container_id, tail)
            for chunk in iterator:
                text = (
                    chunk.decode("utf-8", errors="replace")
                    if isinstance(chunk, (bytes, bytearray))
                    else str(chunk)
                )
                yield f"data: {json.dumps({'logs': text})}\\n\\n"
        except ValueError as exc:
            err = {"logs": "", "error": str(exc)}
            yield f"data: {json.dumps(err)}\\n\\n"
        except Exception as exc:
            err = {"logs": "", "error": f"Docker unavailable: {exc}"}
            yield f"data: {json.dumps(err)}\\n\\n"
        finally:
            service.close()

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.post("/{container_id}/apply")
def apply_compose_changes(container_id: str) -> dict[str, str]:
    """Apply compose/env edits by recreating compose services."""
    service = DockerService()
    try:
        return service.apply_compose(container_id)
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


@router.websocket("/{container_id}/exec")
async def ws_exec_container(
    websocket: WebSocket,
    container_id: str,
    cmd: str = Query("/bin/sh"),
) -> None:
    """Interactive WebSocket terminal attached to a container exec session."""
    await websocket.accept()
    service = DockerService()

    try:
        exec_cmd = await asyncio.to_thread(service.resolve_exec_command, container_id, cmd)
        socket = await asyncio.to_thread(
            service.open_exec_socket_with_command,
            container_id,
            exec_cmd,
        )
    except ValueError as exc:
        await websocket.send_text(f"ERROR: {exc}")
        await websocket.close(code=1011)
        service.close()
        return
    except Exception as exc:
        await websocket.send_text(f"ERROR: Docker unavailable: {exc}")
        await websocket.close(code=1011)
        service.close()
        return

    async def pipe_container_output() -> None:
        while True:
            chunk = await asyncio.to_thread(socket.recv, 4096)
            if chunk is None:
                await asyncio.sleep(0.05)
                continue
            if isinstance(chunk, (bytes, bytearray)) and len(chunk) == 0:
                await asyncio.sleep(0.05)
                continue
            text = (
                chunk.decode("utf-8", errors="replace")
                if isinstance(chunk, (bytes, bytearray))
                else str(chunk)
            )
            await websocket.send_text(text)

    output_task = asyncio.create_task(pipe_container_output())

    try:
        while True:
            data = await websocket.receive_text()
            sender = getattr(socket, "sendall", None)
            if callable(sender):
                await asyncio.to_thread(sender, data.encode("utf-8"))
            else:
                await asyncio.to_thread(socket.send, data.encode("utf-8"))
    except WebSocketDisconnect:
        pass
    finally:
        output_task.cancel()
        try:
            await output_task
        except asyncio.CancelledError:
            pass

        close_candidate = getattr(socket, "close", None)
        if callable(close_candidate):
            await asyncio.to_thread(close_candidate)
        service.close()
