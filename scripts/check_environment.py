"""Report local prerequisites without printing credentials or downloading models."""

from __future__ import annotations

import importlib.util
import json
import argparse
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from database.connection import build_connection_string


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit with status 1 if required local settings or packages are missing")
    args = parser.parse_args()
    settings = get_settings()
    packages = ("fastapi", "uvicorn", "pydantic_settings", "pyodbc", "httpx", "pytest",
                "faiss", "pypdf", "pandas", "openpyxl")
    try:
        import pyodbc

        installed_odbc_drivers = pyodbc.drivers()
    except ImportError:
        installed_odbc_drivers = []
    package_status = {name: importlib.util.find_spec(name) is not None for name in packages}
    connection_has_credentials = any(
        token in build_connection_string(settings).lower()
        for token in ("password=", "pwd=")
    )
    n8n_env_path = Path(".env.n8n")
    n8n_key = ""
    if n8n_env_path.is_file():
        for line in n8n_env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("N8N_ENCRYPTION_KEY="):
                n8n_key = line.split("=", 1)[1].strip().strip('"\'')
                break
    encryption_key_configured = len(n8n_key) >= 32 and "replace-with" not in n8n_key.casefold()
    n8n_host = urlsplit(settings.n8n_base_url).hostname
    report = {
        "python": sys.version.split()[0],
        "packages": package_status,
        "application_env_file_exists": Path(".env").is_file(),
        "odbc_driver_configured": settings.db_driver,
        "odbc_driver_installed": settings.db_driver in installed_odbc_drivers,
        "installed_odbc_drivers": installed_odbc_drivers,
        "ollama_executable": shutil.which("ollama") is not None,
        "docker_executable": shutil.which("docker") is not None,
        "sql_connection_string_has_credentials": connection_has_credentials,
        "app_bind_is_local": settings.app_host in {"127.0.0.1", "localhost"},
        "n8n_base_url_is_local": n8n_host in {"localhost", "127.0.0.1", "::1"},
        "n8n_webhook_configured": bool(settings.n8n_webhook_url),
        "n8n_encryption_key_configured": encryption_key_configured,
        "backup_directory": settings.backup_directory,
        "log_directory": settings.log_directory,
        "ollama_models_are_not_downloaded_by_this_check": True,
    }
    print(json.dumps(report, indent=2))
    required = all(package_status.values()) and settings.db_driver in installed_odbc_drivers
    required = required and report["app_bind_is_local"] and report["n8n_base_url_is_local"]
    required = required and not connection_has_credentials
    return 1 if args.strict and not required else 0


if __name__ == "__main__":
    raise SystemExit(main())

