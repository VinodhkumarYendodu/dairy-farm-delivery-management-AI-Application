"""Phase 5 charges, manual payments, allocations, and customer ledger APIs."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from api.auth_dependencies import get_current_user
from schemas.billing import AdjustmentCreate, ChargeGeneration, PaymentCreate
from services.billing_service import BillingService

router = APIRouter(prefix="/api/v1", tags=["billing and payments"])


def _error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "23000" in message or "2627" in message or "2601" in message:
        return HTTPException(status_code=409, detail="A duplicate or conflicting financial record was rejected")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=503, detail="Database operation failed")


def _service() -> BillingService:
    return BillingService()


def _financial_json(value):
    """Serialize decimal money and quantities as exact strings in API responses."""
    return jsonable_encoder(value, custom_encoder={Decimal: lambda amount: format(amount, "f")})


@router.post("/charges/generate")
def generate_charges(item: ChargeGeneration, user: dict = Depends(get_current_user)):
    try:
        return _financial_json(_service().generate_charges(item.from_date, item.through_date, user["username"]))
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/charges")
def list_charges(
    customer_id: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    through_date: date | None = None,
    open_only: bool = False,
):
    if from_date and through_date and through_date < from_date:
        raise HTTPException(status_code=422, detail="through_date must be on or after from_date")
    try:
        return _financial_json(_service().list_charges(customer_id, from_date, through_date, open_only))
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/payments", status_code=status.HTTP_201_CREATED)
def record_payment(item: PaymentCreate, user: dict = Depends(get_current_user)):
    try:
        return _financial_json(_service().record_payment(item.model_dump(), user["username"]))
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/payments")
def list_payments(
    customer_id: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    through_date: date | None = None,
):
    if from_date and through_date and through_date < from_date:
        raise HTTPException(status_code=422, detail="through_date must be on or after from_date")
    try:
        return _financial_json(_service().list_payments(customer_id, from_date, through_date))
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/adjustments", status_code=status.HTTP_201_CREATED)
def create_adjustment(item: AdjustmentCreate, user: dict = Depends(get_current_user)):
    try:
        return _financial_json(_service().create_adjustment(item.model_dump(), user["username"]))
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(customer_id: int):
    try:
        result = _service().customer_ledger(customer_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        return _financial_json(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc
