"""FastAPI entry point for local health checks."""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import get_settings
from core.logging_config import configure_logging
from database.connection import check_sql_connection
from integrations.ollama_client import check_ollama
from api.v1.routes.master_data import router as master_data_router
from api.v1.routes.subscriptions import router as subscriptions_router
from api.v1.routes.deliveries import router as deliveries_router
from api.v1.routes.billing import router as billing_router
from api.v1.routes.ai import router as ai_router
from api.v1.routes.notifications import router as notifications_router
from api.v1.routes.documents import router as documents_router
from api.v1.routes.reports import router as reports_router
from api.v1.routes.auth import portal as customer_portal_router, router as auth_router
from api.v1.routes.customer import router as customer_router, staff_router as customer_issues_router
from api.auth_dependencies import require_staff

settings = get_settings()
configure_logging(settings.log_level, Path(settings.log_directory),
                  max_bytes=settings.log_max_bytes, backup_count=settings.log_backup_count)
app = FastAPI(title=settings.app_name, version="0.1.0")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="web-assets")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.include_router(auth_router)
app.include_router(customer_portal_router)
app.include_router(customer_router)
app.include_router(customer_issues_router)
staff_access = [Depends(require_staff)]
app.include_router(master_data_router, dependencies=staff_access)
app.include_router(subscriptions_router, dependencies=staff_access)
app.include_router(deliveries_router, dependencies=staff_access)
app.include_router(billing_router, dependencies=staff_access)
app.include_router(ai_router, dependencies=staff_access)
app.include_router(notifications_router, dependencies=staff_access)
app.include_router(documents_router, dependencies=staff_access)
app.include_router(reports_router, dependencies=staff_access)


@app.get("/api/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health", tags=["health"])
def health() -> dict[str, object]:
    dependencies = {
        "sql_server": check_sql_connection(settings),
        "ollama": check_ollama(
            settings.ollama_base_url,
            (settings.ollama_model, settings.ollama_embedding_model),
        ),
    }
    return {
        "status": "ok" if all(
            item.get("status") == "ok" for item in dependencies.values()
        ) else "degraded",
        "dependencies": dependencies,
    }

