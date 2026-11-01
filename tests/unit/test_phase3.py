from datetime import date
from decimal import Decimal

import pytest

from database.repositories.subscriptions import SubscriptionRepository
from schemas.subscriptions import AvailabilitySet, SubscriptionCreate
from services.subscription_engine import calculate_shortages, delivery_dates


def test_daily_schedule_includes_both_date_boundaries():
    assert delivery_dates(date(2026, 11, 1), date(2026, 11, 3), "DAILY") == [
        date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3),
    ]


def test_selected_day_schedule_uses_iso_weekday_and_inclusive_range():
    assert delivery_dates(date(2026, 11, 2), date(2026, 11, 8), "SELECTED_DAYS", [1, 3, 5]) == [
        date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 6),
    ]


def test_selected_day_schedule_rejects_empty_or_out_of_range_weekdays():
    with pytest.raises(ValueError):
        delivery_dates(date(2026, 11, 1), date(2026, 11, 7), "SELECTED_DAYS", [])
    with pytest.raises(ValueError):
        delivery_dates(date(2026, 11, 1), date(2026, 11, 7), "SELECTED_DAYS", [0])


def test_shortages_require_all_dates_and_account_for_existing_commitments():
    dates = [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    shortages = calculate_shortages(
        dates, Decimal("2.000"),
        {dates[0]: Decimal("10.000"), dates[1]: Decimal("2.000"), dates[2]: Decimal("5.000")},
        {dates[0]: Decimal("8.000"), dates[1]: Decimal("0.000"), dates[2]: Decimal("4.000")},
    )
    assert [row["date"] for row in shortages] == [dates[2]]
    assert [row["shortage"] for row in shortages] == [Decimal("1.000")]


def test_missing_availability_is_a_shortage():
    day = date(2026, 11, 1)
    shortages = calculate_shortages([day], Decimal("1.250"), {}, {})
    assert shortages == [{"date": day, "required": Decimal("1.250"), "available": Decimal("0"),
                          "committed": Decimal("0"), "shortage": Decimal("1.250")}]


def test_exact_remaining_stock_is_approvable():
    day = date(2026, 11, 1)
    assert calculate_shortages([day], Decimal("2"), {day: Decimal("5")}, {day: Decimal("3")}) == []


def test_shortage_includes_prior_overcommit_if_stock_was_changed_outside_the_app():
    day = date(2026, 11, 1)
    shortage = calculate_shortages([day], Decimal("2"), {day: Decimal("5")}, {day: Decimal("8")})
    assert shortage[0]["shortage"] == Decimal("5")


def test_subscription_schema_validates_frequency_weekdays_and_date_range():
    common = dict(customer_id=1, product_id=2, quantity_per_delivery="1.250",
                  start_date="2026-11-01", end_date="2026-11-07")
    assert SubscriptionCreate(**common, frequency="SELECTED_DAYS", selected_days=[1, 3]).selected_days == [1, 3]
    with pytest.raises(ValueError):
        SubscriptionCreate(**common, frequency="SELECTED_DAYS", selected_days=[])
    with pytest.raises(ValueError):
        SubscriptionCreate(**common, frequency="DAILY", selected_days=[1])
    with pytest.raises(ValueError):
        SubscriptionCreate(**{**common, "end_date": "2026-10-31"}, frequency="DAILY")


def test_availability_schema_accepts_decimal_precision():
    item = AvailabilitySet(availability_date="2026-11-01", product_id=1, available_quantity="12.375")
    assert item.available_quantity == Decimal("12.375")
    with pytest.raises(ValueError):
        AvailabilitySet(availability_date="2026-11-01", product_id=1, available_quantity="12.3456")


def test_phase3_migration_has_constraints_indexes_and_required_tables():
    from database.migrate import MIGRATIONS_DIR

    migration = (MIGRATIONS_DIR / "002_availability_subscriptions.sql").read_text(encoding="utf-8")
    for expected in (
        "CREATE TABLE dbo.DailyAvailability", "UQ_DailyAvailability_Date_Product",
        "CREATE TABLE dbo.Subscriptions", "CREATE TABLE dbo.SubscriptionDays",
        "CREATE TABLE dbo.SubscriptionStatusHistory", "IX_Subscriptions_Product_Status_Dates",
        "CK_SubscriptionDays_ISOWeekday", "DECIMAL(12,3)",
    ):
        assert expected in migration


def test_stock_mutations_use_serializable_transactions_and_key_locks():
    import inspect

    source = inspect.getsource(SubscriptionRepository)
    assert source.count("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE") >= 3
    assert "WITH (UPDLOCK,HOLDLOCK)" in source
