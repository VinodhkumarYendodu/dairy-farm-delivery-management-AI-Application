from datetime import date
from decimal import Decimal
import inspect

import pytest

from database.repositories.deliveries import DeliveryRepository
from database.repositories.subscriptions import SubscriptionRepository
from schemas.deliveries import DeliveryGenerate, DeliveryUpdate
from services.subscription_engine import delivery_dates


def test_generation_range_is_inclusive_and_respects_subscription_boundaries():
    assert delivery_dates(date(2026, 11, 2), date(2026, 11, 4), "DAILY") == [
        date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4),
    ]


def test_delivery_generation_request_requires_ordered_dates():
    assert DeliveryGenerate(from_date="2026-11-01", through_date="2026-11-02").through_date == date(2026, 11, 2)
    with pytest.raises(ValueError):
        DeliveryGenerate(from_date="2026-11-02", through_date="2026-11-01")


def test_delivery_update_validates_status_and_decimal_precision():
    update = DeliveryUpdate(status="delivered", delivered_quantity="1.250")
    assert update.status == "DELIVERED"
    assert update.delivered_quantity == Decimal("1.250")
    with pytest.raises(ValueError):
        DeliveryUpdate(status="UNKNOWN")
    with pytest.raises(ValueError):
        DeliveryUpdate(delivered_quantity="1.2345")


def test_delivery_migration_enforces_idempotency_and_route_customer_indexes():
    from database.migrate import MIGRATIONS_DIR

    migration = (MIGRATIONS_DIR / "003_deliveries.sql").read_text(encoding="utf-8")
    for expected in (
        "CREATE TABLE dbo.Deliveries", "UQ_Deliveries_Subscription_Date",
        "IX_Deliveries_Date_Route", "IX_Deliveries_Date_Customer",
        "FK_Deliveries_Customers", "FK_Deliveries_DeliveryRoutes",
        "CK_Deliveries_Status", "DeliveredQuantity DECIMAL(12,3)",
    ):
        assert expected in migration


def test_delivery_generation_uses_serializable_locking_and_duplicate_key_check():
    source = inspect.getsource(DeliveryRepository.generate)
    assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE" in source
    assert "WITH (UPDLOCK,HOLDLOCK)" in source
    assert "WHERE SubscriptionId=? AND DeliveryDate=?" in source


def test_subscription_cancellation_preserves_completed_records_and_audits_planned_cancellations():
    source = inspect.getsource(SubscriptionRepository.cancel_subscription)
    assert "Status='CANCELLED'" in source
    assert "Status='PLANNED'" in source
    assert "DELIVERY_CANCELLED_WITH_SUBSCRIPTION" in source
    assert '"CANCELLED"' in source


def test_delivery_corrections_require_reasons_for_terminal_status_changes():
    source = inspect.getsource(DeliveryRepository.update_delivery)
    assert '"DELIVERED", "MISSED", "CANCELLED"' in source
    assert "A reason is required when correcting a completed or cancelled delivery" in source
    assert "DELIVERY_CORRECTED" in source
