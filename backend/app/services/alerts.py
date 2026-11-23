"""Threshold notifications evaluated by the server's metrics scheduler."""
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.services.metrics_service import MetricsSnapshot

logger = logging.getLogger(__name__)
ALERT_CONFIG_KEY = "alert_config"

# Default alert thresholds and webhook
DEFAULT_ALERT_CONFIG: dict[str, Any] = {
    "cpu_threshold": 80,
    "ram_threshold": 85,
    "disk_threshold": 90,
    "webhook_url": "",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


async def load_alert_config(db: AsyncSession) -> dict[str, Any]:
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
        return {**DEFAULT_ALERT_CONFIG, **data}
    except (json.JSONDecodeError, ValueError, TypeError):
        return DEFAULT_ALERT_CONFIG.copy()



class ThresholdAlerts:
    """Report each threshold crossing once until recovery or a configuration change."""

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.delivered: set[str] = set()

    async def evaluate(self, snapshot: MetricsSnapshot, config: dict[str, Any]) -> None:
        if self.config != config:
            self.config = config.copy()
            self.delivered.clear()
        if not config["webhook_url"]:
            return

        exceeded = {}
        for metric, value in (("cpu", snapshot.cpu_percent), ("ram", snapshot.ram_percent),
                              ("disk", snapshot.disk_percent)):
            limit = float(config[f"{metric}_threshold"])
            if value >= limit:
                exceeded[metric] = f"{metric.upper()}: {value:.1f}% (threshold {limit:g}%)"
        self.delivered.intersection_update(exceeded)
        new = [message for key, message in exceeded.items() if key not in self.delivered]
        if not new:
            return

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(config["webhook_url"], json={
                    "content": "**Homelab Dashboard Alert**\n" + "\n".join(new)
                })
                response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Alert delivery failed. The next sample will retry active alerts.")
            return
        self.delivered.update(exceeded)
