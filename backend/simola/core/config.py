"""Typed runtime settings, read from SIMOLA_* environment variables (fail fast)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMOLA_", env_file=None, extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    version: str = "dev"
    log_level: str = "INFO"

    # postgresql+asyncpg://user:pass@host:5432/db
    database_url: str

    # CDP log share mount points and probe addresses, keyed by CDP code.
    # Deployment configuration only - never stored in the repository (NFR-SEC-010).
    cdp_paths: dict[str, str] = Field(default_factory=dict)
    cdp_addresses: dict[str, str] = Field(default_factory=dict)

    # Ingestion (FR-ING-001/006)
    ingest_interval_s: int = 60
    rescan_previous_day_hours: int = 2
    future_tolerance_s: int = 120
    file_io_timeout_s: float = 20.0

    # Network probes (FR-ING-007)
    probe_interval_s: int = 15
    probe_timeout_s: float = 3.0
    probe_ports: list[int] = Field(default_factory=lambda: [445])

    # Backups (NFR-BAK-004): only raise "backup overdue" problems where backups are expected
    backup_expected: bool = False

    # Migrate step only: least-privilege application role to create/update (PRD DB-06)
    app_db_user: str | None = None
    app_db_password: str | None = None

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("SIMOLA_DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return v

    @property
    def asyncpg_dsn(self) -> str:
        """Plain DSN for direct asyncpg connections (migrations, locks)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
