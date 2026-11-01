"""SQL Server connection helpers using Windows Authentication by default."""

from collections.abc import Iterator
from contextlib import contextmanager
import logging

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def build_connection_string(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    if cfg.mssql_connection_string.strip():
        # Keep the supplied ODBC settings but force the configured database so
        # migrations and repositories never accidentally operate in master.
        parts = [
            part.strip()
            for part in cfg.mssql_connection_string.strip().strip(";").split(";")
            if part.strip() and part.split("=", 1)[0].strip().casefold() != "database"
        ]
        parts.append(f"DATABASE={cfg.db_database}")
        return ";".join(parts) + ";"

    fields = [
        f"DRIVER={{{cfg.db_driver}}}",
        f"SERVER={{{cfg.db_server}}}",
        f"DATABASE={cfg.db_database}",
    ]
    if cfg.db_encrypt:
        fields.append("Encrypt=yes")
    if cfg.db_trust_server_certificate:
        fields.append("TrustServerCertificate=yes")
    if cfg.db_trusted_connection:
        fields.append("Trusted_Connection=yes")
    return ";".join(fields) + ";"


@contextmanager
def sql_connection(settings: Settings | None = None, *, autocommit: bool = False) -> Iterator[object]:
    """Open a connection lazily; importing the app does not require pyodbc."""
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("pyodbc is not installed. Install Phase 1 requirements.") from exc

    connection = pyodbc.connect(build_connection_string(settings), timeout=3, autocommit=autocommit)
    try:
        yield connection
    finally:
        connection.close()


def check_sql_connection(settings: Settings | None = None) -> dict[str, object]:
    """Verify connectivity with the permitted, read-only SELECT 1 probe."""
    try:
        with sql_connection(settings) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            cursor.close()
        return {"status": "ok" if row and row[0] == 1 else "error", "detail": "SELECT 1"}
    except Exception as exc:  # dependency errors are reported without leaking connection details
        logger.warning("SQL Server health check failed (%s)", type(exc).__name__)
        return {"status": "unavailable", "detail": "SQL Server is unavailable; check the local connection and database configuration."}

