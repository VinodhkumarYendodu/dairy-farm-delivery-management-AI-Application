"""Phase 4 delivery planning request models."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class DeliveryGenerate(BaseModel):
    from_date: date
    through_date: date

    @model_validator(mode="after")
    def valid_range(self):
        if self.through_date < self.from_date:
            raise ValueError("through_date must be on or after from_date")
        return self


class DeliveryUpdate(BaseModel):
    status: str | None = None
    delivered_quantity: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    notes: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def has_update(self):
        if self.status is None and self.delivered_quantity is None and self.notes is None:
            raise ValueError("At least one delivery field must be supplied")
        if self.status is not None:
            self.status = self.status.upper()
            if self.status not in {"PLANNED", "OUT_FOR_DELIVERY", "DELIVERED", "MISSED", "CANCELLED"}:
                raise ValueError("Status must be PLANNED, OUT_FOR_DELIVERY, DELIVERED, MISSED, or CANCELLED")
        return self
