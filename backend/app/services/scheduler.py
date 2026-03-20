"""APScheduler background jobs for periodic metrics recording and cleanup.

Two jobs run on the AsyncIOScheduler:
1. **Record metrics** (every 60 s) — takes a MetricsSnapshot and inserts a row
   into the ``metrics_history`` table.
2. **Prune old records** (every 60 s, offset by 30 s) — deletes rows older than
   7 days to keep the SQLite file from growing unboundedly.

Usage::

    from app.services.scheduler import start_scheduler, stop_scheduler

    # In FastAPI lifespan:
    scheduler = start_scheduler(async_session_factory)
    ...
    stop_scheduler(scheduler)
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.metrics_history import MetricsHistory
from app.services.metrics_service import metrics_service

logger = logging.getLogger(__name__)

# How long to keep history rows before pruning
HISTORY_TTL_DAYS = 7


async def _record_metrics(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Take a snapshot and persist it to the database.

    This function is called by APScheduler every 60 seconds.
    Errors are caught and logged so a transient failure doesn't crash the job.

    Args:
        session_factory: Factory for creating async DB sessions.
    """
    try:
        snapshot = await metrics_service.get_snapshot()
        row = MetricsHistory(
            timestamp=datetime.utcnow(),
            cpu_percent=snapshot.cpu_percent,
            ram_percent=snapshot.ram_percent,
            ram_used_mb=snapshot.ram_used_mb,
            disk_percent=snapshot.disk_percent,
            net_bytes_sent=snapshot.net_bytes_sent,
            net_bytes_recv=snapshot.net_bytes_recv,
        )
        async with session_factory() as session:
            session.add(row)
            await session.commit()
        logger.debug(
            "Metrics snapshot saved: cpu=%.1f%% ram=%.1f%%",
            snapshot.cpu_percent,
            snapshot.ram_percent,
        )
    except Exception as e:
        logger.error("Failed to record metrics snapshot: %s", e)


async def _prune_old_metrics(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Delete metrics history rows older than HISTORY_TTL_DAYS.

    This function is called by APScheduler every 60 seconds (offset 30 s
    from the record job to avoid contention).

    Args:
        session_factory: Factory for creating async DB sessions.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=HISTORY_TTL_DAYS)
        async with session_factory() as session:
            result = await session.execute(
                delete(MetricsHistory).where(MetricsHistory.timestamp < cutoff)
            )
            await session.commit()
            deleted = int(getattr(result, "rowcount", 0))
        if deleted:
            logger.info(
                "Pruned %d old metrics rows (older than %d days)",
                deleted,
                HISTORY_TTL_DAYS,
            )
    except Exception as e:
        logger.error("Failed to prune metrics history: %s", e)


def start_scheduler(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIOScheduler:
    """Create, configure and start the APScheduler instance.

    Args:
        session_factory: SQLAlchemy async session factory to inject into jobs.

    Returns:
        The running AsyncIOScheduler instance (store a reference to call stop_scheduler).
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _record_metrics,
        trigger="interval",
        seconds=60,
        id="record_metrics",
        kwargs={"session_factory": session_factory},
        replace_existing=True,
    )
    scheduler.add_job(
        _prune_old_metrics,
        trigger="interval",
        seconds=60,
        id="prune_metrics",
        kwargs={"session_factory": session_factory},
        replace_existing=True,
        # Offset by 30 s so record and prune don't run at the same instant
        next_run_time=datetime.now() + timedelta(seconds=30),
    )

    scheduler.start()
    logger.info("Background scheduler started (record + prune jobs active)")
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Gracefully shut down the scheduler.

    Args:
        scheduler: The scheduler instance returned by start_scheduler.
    """
    scheduler.shutdown(wait=False)
    logger.info("Background scheduler stopped")
