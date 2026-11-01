"""SQL Server database bootstrap and idempotent migration runner."""

from __future__ import annotations

import re
from pathlib import Path

from core.config import Settings, get_settings
from database.connection import sql_connection

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
GO_SEPARATOR = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE | re.MULTILINE)
SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


def _sql_batches(script: str) -> list[str]:
    return [batch.strip() for batch in GO_SEPARATOR.split(script) if batch.strip()]


def create_database(settings: Settings | None = None) -> None:
    """Create only the configured project database, if it does not exist."""
    cfg = settings or get_settings()
    if not SAFE_DATABASE_NAME.fullmatch(cfg.db_database):
        raise ValueError("DB_DATABASE must be a simple SQL Server database identifier")
    master_settings = cfg.model_copy(update={"db_database": "master"})
    with sql_connection(master_settings, autocommit=True) as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"IF DB_ID(N'{cfg.db_database}') IS NULL CREATE DATABASE [{cfg.db_database}]"
        )
        cursor.close()


def apply_migrations(settings: Settings | None = None) -> list[str]:
    applied_now: list[str] = []
    with sql_connection(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "IF OBJECT_ID(N'dbo.SchemaMigrations', N'U') IS NULL "
            "CREATE TABLE dbo.SchemaMigrations (MigrationName NVARCHAR(260) NOT NULL PRIMARY KEY, "
            "AppliedAt DATETIME2(0) NOT NULL CONSTRAINT DF_SchemaMigrations_AppliedAt DEFAULT (SYSUTCDATETIME()))"
        )
        cursor.execute("SELECT MigrationName FROM dbo.SchemaMigrations")
        applied = {row[0] for row in cursor.fetchall()}
        cursor.close()

        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            if path.name in applied:
                continue
            batches = _sql_batches(path.read_text(encoding="utf-8"))
            cursor = connection.cursor()
            try:
                for batch in batches:
                    cursor.execute(batch)
                cursor.execute(
                    "INSERT INTO dbo.SchemaMigrations(MigrationName) VALUES (?)", path.name
                )
                connection.commit()
                applied_now.append(path.name)
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    return applied_now

