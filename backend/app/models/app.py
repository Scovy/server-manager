"""SQLAlchemy model for marketplace-installed applications."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class App(Base):
    """Persisted record of an application installed from Marketplace."""

    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    app_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    container_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    host_port: Mapped[int] = mapped_column(Integer, nullable=False)
    app_dir: Mapped[str] = mapped_column(String, nullable=False)
    compose_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="deployed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<App id={self.id} name={self.app_name} status={self.status}>"
