"""Audit log model for tracking all state-changing operations."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AuditLog(Base):
    """Immutable record of every state-changing action in the system.

    Attributes:
        id: Auto-incrementing primary key.
        timestamp: When the action occurred.
        user_id: FK to the user who performed the action (nullable for system actions).
        action: Action identifier, e.g. 'container.stop', 'backup.create'.
        target: What was acted upon, e.g. container ID, domain name.
        ip_address: Client IP address (from X-Forwarded-For behind Caddy).
        success: Whether the action succeeded (1) or failed (0).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    success: Mapped[int] = mapped_column(Integer, default=1)
