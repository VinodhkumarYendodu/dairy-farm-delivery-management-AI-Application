"""Strict AI intent and chat request schemas."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AiIntent = Literal[
    "active_subscriptions",
    "today_demand",
    "pending_confirmations",
    "outstanding_balances",
    "monthly_charges",
    "route_volume",
    "unsupported",
]


class IntentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: AiIntent
    product: str | None = Field(default=None, max_length=100)
    period: Literal["THIS_MONTH", "LAST_MONTH", "CUSTOM"] | None = None
    from_date: date | None = None
    through_date: date | None = None

    @model_validator(mode="after")
    def validate_parameters(self):
        if self.period == "CUSTOM":
            if self.from_date is None or self.through_date is None:
                raise ValueError("Custom periods require both from_date and through_date")
        elif self.from_date is not None or self.through_date is not None:
            raise ValueError("Dates are only accepted with period=CUSTOM")
        if self.period is not None and self.intent not in {"monthly_charges", "route_volume"}:
            raise ValueError("This intent does not accept a date period")
        if self.product is not None and self.intent != "today_demand":
            raise ValueError("Only today_demand accepts a product filter")
        if self.from_date and self.through_date:
            if self.through_date < self.from_date:
                raise ValueError("through_date must be on or after from_date")
            if (self.through_date - self.from_date).days > 366:
                raise ValueError("Custom date range cannot exceed 367 inclusive days")
        if self.intent == "unsupported" and any((self.product, self.period, self.from_date, self.through_date)):
            raise ValueError("Unsupported intent cannot contain parameters")
        return self


class AiChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def question_not_blank(self):
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("Question must not be blank")
        return self
