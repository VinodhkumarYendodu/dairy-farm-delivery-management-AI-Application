"""Phase 4 delivery generation, listing, and status APIs."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth_dependencies import get_current_user
from database.repositories.deliveries import DeliveryRepository
from schemas.deliveries import DeliveryGenerate, DeliveryUpdate

router = APIRouter(prefix="/api/v1", tags=["deliveries"])


def _error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "23000" in message or "2627" in message or "2601" in message:
        return HTTPException(status_code=409, detail="A conflicting record already exists")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=503, detail="Database operation failed")


def _repo() -> DeliveryRepository:
    return DeliveryRepository()


@router.post("/deliveries/generate", status_code=status.HTTP_200_OK)
def generate_deliveries(item: DeliveryGenerate, user: dict = Depends(get_current_user)):
    try:
        return _repo().generate(item.from_date, item.through_date, user["username"])
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/deliveries")
def list_deliveries(
    from_date: date = Query(default_factory=date.today),
    through_date: date = Query(default_factory=date.today),
    route_id: int | None = Query(default=None, ge=1),
    customer_id: int | None = Query(default=None, ge=1),
    status_filter: Literal["PLANNED", "OUT_FOR_DELIVERY", "DELIVERED", "MISSED", "CANCELLED"] | None = Query(
        default=None, alias="status"
    ),
):
    if through_date < from_date:
        raise HTTPException(status_code=422, detail="through_date must be on or after from_date")
    try:
        return _repo().list_deliveries(
            from_date, through_date, route_id=route_id, customer_id=customer_id, status=status_filter
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.patch("/deliveries/{delivery_id}")
def update_delivery(
    delivery_id: int, item: DeliveryUpdate, user: dict = Depends(get_current_user)
):
    try:
        result = _repo().update_delivery(
            delivery_id, status=item.status, delivered_quantity=item.delivered_quantity,
            notes=item.notes, reason=item.reason, actor=user["username"],
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Delivery not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc


@router.patch("/deliveries")
def update_delivery_by_query(
    item: DeliveryUpdate,
    delivery_id: int = Query(ge=1),
    user: dict = Depends(get_current_user),
):
    """PATCH form matching the blueprint's collection endpoint with an ID query parameter."""
    return update_delivery(delivery_id, item, user)
