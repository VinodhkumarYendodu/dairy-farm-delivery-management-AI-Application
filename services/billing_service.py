"""Decimal-safe billing calculations."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")


def calculate_charge_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    if quantity <= 0:
        raise ValueError("Charge quantity must be greater than zero")
    if unit_price < 0:
        raise ValueError("Unit price cannot be negative")
    amount = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount > Decimal("999999999999.99"):
        raise ValueError("Charge amount exceeds the supported DECIMAL(14,2) range")
    return amount


def validate_payment_allocations(amount: Decimal, allocations: list[dict[str, Any]]) -> None:
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    charge_ids = [row["charge_id"] for row in allocations]
    if len(charge_ids) != len(set(charge_ids)):
        raise ValueError("Each charge may appear only once in a payment")
    total = sum((row["amount"] for row in allocations), Decimal("0.00"))
    if total > amount:
        raise ValueError("Payment allocations cannot exceed the payment amount")


def calculate_ledger_totals(
    charges: list[dict[str, Any]], payments: list[dict[str, Any]], adjustments: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Calculate the aggregate account balance without assigning unallocated cash to charges."""
    charges_total = sum((row["amount"] for row in charges), Decimal("0.00"))
    payments_total = sum((row["amount"] for row in payments), Decimal("0.00"))
    adjustments_net = sum(
        (row["amount"] if row["direction"] == "DEBIT" else -row["amount"] for row in adjustments),
        Decimal("0.00"),
    )
    unallocated_credit = sum(
        (row["amount"] - row["allocated_amount"] for row in payments), Decimal("0.00")
    )
    return {
        "charges_total": charges_total,
        "payments_total": payments_total,
        "adjustments_net": adjustments_net,
        "outstanding_balance": charges_total + adjustments_net - payments_total,
        "unallocated_payment_credit": unallocated_credit,
    }


class BillingService:
    """Application service for Phase 5 operations; repositories own SQL transactions."""

    def __init__(self, repository=None):
        if repository is None:
            from database.repositories.billing import BillingRepository

            repository = BillingRepository()
        self.repository = repository

    def generate_charges(self, start: date, end: date, actor: str):
        if end < start:
            raise ValueError("through_date must be on or after from_date")
        return self.repository.generate_charges(start, end, actor)

    def list_charges(self, customer_id=None, start=None, end=None, open_only=False):
        if start and end and end < start:
            raise ValueError("through_date must be on or after from_date")
        return self.repository.list_charges(customer_id, start, end, open_only)

    def record_payment(self, item: dict[str, Any], actor: str):
        validate_payment_allocations(item["amount"], item.get("allocations", []))
        return self.repository.record_payment(item, actor)

    def list_payments(self, customer_id=None, start=None, end=None):
        if start and end and end < start:
            raise ValueError("through_date must be on or after from_date")
        return self.repository.list_payments(customer_id, start, end)

    def create_adjustment(self, item: dict[str, Any], actor: str):
        if item["amount"] <= 0:
            raise ValueError("Adjustment amount must be greater than zero")
        if not item["reason"].strip():
            raise ValueError("A reason is required")
        return self.repository.create_adjustment(item, actor)

    def customer_ledger(self, customer_id: int):
        return self.repository.customer_ledger(customer_id)
