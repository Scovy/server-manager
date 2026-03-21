"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env file and environment variables.

    Attributes:
        APP_NAME: Display name of the application.
        DEBUG: Enable debug mode (verbose logging, auto-reload).
        VERSION: Current application version.
        JWT_SECRET: Secret key for signing JWT tokens. MUST be changed in production.
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES: Access token TTL in minutes.
        JWT_REFRESH_TOKEN_EXPIRE_DAYS: Refresh token TTL in days.
        DATABASE_URL: SQLAlchemy async database URL.
        DOMAIN: Public domain for SSL and reverse proxy configuration.
        CORS_ORIGINS: Comma-separated list of allowed CORS origins.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Application
    APP_NAME: str = "Homelab Dashboard"
    DEBUG: bool = False
    VERSION: str = "0.1.0"

    # Security
    JWT_SECRET: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./homelab.db"

    # Infrastructure
    DOMAIN: str = "localhost"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Metrics
    METRICS_WS_INTERVAL_SECONDS: float = 1.0

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


settings = Settings()
