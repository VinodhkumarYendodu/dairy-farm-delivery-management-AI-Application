"""Validation and domain behavior for master data operations."""

from datetime import date
from decimal import Decimal
from typing import Any

from database.repositories.master_data import MasterDataRepository


class MasterDataService:
    def __init__(self, repository: MasterDataRepository | None = None):
        self.repository = repository or MasterDataRepository()

    def create_product(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        if (item.get("initial_price") is None) != (item.get("price_effective_from") is None):
            raise ValueError("Initial price and effective date must be supplied together")
        return self.repository.create_product(item, actor)

    def add_price(self, product_id: int, price: Decimal, effective_from: date, actor: str) -> dict[str, Any]:
        return self.repository.add_price(product_id, price, effective_from, actor)

