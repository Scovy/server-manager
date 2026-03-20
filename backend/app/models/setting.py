"""Key-value settings model for runtime configuration."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Setting(Base):
    """Generic key-value store for application settings.

    Used for runtime-configurable options like alert thresholds,
    DDNS config, and UI preferences. Not for secrets — use .env for those.

    Attributes:
        key: Setting name (primary key).
        value: Setting value (stored as text, parsed by the application).
        updated_at: Last update timestamp.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
