"""Phase 5 billing, payment allocation, and customer adjustment schemas."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChargeGeneration(BaseModel):
    from_date: date
    through_date: date

    @model_validator(mode="after")
    def valid_range(self):
        if self.through_date < self.from_date:
            raise ValueError("through_date must be on or after from_date")
        return self


class PaymentAllocation(BaseModel):
    charge_id: int = Field(ge=1)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class PaymentCreate(BaseModel):
    customer_id: int = Field(ge=1)
    payment_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: Literal["CASH", "BANK_TRANSFER", "UPI", "OTHER"]
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    allocations: list[PaymentAllocation] = Field(default_factory=list)

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_method(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None

    @model_validator(mode="after")
    def allocations_fit_payment(self):
        charge_ids = [row.charge_id for row in self.allocations]
        if len(charge_ids) != len(set(charge_ids)):
            raise ValueError("Each charge may appear only once in a payment")
        if sum((row.amount for row in self.allocations), Decimal("0")) > self.amount:
            raise ValueError("Payment allocations cannot exceed the payment amount")
        return self


class AdjustmentCreate(BaseModel):
    customer_id: int = Field(ge=1)
    adjustment_date: date
    entry_type: Literal["ADJUSTMENT", "REFUND"]
    direction: Literal["DEBIT", "CREDIT"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("entry_type", "direction", mode="before")
    @classmethod
    def normalize_enums(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reason is required")
        return value
