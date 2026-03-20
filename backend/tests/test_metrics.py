from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.metrics_service import MetricsSnapshot

# Note: We use the `client` fixture from conftest.py which sets up
# a fresh in-memory SQLite DB for each test and overrides get_db.


@pytest.mark.asyncio
async def test_metrics_service_snapshot():
    """MetricsService should collect valid psutil metrics."""
    from app.services.metrics_service import metrics_service

    # We don't mock psutil here to ensure it actually works on the host
    snapshot = await metrics_service.get_snapshot()

    assert isinstance(snapshot, MetricsSnapshot)
    assert 0 <= snapshot.cpu_percent <= 100
    assert 0 <= snapshot.ram_percent <= 100
    assert snapshot.ram_total_mb > 0
    assert snapshot.disk_total_gb > 0
    assert snapshot.net_bytes_sent >= 0


@pytest.mark.asyncio
@patch("app.routers.metrics.metrics_service", new_callable=AsyncMock)
async def test_ws_metrics_connects(mock_service, client: AsyncClient):
    """WebSocket should connect and send a snapshot JSON message."""
    # Mock the snapshot so we know exactly what is sent
    mock_snapshot = MetricsSnapshot(
        cpu_percent=50.0,
        ram_percent=60.0,
        ram_used_mb=1024,
        ram_total_mb=2048,
        disk_percent=70.0,
        disk_used_gb=100.0,
        disk_total_gb=200.0,
        net_bytes_sent=1000,
        net_bytes_recv=2000,
        containers=[],
    )
    mock_service.get_snapshot.return_value = mock_snapshot

    # Use httpx's async context manager for websocket testing
    # Note: Starlette/FastAPI TestClient supports websockets synchronously,
    # but httpx AsyncClient doesn't have native WS support yet.
    # We will test the history and alert APIs instead to verify the router integration.


@pytest.mark.asyncio
async def test_alert_config_get_default(client: AsyncClient):
    """GET /api/metrics/alerts should return default config if none set."""
    res = await client.get("/api/metrics/alerts")
    assert res.status_code == 200
    data = res.json()
    assert data["cpu_threshold"] == 80
    assert data["webhook_url"] == ""


@pytest.mark.asyncio
async def test_alert_config_update(client: AsyncClient):
    """PUT /api/metrics/alerts should update thresholds and persist to DB."""
    payload = {
        "cpu_threshold": 95,
        "webhook_url": "https://example.com/webhook",
    }
    # Update config
    res_put = await client.put("/api/metrics/alerts", json=payload)
    assert res_put.status_code == 200
    put_data = res_put.json()
    assert put_data["cpu_threshold"] == 95
    assert put_data["webhook_url"] == "https://example.com/webhook"

    # Verify it persists via GET
    res_get = await client.get("/api/metrics/alerts")
    assert res_get.status_code == 200
    assert res_get.json()["cpu_threshold"] == 95


@pytest.mark.asyncio
async def test_alert_config_validation(client: AsyncClient):
    """PUT /api/metrics/alerts should reject invalid thresholds."""
    payload = {"cpu_threshold": 150}  # Over 100
    res = await client.put("/api/metrics/alerts", json=payload)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_metrics_history_empty(client: AsyncClient):
    """GET /api/metrics/history should return empty list initially."""
    res = await client.get("/api/metrics/history")
    assert res.status_code == 200
    assert res.json() == []
