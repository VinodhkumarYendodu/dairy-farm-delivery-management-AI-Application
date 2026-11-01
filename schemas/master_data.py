"""Pydantic schemas for Phase 2 master data."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class CustomerCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=30)
    full_name: str = Field(min_length=1, max_length=160)
    mobile: str = Field(min_length=3, max_length=30)
    email: EmailStr | None = None
    address: str = Field(min_length=1, max_length=500)
    area: str | None = Field(default=None, max_length=100)
    route_id: int | None = Field(default=None, ge=1)
    preferred_contact_method: str = "PHONE"
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("preferred_contact_method")
    @classmethod
    def contact_method_allowed(cls, value: str) -> str:
        value = value.upper()
        if value not in {"PHONE", "EMAIL", "WHATSAPP", "SMS"}:
            raise ValueError("Use PHONE, EMAIL, WHATSAPP, or SMS")
        return value


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    mobile: str | None = Field(default=None, min_length=3, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)
    area: str | None = Field(default=None, max_length=100)
    route_id: int | None = Field(default=None, ge=1)
    preferred_contact_method: str | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("preferred_contact_method")
    @classmethod
    def contact_method_allowed(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.upper()
        if value not in {"PHONE", "EMAIL", "WHATSAPP", "SMS"}:
            raise ValueError("Use PHONE, EMAIL, WHATSAPP, or SMS")
        return value


class ProductCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=30)
    product_name: str = Field(min_length=1, max_length=100)
    unit_of_measure: str = Field(default="litre", min_length=1, max_length=20)
    initial_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    price_effective_from: date | None = None

    @model_validator(mode="after")
    def price_date_required_with_price(self):
        if (self.initial_price is None) != (self.price_effective_from is None):
            raise ValueError("initial_price and price_effective_from must be supplied together")
        return self


class ProductUpdate(BaseModel):
    product_code: str | None = Field(default=None, min_length=1, max_length=30)
    product_name: str | None = Field(default=None, min_length=1, max_length=100)
    unit_of_measure: str | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("product_code", "product_name", "unit_of_measure")
    @classmethod
    def product_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Product fields cannot be blank")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one product field to update")
        return self


class ProductActiveUpdate(BaseModel):
    is_active: bool


class PriceCreate(BaseModel):
    price_per_unit: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    effective_from: date


class RouteCreate(BaseModel):
    route_name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class MasterDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


