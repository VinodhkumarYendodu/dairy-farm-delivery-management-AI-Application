"""Phase 2 customer, product, pricing, and route API endpoints."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth_dependencies import get_current_user, require_admin
from database.repositories.master_data import MasterDataRepository
from schemas.master_data import (
    CustomerCreate, CustomerUpdate, PriceCreate, ProductActiveUpdate, ProductCreate, ProductUpdate, RouteCreate,
)
from services.master_data_service import MasterDataService

router = APIRouter(prefix="/api/v1", tags=["master data"])


def _repo() -> MasterDataRepository:
    return MasterDataRepository()


def _database_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if "23000" in message or "2627" in message or "2601" in message:
        return HTTPException(status_code=409, detail="A record with one of these unique values already exists")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=503, detail="Database operation failed")


@router.get("/customers")
def list_customers(search: str | None = Query(default=None, max_length=100), active: bool | None = None):
    try:
        return _repo().list_customers(search, active)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def create_customer(item: CustomerCreate, user: dict = Depends(get_current_user)):
    try:
        return _repo().create_customer(item.model_dump(), user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int):
    try:
        result = _repo().get_customer(customer_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, item: CustomerUpdate, user: dict = Depends(get_current_user)):
    try:
        updates = item.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=422, detail="At least one customer field must be supplied")
        result = _repo().update_customer(customer_id, updates, user["username"])
        if result is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/customers/{customer_id}/deactivate")
def deactivate_customer(customer_id: int, user: dict = Depends(get_current_user)):
    try:
        result = _repo().deactivate_customer(customer_id, user["username"])
        if result is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/products")
def list_products(active: bool | None = None):
    try:
        return _repo().list_products(active)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/products/{product_id}")
def get_product(product_id: int):
    try:
        result = _repo().get_product(product_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/products", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_product(item: ProductCreate, user: dict = Depends(get_current_user)):
    try:
        return MasterDataService().create_product(item.model_dump(), user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/products/{product_id}", dependencies=[Depends(require_admin)])
def update_product(product_id: int, item: ProductUpdate, user: dict = Depends(get_current_user)):
    try:
        updates = item.model_dump(exclude_unset=True, exclude_none=True)
        result = _repo().update_product(product_id, updates, user["username"])
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.patch("/products/{product_id}/status", dependencies=[Depends(require_admin)])
def set_product_status(product_id: int, item: ProductActiveUpdate, user: dict = Depends(get_current_user)):
    try:
        result = _repo().set_product_active(product_id, item.is_active, user["username"])
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/products/{product_id}/prices")
def list_product_prices(product_id: int):
    try:
        return _repo().list_prices(product_id)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/products/{product_id}/prices", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
def add_product_price(product_id: int, item: PriceCreate, user: dict = Depends(get_current_user)):
    try:
        return MasterDataService().add_price(
            product_id, item.price_per_unit, item.effective_from, user["username"]
        )
    except Exception as exc:
        raise _database_error(exc) from exc


@router.get("/routes")
def list_routes(active: bool | None = None):
    try:
        return _repo().list_routes(active)
    except Exception as exc:
        raise _database_error(exc) from exc


@router.post("/routes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_route(item: RouteCreate, user: dict = Depends(get_current_user)):
    try:
        return _repo().create_route(item.model_dump(), user["username"])
    except Exception as exc:
        raise _database_error(exc) from exc

