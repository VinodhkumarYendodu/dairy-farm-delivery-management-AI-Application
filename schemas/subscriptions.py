"""Phase 3 availability and subscription request models."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AvailabilitySet(BaseModel):
    availability_date: date
    product_id: int = Field(ge=1)
    available_quantity: Decimal = Field(ge=0, max_digits=12, decimal_places=3)


class SubscriptionCreate(BaseModel):
    customer_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    quantity_per_delivery: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    frequency: Literal["DAILY", "SELECTED_DAYS"]
    start_date: date
    end_date: date
    selected_days: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("A subscription schedule cannot exceed 367 calendar days")
        if self.frequency == "SELECTED_DAYS":
            if not self.selected_days or any(day not in range(1, 8) for day in self.selected_days):
                raise ValueError("SELECTED_DAYS requires ISO weekdays from 1 (Monday) through 7 (Sunday)")
            if len(set(self.selected_days)) != len(self.selected_days):
                raise ValueError("selected_days must not contain duplicates")
        elif self.selected_days:
            raise ValueError("selected_days must be empty for DAILY subscriptions")
        return self


class CustomerScheduleCreate(BaseModel):
    product_id: int = Field(ge=1)
    quantity_per_delivery: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    frequency: Literal["DAILY", "SELECTED_DAYS"] = "DAILY"
    start_date: date
    end_date: date
    selected_days: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("A customer schedule cannot exceed 367 calendar days")
        if self.frequency == "SELECTED_DAYS":
            if not self.selected_days or any(day not in range(1, 8) for day in self.selected_days):
                raise ValueError("SELECTED_DAYS requires weekdays from 1 (Monday) through 7 (Sunday)")
            if len(set(self.selected_days)) != len(self.selected_days):
                raise ValueError("selected_days must not contain duplicates")
        elif self.selected_days:
            raise ValueError("selected_days must be empty for DAILY schedules")
        return self


class CustomerScheduleDraft(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    quantity_per_delivery: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    frequency: Literal["DAILY", "SELECTED_DAYS"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    selected_days: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


class CustomerDeliveryChange(BaseModel):
    planned_quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    cancel: bool = False

    @model_validator(mode="after")
    def one_change(self):
        if self.cancel == (self.planned_quantity is not None):
            raise ValueError("Choose either a new quantity or cancel=true")
        return self


class ConfirmationRequest(BaseModel):
    decision: Literal["CONFIRMED", "DECLINED"]
    reason: str | None = Field(default=None, max_length=1000)


class SubscriptionStatusUpdate(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class SubscriptionCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A cancellation reason is required")
        return value
