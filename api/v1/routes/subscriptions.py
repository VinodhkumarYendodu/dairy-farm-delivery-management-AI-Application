"""Phase 3 APIs for daily availability and confirmed subscription proposals."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth_dependencies import get_current_user
from database.repositories.subscriptions import SubscriptionRepository
from schemas.subscriptions import (
    AvailabilitySet, ConfirmationRequest, SubscriptionCancelRequest, SubscriptionCreate, SubscriptionStatusUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["availability and subscriptions"])


def _database_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "23000" in message or "2627" in message or "2601" in message:
        return HTTPException(status_code=409, detail="A conflicting record already exists")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=503, detail="Database operation failed")


def _repo() -> SubscriptionRepository:
    return SubscriptionRepository()


@router.get("/availability")
def list_availability(
    from_date: date = Query(default_factory=date.today),
    to_date: date = Query(default_factory=date.today),
    product_id: int | None = Query(default=None, ge=1),
):
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="to_date must be on or after from_date")
    try:
        return _repo().list_availability(from_date, to_date, product_id)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/availability", status_code=status.HTTP_200_OK)
def set_availability(item: AvailabilitySet, user: dict = Depends(get_current_user)):
    try:
        return _repo().set_availability(
            item.availability_date, item.product_id, item.available_quantity, user["username"]
        )
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/subscriptions")
def list_subscriptions(
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    customer_id: int | None = Query(default=None, ge=1),
):
    try:
        return _repo().list_subscriptions(status_filter, customer_id)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription(item: SubscriptionCreate, user: dict = Depends(get_current_user)):
    try:
        return _repo().create_subscription(item.model_dump(), user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/subscriptions/{subscription_id}/confirm")
def confirm_subscription(
    subscription_id: int, item: ConfirmationRequest, user: dict = Depends(get_current_user)
):
    try:
        return _repo().confirm_subscription(
            subscription_id, item.decision, item.reason, user["username"]
        )
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/subscriptions/{subscription_id}/approve")
def approve_subscription(
    subscription_id: int, item: SubscriptionStatusUpdate, user: dict = Depends(get_current_user)
):
    try:
        return _repo().approve_subscription(subscription_id, item.reason, user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(
    subscription_id: int, item: SubscriptionCancelRequest, user: dict = Depends(get_current_user)
):
    try:
        return _repo().cancel_subscription(subscription_id, item.reason, user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/subscriptions/{subscription_id}/history")
def subscription_status_history(subscription_id: int):
    try:
        rows = _repo().get_status_history(subscription_id)
        if not rows:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc
