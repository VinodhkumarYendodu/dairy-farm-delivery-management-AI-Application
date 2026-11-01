"""Validated application settings loaded from environment and .env."""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dairy AI Subscription Management"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_timezone: str = "Asia/Kolkata"
    customer_change_cutoff_hour: int = Field(default=20, ge=0, le=23)

    db_server: str = r"(localdb)\MSSQLLocalDB"
    db_database: str = "DairySubscriptionDB"
    db_driver: str = "ODBC Driver 17 for SQL Server"
    db_trusted_connection: bool = True
    db_encrypt: bool = False
    db_trust_server_certificate: bool = False
    mssql_connection_string: str = ""

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "qwen3-embedding:0.6b"
    n8n_base_url: str = "http://127.0.0.1:5678"
    n8n_webhook_url: str = ""
    document_storage_path: str = "./data/documents"
    faiss_index_path: str = "./data/faiss_index"
    document_max_upload_mb: int = Field(default=10, ge=1, le=100)
    customer_issue_storage_path: str = "./data/customer_issues"
    customer_issue_max_photo_mb: int = Field(default=8, ge=1, le=25)
    backup_directory: str = "./backups"
    log_directory: str = "./logs"
    log_max_bytes: int = Field(default=2_000_000, ge=100_000, le=100_000_000)
    log_backup_count: int = Field(default=5, ge=1, le=20)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("app_host")
    @classmethod
    def keep_app_local(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost"}:
            raise ValueError("APP_HOST must bind to localhost during local development")
        return value

    @field_validator("ollama_base_url", "n8n_base_url", "n8n_webhook_url")
    @classmethod
    def keep_local_integrations(cls, value: str, info) -> str:
        if not value.strip() and info.field_name == "n8n_webhook_url":
            return ""
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(f"{info.field_name.upper()} must use a localhost URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"{info.field_name.upper()} cannot contain URL credentials, query, or fragment data")
        return value.strip().rstrip("/")

    @field_validator("db_database")
    @classmethod
    def simple_database_name(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", value):
            raise ValueError("DB_DATABASE must be a simple SQL Server database name")
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be a standard Python logging level")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

