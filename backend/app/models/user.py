"""User model for authentication and authorization."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class User(Base):
    """Application user with authentication credentials.

    Attributes:
        id: Auto-incrementing primary key.
        username: Unique username for login.
        password: bcrypt-hashed password.
        totp_secret: TOTP secret for 2FA (NULL = disabled).
        role: User role — 'admin' (full access) or 'viewer' (read-only).
        created_at: Timestamp of account creation.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
