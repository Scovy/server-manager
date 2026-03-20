"""System metrics collection service using psutil and Docker SDK.

Provides a single `MetricsService` class that:
- Polls CPU, RAM, disk and network metrics via psutil
- Queries per-container resource usage via Docker stats API
- Exposes typed Pydantic models for use by the WebSocket router and scheduler

All Docker operations are wrapped in try/except so the service degrades
gracefully when Docker Engine is unavailable.
"""

import logging
from typing import Any

import docker
import psutil
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ContainerStat(BaseModel):
    """Resource usage for a single Docker container.

    Attributes:
        id: Short container ID (first 12 chars).
        name: Container name without leading slash.
        status: Current container status (running, exited, …).
        cpu_percent: CPU usage as a percentage of one core (may exceed 100 on multi-core).
        mem_usage_mb: Memory currently consumed, in MB.
        mem_limit_mb: Memory limit set for the container (0 = unlimited / host RAM).
    """

    id: str
    name: str
    status: str
    cpu_percent: float
    mem_usage_mb: float
    mem_limit_mb: float


class MetricsSnapshot(BaseModel):
    """Point-in-time snapshot of host system metrics.

    Attributes:
        cpu_percent: CPU usage percentage across all cores (0–100).
        ram_percent: RAM usage percentage (0–100).
        ram_used_mb: RAM used in megabytes.
        ram_total_mb: Total RAM in megabytes.
        disk_percent: Primary filesystem usage percentage (0–100).
        disk_used_gb: Disk space used in gigabytes.
        disk_total_gb: Total disk space in gigabytes.
        net_bytes_sent: Cumulative bytes sent since boot.
        net_bytes_recv: Cumulative bytes received since boot.
        containers: Per-container stats (empty list if Docker unavailable).
    """

    cpu_percent: float
    ram_percent: float
    ram_used_mb: int
    ram_total_mb: int
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    net_bytes_sent: int
    net_bytes_recv: int
    containers: list[ContainerStat] = []


def _calc_container_cpu(stats: dict[str, Any]) -> float:
    """Calculate container CPU percentage from Docker stats response.

    Docker stats provides cumulative CPU ticks; we compute the delta
    between this and the previous sample to get a real-time percentage.

    Args:
        stats: Raw stats dict from docker SDK container.stats(stream=False).

    Returns:
        CPU usage as a float percentage (can exceed 100% on multi-core hosts).
    """
    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        num_cpus = stats["cpu_stats"].get("online_cpus") or len(
            stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
        )
        if system_delta > 0 and cpu_delta >= 0:
            return round((cpu_delta / system_delta) * num_cpus * 100.0, 2)
    except (KeyError, ZeroDivisionError, TypeError):
        pass
    return 0.0


class MetricsService:
    """Collects system and container metrics on demand.

    Usage::

        service = MetricsService()
        snapshot = service.get_snapshot()
        print(snapshot.cpu_percent)
    """

    def get_snapshot(self) -> MetricsSnapshot:
        """Return a complete metrics snapshot for the current moment.

        Collects host metrics via psutil and per-container stats via Docker.
        Docker errors are caught and logged; the snapshot still returns with
        an empty ``containers`` list in that case.

        Returns:
            MetricsSnapshot with current CPU, RAM, disk, network and container data.
        """
        # ── Host metrics (psutil) ─────────────────────────────────────────────
        cpu = psutil.cpu_percent(interval=None)

        mem = psutil.virtual_memory()
        ram_percent = mem.percent
        ram_used_mb = mem.used // (1024 * 1024)
        ram_total_mb = mem.total // (1024 * 1024)

        disk = psutil.disk_usage("/")
        disk_percent = disk.percent
        disk_used_gb = round(disk.used / (1024**3), 2)
        disk_total_gb = round(disk.total / (1024**3), 2)

        net = psutil.net_io_counters()
        net_sent = net.bytes_sent
        net_recv = net.bytes_recv

        # ── Per-container stats (Docker SDK) ─────────────────────────────────
        containers: list[ContainerStat] = []
        try:
            client = docker.from_env()
            for container in client.containers.list():
                try:
                    stats = container.stats(stream=False)
                    cpu_pct = _calc_container_cpu(stats)
                    mem_stats = stats.get("memory_stats", {})
                    mem_usage = mem_stats.get("usage", 0)
                    mem_limit = mem_stats.get("limit", 0)
                    containers.append(
                        ContainerStat(
                            id=container.short_id,
                            name=container.name.lstrip("/"),
                            status=container.status,
                            cpu_percent=cpu_pct,
                            mem_usage_mb=round(mem_usage / (1024 * 1024), 2),
                            mem_limit_mb=round(mem_limit / (1024 * 1024), 2),
                        )
                    )
                except Exception as e:
                    logger.debug("Error fetching stats for container %s: %s", container.short_id, e)
            client.close()
        except Exception as e:
            logger.warning("Docker unavailable — skipping container stats: %s", e)

        return MetricsSnapshot(
            cpu_percent=cpu,
            ram_percent=ram_percent,
            ram_used_mb=ram_used_mb,
            ram_total_mb=ram_total_mb,
            disk_percent=disk_percent,
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            net_bytes_sent=net_sent,
            net_bytes_recv=net_recv,
            containers=containers,
        )


# Module-level singleton — reused by the router and scheduler
metrics_service = MetricsService()
