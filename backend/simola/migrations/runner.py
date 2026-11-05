"""Plain-SQL migration runner (PRD DB-04, decision OPEN-05).

- Files in ``sql/`` are applied in filename order and recorded in ``schema_migration``.
- Applied files are immutable: their SHA-256 checksum is stored and verified on every run.
- A PostgreSQL advisory lock prevents concurrent runs (e.g. overlapping deploys).
- Each file runs in its own transaction unless its first line is ``-- simola:no-transaction``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parent / "sql"
LOCK_KEY = 7_316_652_001  # arbitrary, stable advisory-lock key for SIMOLA migrations
NO_TX_MARKER = "-- simola:no-transaction"


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str

    @property
    def transactional(self) -> bool:
        return not self.sql.lstrip().startswith(NO_TX_MARKER)


def discover(sql_dir: Path = SQL_DIR) -> list[Migration]:
    out = []
    for path in sorted(sql_dir.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        out.append(Migration(path.stem, path, text, hashlib.sha256(text.encode()).hexdigest()))
    versions = [m.version for m in out]
    if len(versions) != len(set(versions)):
        raise MigrationError("duplicate migration versions")
    return out


async def migrate(dsn: str, sql_dir: Path = SQL_DIR) -> list[str]:
    """Apply pending migrations; return the versions applied in this run."""
    conn = await asyncpg.connect(
        dsn, server_settings={"TimeZone": "UTC", "application_name": "simola-migrate"}
    )
    applied_now: list[str] = []
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version     text PRIMARY KEY,
                checksum    text NOT NULL,
                applied_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        rows = await conn.fetch("SELECT version, checksum FROM schema_migration")
        applied = {r["version"]: r["checksum"] for r in rows}
        migrations = discover(sql_dir)
        known = {m.version for m in migrations}
        unknown = sorted(set(applied) - known)
        if unknown:
            raise MigrationError(f"database has migrations unknown to this release: {unknown}")
        for m in migrations:
            if m.version in applied:
                if applied[m.version] != m.checksum:
                    raise MigrationError(
                        f"checksum mismatch for applied migration {m.version}: files are immutable"
                    )
                continue
            logger.info("applying migration", extra={"version": m.version})
            if m.transactional:
                async with conn.transaction():
                    await conn.execute(m.sql)
                    await conn.execute(
                        "INSERT INTO schema_migration (version, checksum) VALUES ($1, $2)",
                        m.version,
                        m.checksum,
                    )
            else:
                await conn.execute(m.sql)
                await conn.execute(
                    "INSERT INTO schema_migration (version, checksum) VALUES ($1, $2)", m.version, m.checksum
                )
            applied_now.append(m.version)
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
        finally:
            await conn.close()
    return applied_now


async def ensure_app_role(dsn: str, user: str, password: str) -> None:
    """Least-privilege application role (PRD DB-06): DML only, no DDL. Run by the migrate step as owner."""
    conn = await asyncpg.connect(dsn, server_settings={"application_name": "simola-migrate"})
    try:
        ident, literal = await conn.fetchrow("SELECT quote_ident($1), quote_literal($2)", user, password)
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", user)
        verb = "ALTER" if exists else "CREATE"
        await conn.execute(
            f"{verb} ROLE {ident} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {literal}"
        )
        db = await conn.fetchval("SELECT quote_ident(current_database())")
        await conn.execute(f"GRANT CONNECT ON DATABASE {db} TO {ident}")
        await conn.execute(f"GRANT USAGE ON SCHEMA public TO {ident}")
        await conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ident}")
        await conn.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ident}")
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ident}"
        )
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ident}"
        )
        # The audit log is append-only (FR-AUD-001): the application may add entries, never change them.
        if await conn.fetchval("SELECT to_regclass('audit_event') IS NOT NULL"):
            await conn.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM {ident}")
    finally:
        await conn.close()


async def pending(dsn: str, sql_dir: Path = SQL_DIR) -> list[str]:
    """Versions not yet applied (used by /ready)."""
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval("SELECT to_regclass('schema_migration') IS NOT NULL")
        applied = set()
        if exists:
            applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migration")}
        return [m.version for m in discover(sql_dir) if m.version not in applied]
    finally:
        await conn.close()
