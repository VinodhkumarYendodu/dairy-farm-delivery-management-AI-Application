"""Pure schedule and stock evaluation logic for Phase 3."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable


def delivery_dates(start_date: date, end_date: date, frequency: str, selected_days: Iterable[int] = ()) -> list[date]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if frequency not in {"DAILY", "SELECTED_DAYS"}:
        raise ValueError("frequency must be DAILY or SELECTED_DAYS")
    weekdays = set(selected_days)
    if frequency == "SELECTED_DAYS" and (not weekdays or not weekdays.issubset(set(range(1, 8)))):
        raise ValueError("SELECTED_DAYS requires ISO weekdays from 1 through 7")
    result = []
    current = start_date
    while current <= end_date:
        if frequency == "DAILY" or current.isoweekday() in weekdays:
            result.append(current)
        current += timedelta(days=1)
    return result


def calculate_shortages(
    dates: Iterable[date], quantity: Decimal,
    availability: dict[date, Decimal], committed: dict[date, Decimal],
) -> list[dict[str, date | Decimal]]:
    shortages = []
    for delivery_date in dates:
        available = availability.get(delivery_date)
        available = available if available is not None else Decimal("0")
        already_committed = committed.get(delivery_date, Decimal("0"))
        shortage = quantity + already_committed - available
        if shortage > 0:
            shortages.append({"date": delivery_date, "required": quantity, "available": available,
                              "committed": already_committed, "shortage": shortage})
    return shortages
