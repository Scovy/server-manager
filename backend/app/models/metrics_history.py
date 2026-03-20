"""SQLAlchemy model for storing historical system metrics snapshots."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class MetricsHistory(Base):
    """A single point-in-time snapshot of system resource usage.

    Rows are written every 60 seconds by the background scheduler.
    Old rows (older than 7 days) are pruned on the same schedule.

    Attributes:
        id: Auto-incremented primary key.
        timestamp: UTC time when the snapshot was taken.
        cpu_percent: CPU usage across all cores (0–100).
        ram_percent: RAM usage percentage (0–100).
        ram_used_mb: RAM currently in use, in megabytes.
        disk_percent: Primary disk usage percentage (0–100).
        net_bytes_sent: Cumulative bytes sent since boot.
        net_bytes_recv: Cumulative bytes received since boot.
    """

    __tablename__ = "metrics_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    ram_percent: Mapped[float] = mapped_column(Float, nullable=False)
    ram_used_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_percent: Mapped[float] = mapped_column(Float, nullable=False)
    net_bytes_sent: Mapped[int] = mapped_column(Integer, nullable=False)
    net_bytes_recv: Mapped[int] = mapped_column(Integer, nullable=False)

    # Index on timestamp for efficient TTL pruning (DELETE WHERE timestamp < ...)
    __table_args__ = (Index("idx_metrics_history_ts", "timestamp"),)

    def __repr__(self) -> str:
        return (
            f"<MetricsHistory id={self.id} ts={self.timestamp} "
            f"cpu={self.cpu_percent:.1f}% ram={self.ram_percent:.1f}%>"
        )
