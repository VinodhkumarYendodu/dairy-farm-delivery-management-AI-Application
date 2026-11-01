"""Notification outbox and explicitly invoked workflow dispatch."""
from fastapi import APIRouter, HTTPException, Query

from schemas.notifications import ProcessNotifications, RetryNotification
from services.notification_service import NotificationService
from database.repositories.billing import BillingRepository
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class MonthlyStatementRequest(BaseModel):
    customer_id: int = Field(ge=1)
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


@router.get("/status")
def integration_status():
    try:
        return NotificationService().integration_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Notification status unavailable; apply migration 005") from exc


@router.get("")
def list_notifications(status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)):
    if status and status.upper() not in {"PENDING", "PROCESSING", "SENT", "FAILED", "REQUIRES_REVIEW", "SKIPPED"}:
        raise HTTPException(status_code=422, detail="Unsupported notification status")
    try:
        return NotificationService().list_notifications(status.upper() if status else None, limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Notification list unavailable; apply migration 005") from exc


@router.post("/process")
def process_notifications(item: ProcessNotifications):
    try:
        return NotificationService().process_pending(item.limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Notification processing failed") from exc


@router.post("/{notification_id}/retry")
def retry_notification(notification_id: int, item: RetryNotification):
    try:
        return NotificationService().retry(notification_id, item.confirm_possible_duplicate)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Notification retry failed") from exc


@router.post("/monthly-statement", status_code=201)
def queue_monthly_statement(item: MonthlyStatementRequest):
    try:
        notification_id = BillingRepository().enqueue_monthly_statement(item.customer_id, item.year, item.month)
        return {"id": notification_id, "status": "QUEUED"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not queue monthly statement") from exc
