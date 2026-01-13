"""
Centralized configuration for Lead Validator backend.
All environment variables are read and validated here.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime


class Config:
    """Application configuration with validation."""

    # Application version (single source of truth)
    VERSION: str = "2.0.0"

    # Testing mode detection (disables background threads)
    TESTING: bool = os.getenv("TESTING", "").lower() in ("1", "true", "yes")

    # Time provider for testability (dependency injection)
    _now_provider: Callable[[], datetime] | None = None

    @classmethod
    def set_time_provider(cls, provider: Callable[[], datetime] | None) -> None:
        """Set custom time provider for testing."""
        cls._now_provider = provider

    @classmethod
    def now_utc(cls) -> datetime:
        """Get current UTC time (injectable for tests)."""
        if cls._now_provider:
            return cls._now_provider()
        return datetime.now(UTC)

    # Server
    PORT: int = int(os.getenv("PORT", "5050"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    DEBUG: bool = os.getenv("FLASK_ENV", "development") == "development"

    # Validator
    VALIDATOR_MODE: str = os.getenv("VALIDATOR_MODE", "real")  # 'real' or 'mock'

    # Upload limits
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    MAX_CONTENT_LENGTH: int = MAX_UPLOAD_MB * 1024 * 1024  # Convert to bytes

    # CSV limits
    MAX_CSV_ROWS: int = int(os.getenv("MAX_CSV_ROWS", "10000"))
    MAX_LINE_LENGTH: int = int(os.getenv("MAX_LINE_LENGTH", "10000"))

    # CORS
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")  # Comma-separated, empty = same-origin only

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Storage
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", os.path.join(os.path.dirname(__file__), "storage"))
    DB_PATH: str = os.getenv("DB_PATH", os.path.join(STORAGE_DIR, "lead_validator.db"))

    # Retention
    RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "14"))
    MAX_JOBS: int = int(os.getenv("MAX_JOBS", "200"))

    # Concurrency
    MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))

    # Job health monitoring (heartbeat / stall detection)
    JOB_HEARTBEAT_INTERVAL_ROWS: int = int(os.getenv("JOB_HEARTBEAT_INTERVAL_ROWS", "10"))
    JOB_STALL_TIMEOUT_MINUTES: int = int(os.getenv("JOB_STALL_TIMEOUT_MINUTES", "10"))

    # Scoring
    SCORING_VERSION: str = "2.0"
    FREE_EMAIL_PROVIDERS: set[str] = {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "icloud.com",
        "live.com",
        "msn.com",
    }

    @classmethod
    def get_cors_origins(cls) -> list[str]:
        """Parse CORS_ORIGINS into a list."""
        if not cls.CORS_ORIGINS:
            return []  # No wildcard, same-origin only
        return [origin.strip() for origin in cls.CORS_ORIGINS.split(",") if origin.strip()]

    @classmethod
    def validate(cls) -> None:
        """Validate configuration values."""
        if cls.VALIDATOR_MODE not in ("real", "mock"):
            raise ValueError(f"VALIDATOR_MODE must be 'real' or 'mock', got '{cls.VALIDATOR_MODE}'")

        if cls.MAX_UPLOAD_MB < 1 or cls.MAX_UPLOAD_MB > 100:
            raise ValueError(f"MAX_UPLOAD_MB must be between 1 and 100, got {cls.MAX_UPLOAD_MB}")

        if cls.LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"LOG_LEVEL must be valid logging level, got '{cls.LOG_LEVEL}'")

        if cls.RETENTION_DAYS < 1 or cls.RETENTION_DAYS > 365:
            raise ValueError(f"RETENTION_DAYS must be between 1 and 365, got {cls.RETENTION_DAYS}")

        if cls.MAX_JOBS < 1 or cls.MAX_JOBS > 10000:
            raise ValueError(f"MAX_JOBS must be between 1 and 10000, got {cls.MAX_JOBS}")

        if cls.MAX_CONCURRENT_JOBS < 1 or cls.MAX_CONCURRENT_JOBS > 20:
            raise ValueError(
                f"MAX_CONCURRENT_JOBS must be between 1 and 20, got {cls.MAX_CONCURRENT_JOBS}"
            )

        if cls.JOB_STALL_TIMEOUT_MINUTES < 1 or cls.JOB_STALL_TIMEOUT_MINUTES > 60:
            raise ValueError(
                f"JOB_STALL_TIMEOUT_MINUTES must be between 1 and 60, "
                f"got {cls.JOB_STALL_TIMEOUT_MINUTES}"
            )


# Validate on import
Config.validate()
