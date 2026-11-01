"""Sign-in, session management, admin account management, and customer portal APIs."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials

from api.auth_dependencies import bearer, get_current_user, require_admin, require_customer
from database.repositories.auth import AuthRepository
from database.repositories.deliveries import DeliveryRepository
from database.repositories.master_data import MasterDataRepository
from database.repositories.subscriptions import SubscriptionRepository
from schemas.auth import CustomerSignup, LoginRequest, PasswordChange, UserActiveUpdate, UserCreate
from schemas.subscriptions import ConfirmationRequest, CustomerDeliveryChange, CustomerScheduleCreate
from services.auth_service import AuthService, AuthenticationError
from services.billing_service import BillingService
from core.config import get_settings
from services.subscription_engine import delivery_dates

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
portal = APIRouter(prefix="/api/v1/customer-portal", tags=["customer portal"])


def _change_deadline(delivery_day: date) -> datetime:
    settings = get_settings()
    return datetime.combine(delivery_day - timedelta(days=1), time(settings.customer_change_cutoff_hour),
                            tzinfo=ZoneInfo(settings.app_timezone))


@portal.post("/signup", status_code=status.HTTP_201_CREATED)
def customer_signup(item: CustomerSignup):
    try:
        service = AuthService()
        service.register_customer(item.model_dump())
        return service.login(item.username, item.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Customer signup is unavailable; check database migrations and try again") from exc


@portal.get("/products")
def customer_products(_user: dict = Depends(require_customer)):
    try:
        return MasterDataRepository().list_products(active=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Product catalogue is unavailable") from exc


@portal.get("/policy")
def customer_schedule_policy(_user: dict = Depends(require_customer)):
    settings = get_settings()
    return {"timezone": settings.app_timezone, "cutoff_hour": settings.customer_change_cutoff_hour,
            "cutoff_text": f"Changes and cancellations are available until {settings.customer_change_cutoff_hour:02d}:00 on the day before delivery."}


@portal.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def customer_create_schedule(item: CustomerScheduleCreate, user: dict = Depends(require_customer)):
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    schedule_dates = delivery_dates(item.start_date, item.end_date, item.frequency, item.selected_days)
    if not schedule_dates or now >= _change_deadline(schedule_dates[0]):
        raise HTTPException(status_code=422, detail="Choose a delivery date that is still before its change cutoff")
    try:
        repo = SubscriptionRepository()
        return repo.create_subscription(
            {**item.model_dump(), "customer_id": user["customer_id"]}, user["username"],
            notify_confirmation=False, require_available=True,
        )
    except Exception as exc:
        if isinstance(exc, (ValueError, LookupError)):
            raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 404, detail=str(exc)) from exc
        raise HTTPException(status_code=503, detail="Could not save this delivery schedule") from exc


@portal.post("/subscriptions/{subscription_id}/cancel")
def customer_cancel_schedule(subscription_id: int, user: dict = Depends(require_customer)):
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.app_timezone))
    try:
        repo = SubscriptionRepository()
        schedule = next((row for row in repo.list_subscriptions(customer_id=user["customer_id"])
                         if row["id"] == subscription_id), None)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        if schedule["status"] in {"CANCELLED", "DECLINED"}:
            raise HTTPException(status_code=409, detail="This schedule is already closed")
        candidates = delivery_dates(max(schedule["start_date"], now.date()), schedule["end_date"],
                                   schedule["frequency"], schedule.get("selected_days", []))
        effective_from = next((day for day in candidates if now < _change_deadline(day)), None)
        if effective_from is None:
            raise HTTPException(status_code=422, detail="No upcoming delivery is currently outside the change cutoff")
        return repo.cancel_subscription(subscription_id, "Cancelled by customer", user["username"], effective_from)
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not cancel this schedule") from exc


def _customer_schedule_rows(customer_id: int) -> list[dict]:
    now = datetime.now(ZoneInfo(get_settings().app_timezone))
    rows = SubscriptionRepository().list_subscriptions(customer_id=customer_id)
    for row in rows:
        dates = delivery_dates(max(row["start_date"], now.date()), row["end_date"],
                               row["frequency"], row.get("selected_days", []))
        deadline = _change_deadline(dates[0]) if dates else None
        row["customer_change_allowed"] = bool(
            deadline and now < deadline and row["status"] not in {"CANCELLED", "DECLINED"}
        )
        row["change_deadline"] = deadline
    return rows


@router.post("/login")
def login(item: LoginRequest):
    try:
        return AuthService().login(item.username, item.password)
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid username or password",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Sign-in service is unavailable") from exc


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer),
           _user: dict = Depends(get_current_user)):
    AuthRepository().revoke_session(AuthService.token_hash(credentials.credentials))
    return None


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(item: PasswordChange, user: dict = Depends(get_current_user)):
    try:
        AuthService().change_password(user["id"], item.current_password, item.new_password)
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Current password is incorrect") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not change password") from exc
    return None


@router.get("/users")
def list_users(_admin: dict = Depends(require_admin)):
    try:
        return AuthRepository().list_users()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="User directory is unavailable") from exc


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(item: UserCreate, _admin: dict = Depends(require_admin)):
    if (item.role == "CUSTOMER") != (item.customer_id is not None):
        raise HTTPException(status_code=422, detail="Customer accounts require customer_id; agent accounts must omit it")
    if item.customer_id is not None:
        try:
            customer = MasterDataRepository().get_customer(item.customer_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Customer directory is unavailable") from exc
        if not customer or not customer["is_active"]:
            raise HTTPException(status_code=422, detail="An active customer record is required for this account")
    try:
        return AuthService().create_user(item.username, item.password, item.role, item.customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not create user account") from exc


@router.patch("/users/{user_id}/active")
def set_user_active(user_id: int, item: UserActiveUpdate, admin: dict = Depends(require_admin)):
    if user_id == admin["id"] and not item.is_active:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own administrator account")
    try:
        if not AuthRepository().set_user_active(user_id, item.is_active):
            raise HTTPException(status_code=404, detail="User account not found")
        return {"id": user_id, "is_active": item.is_active}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not update user account") from exc


@portal.get("/profile")
def customer_profile(user: dict = Depends(require_customer)):
    try:
        customer = MasterDataRepository().get_customer(user["customer_id"])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Customer profile is unavailable") from exc
    if not customer or not customer["is_active"]:
        raise HTTPException(status_code=404, detail="Customer profile is unavailable")
    return customer


@portal.get("/subscriptions")
def customer_subscriptions(user: dict = Depends(require_customer)):
    try:
        return _customer_schedule_rows(user["customer_id"])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Subscription list is unavailable") from exc


@portal.post("/subscriptions/{subscription_id}/confirm")
def customer_confirm_subscription(
    subscription_id: int, item: ConfirmationRequest, user: dict = Depends(require_customer)
):
    try:
        return SubscriptionRepository().confirm_subscription(
            subscription_id, item.decision, item.reason, user["username"], user["customer_id"]
        )
    except LookupError as exc:
        # Do not reveal whether another customer's subscription exists.
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not confirm this schedule") from exc


@portal.get("/deliveries")
def customer_deliveries(
    from_date: date = Query(default_factory=lambda: date.today() - timedelta(days=30)),
    through_date: date = Query(default_factory=lambda: date.today() + timedelta(days=30)),
    user: dict = Depends(require_customer),
):
    if (through_date - from_date).days > 365 or through_date < from_date:
        raise HTTPException(status_code=422, detail="Date range must be valid and no longer than 366 days")
    try:
        rows = DeliveryRepository().list_deliveries(from_date, through_date, customer_id=user["customer_id"])
        now = datetime.now(ZoneInfo(get_settings().app_timezone))
        for row in rows:
            deadline = _change_deadline(row["delivery_date"])
            row["customer_change_allowed"] = row["status"] == "PLANNED" and now < deadline
            row["change_deadline"] = deadline
        return rows
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Delivery list is unavailable") from exc


@portal.patch("/deliveries/{delivery_id}")
def customer_change_delivery(delivery_id: int, item: CustomerDeliveryChange, user: dict = Depends(require_customer)):
    try:
        return DeliveryRepository().change_customer_delivery(
            delivery_id, user["customer_id"], item.planned_quantity, item.cancel, user["username"]
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not change this delivery") from exc


@portal.get("/ledger")
def customer_ledger(user: dict = Depends(require_customer)):
    try:
        result = BillingService().customer_ledger(user["customer_id"])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Customer ledger is unavailable") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Customer ledger is unavailable")
    return result
