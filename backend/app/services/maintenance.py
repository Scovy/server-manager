"""Coordinate application writes with restore in the shipped single-worker server."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MaintenanceBusy(RuntimeError):
    pass


class MaintenanceGate:
    # All counters are accessed on the ASGI event loop, before any await.
    def __init__(self) -> None:
        self.active = 0
        self.restoring = False

    @contextmanager
    def operation(self) -> Iterator[None]:
        if self.restoring:
            raise MaintenanceBusy("A restore is in progress")
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1

    @contextmanager
    def restore(self) -> Iterator[None]:
        if self.active or self.restoring:
            raise MaintenanceBusy("Another operation is active. Close terminals and retry.")
        self.restoring = True
        try:
            yield
        finally:
            self.restoring = False


gate = MaintenanceGate()


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind, path = scope["type"], scope.get("path", "")
        if kind not in ("http", "websocket") or path == "/api/backup/import":
            await self.app(scope, receive, send)
            return
        # Read-only continuous streams can stay connected during maintenance.
        if path == "/ws/metrics" or (scope.get("method") == "GET" and path.endswith("/logs")):
            await self.app(scope, receive, send)
            return
        try:
            with gate.operation():
                await self.app(scope, receive, send)
        except MaintenanceBusy as exc:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse({"detail": str(exc)}, status_code=503)(scope, receive, send)
