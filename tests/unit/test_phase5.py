from datetime import date
from decimal import Decimal
import inspect

import pytest

from database.repositories.billing import BillingRepository
from schemas.billing import AdjustmentCreate, PaymentCreate
from services.billing_service import calculate_charge_amount, calculate_ledger_totals, validate_payment_allocations


def test_charge_math_uses_decimal_and_rounds_half_up_to_currency():
    assert calculate_charge_amount(Decimal("1.250"), Decimal("43.21")) == Decimal("54.01")
    assert calculate_charge_amount(Decimal("1"), Decimal("1.005")) == Decimal("1.01")


def test_charge_math_rejects_non_positive_quantity_and_negative_price():
    with pytest.raises(ValueError):
        calculate_charge_amount(Decimal("0"), Decimal("10"))
    with pytest.raises(ValueError):
        calculate_charge_amount(Decimal("1"), Decimal("-1"))
    with pytest.raises(ValueError):
        calculate_charge_amount(Decimal("999999999.999"), Decimal("9999999999.99"))


def test_payment_schema_accepts_partial_allocations_and_normalizes_method():
    payment = PaymentCreate(
        customer_id=4, payment_date=date(2026, 11, 1), amount="100.00", payment_method="upi",
        allocations=[{"charge_id": 1, "amount": "40.00"}],
    )
    assert payment.payment_method == "UPI"
    assert payment.allocations[0].amount == Decimal("40.00")


def test_payment_schema_rejects_allocations_over_payment_and_duplicate_charges():
    base = dict(customer_id=4, payment_date="2026-11-01", amount="10.00", payment_method="CASH")
    with pytest.raises(ValueError):
        PaymentCreate(**base, allocations=[{"charge_id": 1, "amount": "10.01"}])
    with pytest.raises(ValueError):
        PaymentCreate(**base, allocations=[{"charge_id": 1, "amount": "2.00"},
                                           {"charge_id": 1, "amount": "3.00"}])


def test_payment_reference_is_trimmed_and_optional():
    payment = PaymentCreate(customer_id=1, payment_date="2026-11-01", amount="1.00",
                            payment_method="OTHER", reference="  bank-ref  ")
    assert payment.reference == "bank-ref"
    no_reference = PaymentCreate(customer_id=1, payment_date="2026-11-01", amount="1.00",
                                 payment_method="OTHER", reference="  ")
    assert no_reference.reference is None


def test_adjustment_requires_reason_and_supports_explicit_direction():
    entry = AdjustmentCreate(customer_id=3, adjustment_date="2026-11-01", entry_type="refund",
                             direction="credit", amount="25.00", reason="Returned product")
    assert entry.entry_type == "REFUND"
    assert entry.direction == "CREDIT"
    with pytest.raises(ValueError):
        AdjustmentCreate(customer_id=3, adjustment_date="2026-11-01", entry_type="refund",
                         direction="credit", amount="25.00", reason="  ")


def test_financial_migration_uses_decimal_unique_references_and_allocation_constraints():
    from database.migrate import MIGRATIONS_DIR

    migration = (MIGRATIONS_DIR / "004_billing_payments.sql").read_text(encoding="utf-8")
    for expected in (
        "CREATE TABLE dbo.CustomerCharges", "UQ_CustomerCharges_Delivery",
        "CREATE TABLE dbo.Payments", "UX_Payments_Reference", "WHERE Reference IS NOT NULL",
        "CREATE TABLE dbo.PaymentAllocations", "CK_PaymentAllocations_Amount",
        "CREATE TABLE dbo.CustomerAdjustments", "DECIMAL(14,2)",
    ):
        assert expected in migration


def test_financial_writes_are_serializable_and_manual_allocations_are_validated():
    source = inspect.getsource(BillingRepository)
    assert source.count("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE") >= 3
    assert "Allocation exceeds the remaining balance" in source
    assert "belongs to a different customer" in source
    assert "CHARGE_GENERATED" in source
    assert "PAYMENT_RECORDED" in source


def test_charge_generation_uses_delivered_quantity_and_snapshotted_price():
    source = inspect.getsource(BillingRepository.generate_charges)
    assert "d.Status='DELIVERED'" in source
    assert "COALESCE(d.DeliveredQuantity,d.PlannedQuantity)" in source
    assert "s.UnitPriceSnapshot" in source
    assert "calculate_charge_amount(quantity, price)" in source


def test_allocation_business_rule_rejects_duplicate_and_overpayment():
    with pytest.raises(ValueError):
        validate_payment_allocations(Decimal("5.00"), [{"charge_id": 1, "amount": Decimal("6.00")}])
    with pytest.raises(ValueError):
        validate_payment_allocations(Decimal("5.00"), [
            {"charge_id": 1, "amount": Decimal("2.00")}, {"charge_id": 1, "amount": Decimal("1.00")},
        ])


def test_ledger_totals_include_unallocated_payment_credit_without_auto_assignment():
    totals = calculate_ledger_totals(
        [{"amount": Decimal("100.00")}],
        [{"amount": Decimal("70.00"), "allocated_amount": Decimal("50.00")}],
        [{"amount": Decimal("5.00"), "direction": "DEBIT"},
         {"amount": Decimal("10.00"), "direction": "CREDIT"}],
    )
    assert totals == {
        "charges_total": Decimal("100.00"), "payments_total": Decimal("70.00"),
        "adjustments_net": Decimal("-5.00"), "outstanding_balance": Decimal("25.00"),
        "unallocated_payment_credit": Decimal("20.00"),
    }
