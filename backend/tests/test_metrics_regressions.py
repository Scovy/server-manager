"""Regression tests for dashboard metrics behavior.

Covers:
- /api/metrics/history: latest-N selection (descending query, ascending response),
  UTC "Z" timestamps, and from/to params carrying UTC offsets.
- /ws/metrics: server-side `timestamp`, nullable `container_summary`, disk label.
- MetricsService: container runtime summary from one Docker listing, with
  per-container stats only for containers a default `docker ps` shows.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.metrics_history import MetricsHistory
from app.services.metrics_service import (
    ContainerSummary,
    MetricsService,
    MetricsSnapshot,
    _disk_source,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_disk_source_cache() -> None:
    """The root lookup is process-cached in production; each test starts clean."""
    _disk_source.cache_clear()


def _history_row(ts: datetime, cpu: float) -> MetricsHistory:
    return MetricsHistory(
        timestamp=ts,
        cpu_percent=cpu,
        ram_percent=1.0,
        ram_used_mb=1,
        disk_percent=1.0,
        net_bytes_sent=1,
        net_bytes_recv=1,
    )


def _stats_payload() -> dict:
    # cpu_delta=50, system_delta=100, 1 cpu → 50.0%
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 150},
            "system_cpu_usage": 300,
            "online_cpus": 1,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 200,
        },
        "memory_stats": {"usage": 1048576, "limit": 2097152},
    }


def _fake_container(name: str, status: str, health: str | None = None) -> MagicMock:
    """Sparse-listing fake: attrs match a `/containers/json` entry, and
    ``reload()`` replaces them with a full inspect payload."""
    inspect_state: dict = {"Status": status}
    if health is not None:
        inspect_state["Health"] = {"Status": health}
    inspect_attrs = {"Id": f"{name}-id", "Name": f"/{name}", "State": inspect_state}
    c = MagicMock()
    c.attrs = {"Id": f"{name}-id", "Names": [f"/{name}"], "State": status}
    c.short_id = f"{name}-id"
    c.reload = MagicMock(side_effect=lambda: setattr(c, "attrs", inspect_attrs))
    c.stats = MagicMock(return_value=_stats_payload())
    return c


# ── /api/metrics/history ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_returns_latest_n_oldest_first(
    async_db: AsyncSession, client: AsyncClient, admin_session: str
) -> None:
    """limit selects the NEWEST rows; response keeps the old ascending order."""
    base = datetime(2026, 11, 23, 12, 0, 0)
    for i in range(5):
        async_db.add(_history_row(base + timedelta(minutes=i), cpu=float(i)))
    await async_db.commit()

    res = await client.get("/api/metrics/history", params={"limit": 3})
    assert res.status_code == 200
    rows = res.json()
    assert [r["cpu_percent"] for r in rows] == [2.0, 3.0, 4.0]
    # Stored naive UTC is emitted as ISO 8601 UTC with a Z suffix.
    assert [r["timestamp"] for r in rows] == [
        "2026-11-23T12:02:00Z",
        "2026-11-23T12:03:00Z",
        "2026-11-23T12:04:00Z",
    ]


@pytest.mark.asyncio
async def test_history_range_with_utc_offsets(
    async_db: AsyncSession, client: AsyncClient, admin_session: str
) -> None:
    """from/to may carry UTC offsets; within a range the latest N are returned."""
    base = datetime(2026, 11, 23, 12, 0, 0)
    for i in range(5):
        async_db.add(_history_row(base + timedelta(minutes=i), cpu=float(i)))
    await async_db.commit()

    # Window 12:01–12:03 UTC, expressed with a +02:00 offset.
    window = {"from": "2026-11-23T14:01:00+02:00", "to": "2026-11-23T14:03:00+02:00"}

    res = await client.get("/api/metrics/history", params={**window, "limit": 10})
    assert [r["cpu_percent"] for r in res.json()] == [1.0, 2.0, 3.0]

    res = await client.get("/api/metrics/history", params={**window, "limit": 2})
    assert [r["cpu_percent"] for r in res.json()] == [2.0, 3.0]


@pytest.mark.asyncio
async def test_history_timestamps_parse_as_utc(
    async_db: AsyncSession, client: AsyncClient, admin_session: str
) -> None:
    """The Z-suffixed timestamps must represent the same instants that were stored."""
    ts = datetime(2026, 11, 23, 23, 59, 59)
    async_db.add(_history_row(ts, cpu=42.0))
    await async_db.commit()

    res = await client.get("/api/metrics/history")
    stamp = res.json()[0]["timestamp"]
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed == ts.replace(tzinfo=timezone.utc)


# ── /ws/metrics payload ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.routers.metrics.WS_INTERVAL", 0.05)
@patch("app.routers.metrics.CONTAINER_REFRESH_INTERVAL", 10.0)
@patch("app.routers.metrics.time")
@patch("app.routers.metrics.metrics_service", new_callable=AsyncMock)
async def test_ws_container_refresh_throttled_when_all_stopped(
    mock_service, mock_time, admin_session
) -> None:
    """Empty containers + null summary is a valid (all-stopped) state.

    The refresh must be driven by the interval, not by the result: the first
    listing fires immediately, the clock stays frozen while ticks keep
    coming (no re-listing on empty data), and exactly one more listing runs
    after the clock moves past the interval.
    """
    clock = {"t": 0.0}  # virtual monotonic clock, driven by this test
    mock_time.monotonic.side_effect = lambda: clock["t"]

    listing_calls: list[int] = []
    host = MetricsSnapshot(
        cpu_percent=1.0,
        ram_percent=1.0,
        ram_used_mb=1,
        ram_total_mb=2,
        disk_percent=1.0,
        disk_used_gb=1.0,
        disk_total_gb=2.0,
        net_bytes_sent=1,
        net_bytes_recv=1,
        containers=[],
    )

    async def fake_get_snapshot(include_containers: bool = True) -> MetricsSnapshot:
        if include_containers:
            listing_calls.append(1)
        # Valid all-stopped / Docker-unavailable attempt: no stats, no summary.
        return host

    mock_service.get_snapshot = fake_get_snapshot

    with TestClient(app).websocket_connect(
        "/ws/metrics", subprotocols=["homelab.v1", admin_session]
    ) as ws:
        ws.receive_json()  # initial host-only snapshot
        # Clock frozen at 0: the first listing already ran, and NO number of
        # ticks with an empty result may trigger another one.
        for _ in range(3):
            msg = ws.receive_json()
            assert msg["containers"] == []
            assert msg["container_summary"] is None
        assert listing_calls == [1]

        # Move the clock past the interval: exactly one more listing, then
        # throttled again while the clock stays where the test put it.
        clock["t"] = 20.0
        for _ in range(5):
            ws.receive_json()
        assert listing_calls == [1, 1]


@pytest.mark.asyncio
@patch("app.routers.metrics.metrics_service", new_callable=AsyncMock)
async def test_ws_message_has_server_timestamp_and_nullable_summary(
    mock_service, admin_session
) -> None:
    """WS message carries a server-side UTC 'Z' timestamp; unknown fields are null."""
    mock_snapshot = MetricsSnapshot(
        cpu_percent=1.0,
        ram_percent=1.0,
        ram_used_mb=1,
        ram_total_mb=2,
        disk_percent=1.0,
        disk_used_gb=1.0,
        disk_total_gb=2.0,
        net_bytes_sent=1,
        net_bytes_recv=1,
        containers=[],
    )
    mock_service.get_snapshot.return_value = mock_snapshot

    with TestClient(app).websocket_connect(
        "/ws/metrics", subprotocols=["homelab.v1", admin_session]
    ) as ws:
        assert ws.accepted_subprotocol == "homelab.v1"
        msg = ws.receive_json()

    assert msg["timestamp"].endswith("Z")
    parsed = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60
    assert msg["container_summary"] is None
    assert msg["containers"] == []
    assert msg["disk_source"] is None
    # New optional field serializes as null when the caller did not set it.
    assert msg["disk_free_gb"] is None


# ── MetricsService ──────────────────────────────────────────────────────────────


def test_snapshot_container_summary_and_no_stats_for_stopped() -> None:
    """Summary counts all states from one sparse listing; only active are
    inspected and stat-ed — stopped get neither."""
    sick = _fake_container("web", "running", "unhealthy")
    exited = _fake_container("old", "exited")
    running = _fake_container("app", "running", "healthy")
    looping = _fake_container("loop", "restarting")
    paused = _fake_container("hold", "paused")

    docker_client = MagicMock()
    docker_client.containers.list.return_value = [sick, exited, running, looping, paused]

    with (
        patch("app.services.metrics_service.docker.from_env", return_value=docker_client),
        patch(
            "app.services.metrics_service.psutil.disk_partitions",
            return_value=[SimpleNamespace(device="overlay", mountpoint="/")],
        ),
    ):
        snapshot = MetricsService()._get_snapshot_sync(include_containers=True)

    # Sparse listing: no per-container inspect in the listing call itself.
    docker_client.containers.list.assert_called_with(all=True, sparse=True)
    # Stopped containers get neither an inspect nor a stats call.
    exited.reload.assert_not_called()
    exited.stats.assert_not_called()
    assert snapshot.container_summary == ContainerSummary(
        running=2, total=5, unhealthy=1, restarting=1
    )
    # `containers` keeps its docker-ps meaning (running/paused/restarting), with
    # exact inspect state and no hidden SDK reloads for names.
    assert [c.name for c in snapshot.containers] == ["web", "app", "loop", "hold"]
    assert snapshot.disk_source == "overlay"
    assert snapshot.timestamp.tzinfo is not None


def test_snapshot_summary_null_when_active_inspect_fails() -> None:
    """Failed inspect of an active container → health unknown → the whole
    summary is null; stats are still kept where possible."""
    broken = _fake_container("app", "running")
    broken.reload.side_effect = RuntimeError("inspect failed")

    docker_client = MagicMock()
    docker_client.containers.list.return_value = [broken]

    with (
        patch("app.services.metrics_service.docker.from_env", return_value=docker_client),
        patch("app.services.metrics_service.psutil.disk_partitions", return_value=[]),
    ):
        snapshot = MetricsService()._get_snapshot_sync(include_containers=True)

    assert snapshot.container_summary is None
    assert [c.name for c in snapshot.containers] == ["app"]


def test_snapshot_reports_real_disk_free() -> None:
    """disk_free_gb comes from psutil's ``.free`` (FS reserve included), not
    ``total - used``."""
    usage = SimpleNamespace(total=100 * 1024**3, used=30 * 1024**3, free=60 * 1024**3, percent=30.0)
    with (
        patch("app.services.metrics_service.psutil.disk_usage", return_value=usage),
        patch("app.services.metrics_service.psutil.disk_partitions", return_value=[]),
    ):
        snapshot = MetricsService()._get_snapshot_sync(include_containers=False)

    assert snapshot.disk_free_gb == 60.0  # total - used would say 70


def test_snapshot_without_docker_leaves_summary_null() -> None:
    """When Docker is unavailable the summary stays None instead of being guessed."""
    with patch("app.services.metrics_service.docker.from_env", side_effect=OSError("no socket")):
        snapshot = MetricsService()._get_snapshot_sync(include_containers=True)

    assert snapshot.containers == []
    assert snapshot.container_summary is None
    # Host-side metrics (and their sample timestamp) are still present.
    assert snapshot.timestamp.tzinfo is not None


def test_disk_source_prefers_longest_mount_prefix() -> None:
    """The label points at the device backing the path, as seen from the backend."""
    parts = [
        SimpleNamespace(device="overlay", mountpoint="/"),
        SimpleNamespace(device="/dev/sdb1", mountpoint="/mnt/data"),
        SimpleNamespace(device="tmpfs", mountpoint="/mnt/data/tmp"),
    ]
    with patch("app.services.metrics_service.psutil.disk_partitions", return_value=parts):
        assert _disk_source() == "overlay"
        assert _disk_source("/mnt/data/media") == "/dev/sdb1"
        assert _disk_source("/mnt/data/tmp/x") == "tmpfs"


def test_disk_source_unknown_when_no_mount_matches() -> None:
    with patch("app.services.metrics_service.psutil.disk_partitions", return_value=[]):
        assert _disk_source() is None


def test_disk_source_cached_for_process_lifetime() -> None:
    """Mounts are static: the root lookup is scanned once and then reused."""
    first = [SimpleNamespace(device="overlay", mountpoint="/")]
    with patch("app.services.metrics_service.psutil.disk_partitions", return_value=first):
        assert _disk_source() == "overlay"

    # A later call must not rescan — changed mount data is ignored.
    with patch("app.services.metrics_service.psutil.disk_partitions", return_value=[]):
        assert _disk_source() == "overlay"
