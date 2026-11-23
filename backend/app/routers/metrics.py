"""Metrics router — WebSocket stream, historical data, and alert configuration.

Endpoints:
    GET  /ws/metrics              WebSocket broadcasting live MetricsSnapshot
    GET  /api/metrics/history     Historical data with optional time-range and interval filters
    GET  /api/metrics/alerts      Current alert threshold configuration
    PUT  /api/metrics/alerts      Update alert thresholds and optional webhook URL
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies.auth import WS_PROTOCOL
from app.models.metrics_history import MetricsHistory
from app.models.setting import Setting
from app.services.alerts import ALERT_CONFIG_KEY, load_alert_config
from app.services.metrics_service import (
    ContainerStat,
    ContainerSummary,
    MetricsSnapshot,
    metrics_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])
streams = APIRouter()

# Seconds between WebSocket metric pushes
WS_INTERVAL = settings.METRICS_WS_INTERVAL_SECONDS
CONTAINER_REFRESH_INTERVAL = settings.METRICS_CONTAINER_REFRESH_SECONDS

# ── WebSocket /ws/metrics ──────────────────────────────────────────────────────


@streams.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket) -> None:
    """WebSocket endpoint that pushes live system metrics on each interval tick.

    Sends a JSON object matching the ``MetricsSnapshot`` schema on each tick.
    Clients should reconnect with exponential backoff on disconnect.

    Message shape::

        {
          "timestamp": "2026-11-23T12:00:00.123456Z",
          "cpu_percent": 12.4,
          "ram_percent": 48.3,
          "ram_used_mb": 7812,
          "ram_total_mb": 16192,
          "disk_percent": 55.0,
          "disk_used_gb": 110.5,
          "disk_total_gb": 200.0,
          "disk_free_gb": 89.5,
          "disk_source": "overlay",
          "net_bytes_sent": 12345678,
          "net_bytes_recv": 98765432,
          "containers": [
            {"id": "abc123", "name": "nginx", "status": "running",
             "cpu_percent": 0.5, "mem_usage_mb": 64.0, "mem_limit_mb": 512.0}
          ],
          "container_summary": {"running": 2, "total": 5, "unhealthy": 1, "restarting": 0}
        }

    ``timestamp`` is server-side UTC ("Z") of the host sample, not the end of
    the Docker stats pass. ``container_summary`` is ``null`` until a reliable
    Docker listing has been fetched — it is never guessed.
    """
    await websocket.accept(subprotocol=WS_PROTOCOL)
    logger.info("WebSocket client connected: %s", websocket.client)

    last_containers: list[ContainerStat] = []
    last_summary: ContainerSummary | None = None
    # Time of the last COMPLETED refresh attempt (None = never attempted).
    # An empty container list / null summary is a valid state, so throttling
    # must not key off the data — only off this timestamp.
    last_container_refresh: float | None = None
    container_refresh_task: asyncio.Task[MetricsSnapshot] | None = None

    try:
        # Send host-level metrics immediately so dashboard cards render on refresh
        # without waiting for Docker container stats collection.
        initial_snapshot = await metrics_service.get_snapshot(include_containers=False)
        await websocket.send_text(initial_snapshot.model_dump_json())

        while True:
            now_monotonic = time.monotonic()

            if container_refresh_task and container_refresh_task.done():
                try:
                    container_snapshot = container_refresh_task.result()
                    last_containers = container_snapshot.containers
                    last_summary = container_snapshot.container_summary
                except Exception as e:
                    # Keep the last known stats, but never guess the summary.
                    last_summary = None
                    logger.debug("Container refresh task failed: %s", e)
                finally:
                    # Throttle from the finished ATTEMPT — success, empty list
                    # or exception — so failures don't trigger per-tick retries.
                    last_container_refresh = now_monotonic
                    container_refresh_task = None

            # First refresh fires immediately; afterwards the interval applies
            # regardless of an empty result, null summary or a failed attempt.
            if container_refresh_task is None and (
                last_container_refresh is None
                or (now_monotonic - last_container_refresh) >= CONTAINER_REFRESH_INTERVAL
            ):
                container_refresh_task = asyncio.create_task(
                    metrics_service.get_snapshot(include_containers=True)
                )

            snapshot = await metrics_service.get_snapshot(include_containers=False)
            snapshot = snapshot.model_copy(
                update={"containers": last_containers, "container_summary": last_summary}
            )

            await websocket.send_text(snapshot.model_dump_json())
            await asyncio.sleep(WS_INTERVAL)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", websocket.client)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        await websocket.close()
    finally:
        if container_refresh_task and not container_refresh_task.done():
            container_refresh_task.cancel()


# ── GET /api/metrics/history ───────────────────────────────────────────────────


def _naive_utc(value: datetime) -> datetime:
    """Normalize an (optionally offset-carrying) query param to naive UTC.

    ``metrics_history`` rows are stored as naive UTC; a param like
    ``2026-11-23T14:00:00+02:00`` must not be compared against them as-is.
    """
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _iso_utc_z(value: datetime) -> str:
    """Format a naive-UTC DB datetime as ISO 8601 with a ``Z`` suffix."""
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/api/metrics/history")
async def get_metrics_history(
    db: AsyncSession = Depends(get_db),
    from_ts: datetime | None = Query(None, alias="from", description="Start time (ISO 8601)"),
    to_ts: datetime | None = Query(None, alias="to", description="End time (ISO 8601)"),
    limit: int = Query(500, ge=1, le=2000, description="Maximum number of rows to return"),
) -> list[dict[str, Any]]:
    """Return the latest stored metrics history rows, optionally filtered by time range.

    Rows are sampled from the ``metrics_history`` table, which is populated
    every 60 seconds by the background scheduler. The newest ``limit`` rows
    (within the range) are selected first, then returned oldest-first.

    Args:
        db: Async database session.
        from_ts: Optional start of time range (may carry a UTC offset).
        to_ts: Optional end of time range (may carry a UTC offset).
        limit: Maximum rows to return (default 500, max 2000).

    Returns:
        List of metric snapshot dictionaries, ordered oldest-first, timestamps
        as ISO 8601 UTC with a ``Z`` suffix.

    Example response item::

        {
          "id": 42,
          "timestamp": "2024-11-15T03:00:00Z",
          "cpu_percent": 14.2,
          "ram_percent": 52.1,
          "ram_used_mb": 8421,
          "disk_percent": 55.0,
          "net_bytes_sent": 123456789,
          "net_bytes_recv": 987654321
        }
    """
    # Descending order + limit selects the *latest* N in the range;
    # id desc breaks ties for identical timestamps (same-second inserts).
    stmt = select(MetricsHistory).order_by(
        MetricsHistory.timestamp.desc(), MetricsHistory.id.desc()
    )

    if from_ts:
        stmt = stmt.where(MetricsHistory.timestamp >= _naive_utc(from_ts))
    if to_ts:
        stmt = stmt.where(MetricsHistory.timestamp <= _naive_utc(to_ts))

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    # Clients receive the selected newest rows oldest-first.
    rows.reverse()

    return [
        {
            "id": row.id,
            "timestamp": _iso_utc_z(row.timestamp),
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
    return await load_alert_config(db)


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

    current = await load_alert_config(db)
    current.update(config)

    # Validate thresholds are in 0–100
    for key in ("cpu_threshold", "ram_threshold", "disk_threshold"):
        value = current.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise HTTPException(status_code=400, detail=f"{key} must be between 0 and 100")
    if not isinstance(current.get("webhook_url"), str):
        raise HTTPException(status_code=400, detail="Webhook URL must be a string")

    serialized = json.dumps(current)

    # Upsert — update if row exists, insert otherwise
    result = await db.execute(select(Setting).where(Setting.key == ALERT_CONFIG_KEY))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = serialized
    else:
        db.add(Setting(key=ALERT_CONFIG_KEY, value=serialized))

    await db.commit()
    logger.info("Alert configuration updated")
    return current
