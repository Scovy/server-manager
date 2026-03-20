"""SQLAlchemy models for the Homelab Dashboard.

All models inherit from the shared `Base` declarative base.
Import models here so Alembic can discover them for auto-migration.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# Import all models so they are registered with Base.metadata
# This is required for Alembic autogenerate to detect them.
from app.models.audit_log import AuditLog  # noqa: E402, F401
from app.models.metrics_history import MetricsHistory  # noqa: E402, F401
from app.models.setting import Setting  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
