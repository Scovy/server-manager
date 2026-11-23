"""Access boundaries shared by the management HTTP and WebSocket routers."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.models.user import User
from app.services.auth_service import issue_tokens


@pytest.mark.parametrize("path", [
    "/api/containers", "/api/containers/test/logs", "/api/backup/list", "/api/volumes",
    "/api/marketplace", "/api/domains", "/api/metrics/history", "/api/metrics/alerts",
])
async def test_management_http_requires_admin(client, async_db, path):
    assert (await client.get(path)).status_code == 401
    viewer = User(username="reader", password="unused", role="viewer")
    async_db.add(viewer)
    await async_db.flush()
    token = issue_tokens(viewer, 0).access_token
    response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/ws/metrics", "/api/containers/test/exec"])
async def test_websocket_rejects_missing_credentials_and_viewer(client, async_db, path):
    viewer = User(username="reader", password="unused", role="viewer")
    async_db.add(viewer)
    await async_db.commit()
    tokens = issue_tokens(viewer, 0)
    offers = [[], ["homelab.v1", tokens.access_token], ["homelab.v1", tokens.refresh_token]]
    for protocols in offers:
        with pytest.raises(WebSocketDisconnect) as denied:
            with TestClient(app).websocket_connect(path, subprotocols=protocols):
                pytest.fail("Unauthorized upgrade was accepted")
        assert denied.value.code == 1008
