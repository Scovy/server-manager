"""System metrics collection service using psutil and Docker SDK.

Provides a single `MetricsService` class that:
- Polls CPU, RAM, disk and network metrics via psutil
- Queries per-container resource usage via Docker stats API
- Exposes typed Pydantic models for use by the WebSocket router and scheduler

All Docker operations are wrapped in try/except so the service degrades
gracefully when Docker Engine is unavailable.
"""

import functools
import logging
from datetime import datetime, timezone
from typing import Any

import docker
import psutil
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Container states shown by a default `docker ps` listing. Health inspects and
# per-container stats are collected only for these; stopped containers get
# neither a stats call nor an inspect.
_STATS_STATUSES = frozenset({"running", "paused", "restarting"})


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


class ContainerSummary(BaseModel):
    """Runtime container counts for the dashboard card.

    Totals and state counts come from a single *sparse* Docker listing (one
    API call, no per-container inspect); ``unhealthy`` comes from the health
    inspects of active containers only — stopped containers are never
    inspected, and the whole summary is ``None`` whenever health is unknown.

    Attributes:
        running: Containers currently in the ``running`` state.
        total: All containers known to Docker (including stopped ones).
        unhealthy: Active containers whose health check reports ``unhealthy``.
        restarting: Containers crash-looping under a restart policy.
    """

    running: int
    total: int
    unhealthy: int
    restarting: int


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
        disk_free_gb: Real free space (psutil ``.free`` — includes the FS
            reserve, unlike ``total - used``) in gigabytes; ``None`` when the
            caller did not provide it (backwards-compatible default).
        net_bytes_sent: Cumulative bytes sent since boot.
        net_bytes_recv: Cumulative bytes received since boot.
        containers: Per-container stats (empty list if Docker unavailable).
        timestamp: Server-side time (UTC, ISO 8601 "Z") of the host sample,
            captured before the slow Docker stats pass.
        disk_source: Device backing the measured path ``/`` as seen from this
            backend process (e.g. ``overlay`` inside Docker, ``/dev/sda1`` on a
            host install) — ``None`` if it cannot be determined.
        container_summary: Runtime counts across all containers, or ``None``
            when Docker was unavailable (never guessed).
    """

    cpu_percent: float
    ram_percent: float
    ram_used_mb: int
    ram_total_mb: int
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    disk_free_gb: float | None = None
    net_bytes_sent: int
    net_bytes_recv: int
    containers: list[ContainerStat] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disk_source: str | None = None
    container_summary: ContainerSummary | None = None


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
            stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        )
        num_cpus = stats["cpu_stats"].get("online_cpus") or len(
            stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
        )
        if system_delta > 0 and cpu_delta >= 0:
            return float(round((cpu_delta / system_delta) * num_cpus * 100.0, 2))
    except (KeyError, ZeroDivisionError, TypeError):
        pass
    return 0.0


@functools.lru_cache(maxsize=None)
def _disk_source(path: str = "/") -> str | None:
    """Device backing ``path`` as seen from this backend process.

    The disk metrics measure ``psutil.disk_usage("/")`` — i.e. the backend's
    own root filesystem (the container overlay when deployed in Docker), not
    the host's root disk. This label lets the dashboard say which filesystem
    the numbers describe. No mounts are read or changed beyond this lookup.

    Mount layout is static, so each path is resolved once per process and
    cached — the scan must not repeat on every ~0.8 s WS tick.
    """
    try:
        parts = psutil.disk_partitions(all=True)
    except Exception:  # different platforms expose different mounts
        return None  # transient — not cached, retried next tick
    best_device: str | None = None
    best_len = -1
    for part in parts:
        mountpoint = part.mountpoint
        prefix = mountpoint if mountpoint.endswith("/") else mountpoint + "/"
        if not (path == mountpoint or path.startswith(prefix)):
            continue
        if len(mountpoint) > best_len:
            best_device, best_len = part.device, len(mountpoint)
    return best_device


def _listed_state(attrs: Any) -> str:
    """Container state from listing/inspect attrs, without the SDK property.

    In a sparse listing ``State`` is a plain string (``"running"`` …); after
    ``reload()`` it is a dict with ``Status``/``Health``. The human ``Status``
    text ("Up 2 hours") is never parsed.
    """
    state = attrs.get("State")
    if isinstance(state, dict):
        state = state.get("Status")
    return str(state).lower()


def _listed_name(attrs: Any) -> str:
    """Container name from listing (``Names``) or inspect (``Name``) attrs.

    The SDK's ``Container.name`` reloads sparse objects (a hidden inspect);
    this reads the attrs directly instead.
    """
    names = attrs.get("Names")
    if isinstance(names, list) and names:
        return str(names[0]).lstrip("/")
    return str(attrs.get("Name", "")).lstrip("/")


class MetricsService:
    """Collects system and container metrics on demand.

    Usage::

        service = MetricsService()
        snapshot = service.get_snapshot()
        print(snapshot.cpu_percent)
    """

    async def get_snapshot(self, include_containers: bool = True) -> MetricsSnapshot:
        """Return a complete metrics snapshot for the current moment.

        Collects host metrics via psutil and per-container stats via Docker.
        Docker errors are caught and logged; the snapshot still returns with
        an empty ``containers`` list in that case.

        Runs blocking IO in a separate thread to avoid hanging the event loop.

        Returns:
            MetricsSnapshot with current CPU, RAM, disk, network and container data.
        """
        import asyncio

        return await asyncio.to_thread(self._get_snapshot_sync, include_containers)

    def _get_snapshot_sync(self, include_containers: bool = True) -> MetricsSnapshot:
        """Synchronous implementation of metrics collection."""
        # Host-sample time, captured before the slow Docker stats pass, so the
        # `timestamp` refers to the sample itself, not the end of collection.
        timestamp = datetime.now(timezone.utc)

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
        disk_free_gb = round(disk.free / (1024**3), 2)
        disk_source = _disk_source()

        net = psutil.net_io_counters()
        net_sent = net.bytes_sent
        net_recv = net.bytes_recv

        containers: list[ContainerStat] = []
        summary: ContainerSummary | None = None
        if include_containers:
            # ── Per-container stats + runtime summary (Docker SDK) ────────────
            client: Any = None
            try:
                client = docker.from_env()
                # One SPARSE listing of all containers: a single API call that
                # inspects nothing — the SDK's default listing inspects every
                # entry, which would tax stopped containers on every refresh.
                listed = client.containers.list(all=True, sparse=True)
                running = restarting = 0
                active: list[Any] = []
                for container in listed:
                    state = _listed_state(container.attrs)
                    if state == "running":
                        running += 1
                    elif state == "restarting":
                        restarting += 1
                    if state in _STATS_STATUSES:
                        active.append(container)

                # Health lives only in inspect — reload the same active set a
                # non-sparse listing would have inspected; stopped are skipped.
                unhealthy = 0
                summary_reliable = True
                for container in active:
                    try:
                        container.reload()
                        state = container.attrs.get("State")
                        if isinstance(state, dict):
                            health = state.get("Health") or {}
                            if health.get("Status") == "unhealthy":
                                unhealthy += 1
                        else:
                            summary_reliable = False
                    except Exception as e:
                        # No inspect → health unknown for this container; the
                        # summary is dropped entirely rather than guessed.
                        summary_reliable = False
                        logger.debug("Error inspecting container %s: %s", container.short_id, e)
                    try:
                        stats = container.stats(stream=False)
                        cpu_pct = _calc_container_cpu(stats)
                        mem_stats = stats.get("memory_stats", {})
                        mem_usage = mem_stats.get("usage", 0)
                        mem_limit = mem_stats.get("limit", 0)
                        containers.append(
                            ContainerStat(
                                id=container.short_id,
                                name=_listed_name(container.attrs),
                                status=_listed_state(container.attrs),
                                cpu_percent=cpu_pct,
                                mem_usage_mb=round(mem_usage / (1024 * 1024), 2),
                                mem_limit_mb=round(mem_limit / (1024 * 1024), 2),
                            )
                        )
                    except Exception as e:
                        logger.debug(
                            "Error fetching stats for container %s: %s",
                            container.short_id,
                            e,
                        )
                if summary_reliable:
                    summary = ContainerSummary(
                        running=running,
                        total=len(listed),
                        unhealthy=unhealthy,
                        restarting=restarting,
                    )
            except Exception as e:
                logger.warning("Docker unavailable — skipping container stats: %s", e)
            finally:
                # The old code leaked the client when the listing itself failed.
                if client is not None:
                    client.close()

        return MetricsSnapshot(
            cpu_percent=cpu,
            ram_percent=ram_percent,
            ram_used_mb=ram_used_mb,
            ram_total_mb=ram_total_mb,
            disk_percent=disk_percent,
            disk_used_gb=disk_used_gb,
            disk_total_gb=disk_total_gb,
            disk_free_gb=disk_free_gb,
            net_bytes_sent=net_sent,
            net_bytes_recv=net_recv,
            containers=containers,
            timestamp=timestamp,
            disk_source=disk_source,
            container_summary=summary,
        )


# Module-level singleton — reused by the router and scheduler
metrics_service = MetricsService()
