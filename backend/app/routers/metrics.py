"""Metrics router — WebSocket stream, historical data, and alert configuration.

Endpoints:
    GET  /ws/metrics              WebSocket broadcasting live MetricsSnapshot every 2 s
    GET  /api/metrics/history     Historical data with optional time-range and interval filters
    GET  /api/metrics/alerts      Current alert threshold configuration
    PUT  /api/metrics/alerts      Update alert thresholds and optional webhook URL
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.metrics_history import MetricsHistory
from app.models.setting import Setting
from app.services.metrics_service import MetricsSnapshot, metrics_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

# Seconds between WebSocket metric pushes
WS_INTERVAL = 2.0

# Settings key for alert configuration
ALERT_CONFIG_KEY = "alert_config"

# Default alert thresholds and webhook
DEFAULT_ALERT_CONFIG: dict[str, Any] = {
    "cpu_threshold": 80,
    "ram_threshold": 85,
    "disk_threshold": 90,
    "webhook_url": "",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_alert_config(db: AsyncSession) -> dict[str, Any]:
    """Load alert configuration from the settings table.

    Returns the stored JSON value, or DEFAULT_ALERT_CONFIG if not yet set.

    Args:
        db: Async database session.

    Returns:
        Alert configuration dictionary.
    """
    row = await db.execute(select(Setting).where(Setting.key == ALERT_CONFIG_KEY))
    setting = row.scalar_one_or_none()
    if setting is None or not setting.value:
        return DEFAULT_ALERT_CONFIG.copy()
    try:
        data = json.loads(str(setting.value))
        if not isinstance(data, dict):
            return DEFAULT_ALERT_CONFIG.copy()
        return dict(data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return DEFAULT_ALERT_CONFIG.copy()


async def _maybe_send_alert(snapshot: MetricsSnapshot, config: dict[str, Any]) -> None:
    """Fire a Discord/generic webhook if any metric exceeds its threshold.

    Args:
        snapshot: Current metrics snapshot.
        config: Alert configuration (thresholds + webhook_url).
    """
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        return

    alerts: list[str] = []
    if snapshot.cpu_percent >= config.get("cpu_threshold", 80):
        alerts.append(
            f"🔴 CPU: **{snapshot.cpu_percent:.1f}%** (threshold {config['cpu_threshold']}%)"
        )
    if snapshot.ram_percent >= config.get("ram_threshold", 85):
        alerts.append(
            f"🔴 RAM: **{snapshot.ram_percent:.1f}%** (threshold {config['ram_threshold']}%)"
        )
    if snapshot.disk_percent >= config.get("disk_threshold", 90):
        alerts.append(
            f"🔴 Disk: **{snapshot.disk_percent:.1f}%** (threshold {config['disk_threshold']}%)"
        )

    if not alerts:
        return

    payload = {"content": "**⚠️ Homelab Dashboard Alert**\n" + "\n".join(alerts)}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(webhook_url, json=payload)
    except Exception as e:
        logger.warning("Failed to send alert webhook: %s", e)


# ── WebSocket /ws/metrics ──────────────────────────────────────────────────────


@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    """WebSocket endpoint that pushes live system metrics every 2 seconds.

    Sends a JSON object matching the ``MetricsSnapshot`` schema on each tick.
    Clients should reconnect with exponential backoff on disconnect.

    Message shape::

        {
          "cpu_percent": 12.4,
          "ram_percent": 48.3,
          "ram_used_mb": 7812,
          "ram_total_mb": 16192,
          "disk_percent": 55.0,
          "disk_used_gb": 110.5,
          "disk_total_gb": 200.0,
          "net_bytes_sent": 12345678,
          "net_bytes_recv": 98765432,
          "containers": [
            {"id": "abc123", "name": "nginx", "status": "running",
             "cpu_percent": 0.5, "mem_usage_mb": 64.0, "mem_limit_mb": 512.0}
          ]
        }
    """
    await websocket.accept()
    logger.info("WebSocket client connected: %s", websocket.client)

    alert_config = await _get_alert_config(db)
    alert_cooldown: dict[str, datetime] = {}  # metric → last alert time

    try:
        while True:
            snapshot = await metrics_service.get_snapshot()

            # Check alerts (max once per 5 min per metric to avoid spam)
            now = datetime.utcnow()
            should_alert = any(
                (now - alert_cooldown.get(k, datetime.min)).total_seconds() > 300
                for k in ("cpu", "ram", "disk")
            )
            if should_alert:
                await _maybe_send_alert(snapshot, alert_config)
                alert_cooldown = {k: now for k in ("cpu", "ram", "disk")}

            await websocket.send_text(snapshot.model_dump_json())
            await asyncio.sleep(WS_INTERVAL)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", websocket.client)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        await websocket.close()


# ── GET /api/metrics/history ───────────────────────────────────────────────────


@router.get("/api/metrics/history")
async def get_metrics_history(
    db: AsyncSession = Depends(get_db),
    from_ts: datetime | None = Query(None, alias="from", description="Start time (ISO 8601)"),
    to_ts: datetime | None = Query(None, alias="to", description="End time (ISO 8601)"),
    limit: int = Query(500, ge=1, le=2000, description="Maximum number of rows to return"),
) -> list[dict[str, Any]]:
    """Return stored metrics history, optionally filtered by time range.

    Rows are sampled from the ``metrics_history`` table, which is populated
    every 60 seconds by the background scheduler.

    Args:
        db: Async database session.
        from_ts: Optional start of time range.
        to_ts: Optional end of time range. Defaults to now.
        limit: Maximum rows to return (default 500, max 2000).

    Returns:
        List of metric snapshot dictionaries, ordered oldest-first.

    Example response item::

        {
          "id": 42,
          "timestamp": "2024-11-15T03:00:00",
          "cpu_percent": 14.2,
          "ram_percent": 52.1,
          "ram_used_mb": 8421,
          "disk_percent": 55.0,
          "net_bytes_sent": 123456789,
          "net_bytes_recv": 987654321
        }
    """
    stmt = select(MetricsHistory).order_by(MetricsHistory.timestamp.asc())

    if from_ts:
        stmt = stmt.where(MetricsHistory.timestamp >= from_ts)
    if to_ts:
        stmt = stmt.where(MetricsHistory.timestamp <= to_ts)

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "cpu_percent": row.cpu_percent,
            "ram_percent": row.ram_percent,
            "ram_used_mb": row.ram_used_mb,
            "disk_percent": row.disk_percent,
            "net_bytes_sent": row.net_bytes_sent,
            "net_bytes_recv": row.net_bytes_recv,
        }
        for row in rows
    ]


# ── GET /api/metrics/alerts ────────────────────────────────────────────────────


@router.get("/api/metrics/alerts")
async def get_alert_config(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return the current alert threshold configuration.

    Returns:
        JSON with cpu_threshold, ram_threshold, disk_threshold (0–100) and webhook_url.

    Example response::

        {
          "cpu_threshold": 80,
          "ram_threshold": 85,
          "disk_threshold": 90,
          "webhook_url": "https://discord.com/api/webhooks/..."
        }
    """
    return await _get_alert_config(db)


# ── PUT /api/metrics/alerts ────────────────────────────────────────────────────


@router.put("/api/metrics/alerts")
async def update_alert_config(
    config: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update alert threshold configuration.

    Validates that threshold values are in the 0–100 range, then persists
    the config to the ``settings`` table under the key ``alert_config``.

    Args:
        config: Dict with optional keys: cpu_threshold, ram_threshold,
                disk_threshold (int 0–100) and webhook_url (str).
        db: Async database session.

    Returns:
        The updated configuration.

    Raises:
        HTTPException 400: If a threshold value is out of range.
    """
    from fastapi import HTTPException

    current = await _get_alert_config(db)
    current.update(config)

    # Validate thresholds are in 0–100
    for key in ("cpu_threshold", "ram_threshold", "disk_threshold"):
        val = current.get(key)
        if val is not None and not (0 <= int(val) <= 100):
            raise HTTPException(status_code=400, detail=f"{key} must be between 0 and 100")

    serialized = json.dumps(current)

    # Upsert — update if row exists, insert otherwise
    result = await db.execute(select(Setting).where(Setting.key == ALERT_CONFIG_KEY))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = serialized
    else:
        db.add(Setting(key=ALERT_CONFIG_KEY, value=serialized))

    await db.commit()
    logger.info("Alert config updated: %s", current)
    return current
