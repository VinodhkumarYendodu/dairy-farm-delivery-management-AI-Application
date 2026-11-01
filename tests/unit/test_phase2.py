from datetime import date
from decimal import Decimal

import pytest

from core.config import Settings
from database.connection import build_connection_string
from database.migrate import MIGRATIONS_DIR, SAFE_DATABASE_NAME, _sql_batches
from database.repositories.master_data import _safe_audit_value
from schemas.master_data import CustomerCreate, ProductCreate
from services.master_data_service import MasterDataService


def test_localdb_is_default_and_braced_for_odbc() -> None:
    settings = Settings(_env_file=None)
    assert settings.db_server == r"(localdb)\MSSQLLocalDB"
    assert settings.db_driver == "ODBC Driver 17 for SQL Server"
    assert r"SERVER={(localdb)\MSSQLLocalDB}" in build_connection_string(settings)
    assert "Trusted_Connection=yes" in build_connection_string(settings)
    assert "Encrypt=" not in build_connection_string(settings)


def test_supplied_connection_string_is_used_with_app_database_selected() -> None:
    supplied = r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=(localdb)\MSSQLLocalDB;Trusted_Connection=yes;"
    value = build_connection_string(Settings(mssql_connection_string=supplied))
    assert value == supplied + "DATABASE=DairySubscriptionDB;"


def test_customer_schema_normalizes_contact_method_and_checks_email() -> None:
    customer = CustomerCreate(
        customer_code="C-1", full_name="Test Customer", mobile="1234567890",
        address="Sample address", preferred_contact_method="whatsapp", email="person@example.com",
    )
    assert customer.preferred_contact_method == "WHATSAPP"
    with pytest.raises(ValueError):
        CustomerCreate(customer_code="C-2", full_name="Bad", mobile="1234567890",
                       address="Sample address", email="not-an-email")


def test_initial_price_requires_effective_date() -> None:
    with pytest.raises(ValueError):
        ProductCreate(product_code="MILK", product_name="Milk", initial_price=Decimal("12.50"))
    product = ProductCreate(product_code="MILK", product_name="Milk", initial_price=Decimal("12.50"),
                            price_effective_from=date(2026, 11, 1))
    assert product.initial_price == Decimal("12.50")


def test_migration_batches_split_only_on_go_lines() -> None:
    sql = "SELECT 'GO';\nGO\nSELECT 2;\n"
    assert _sql_batches(sql) == ["SELECT 'GO';", "SELECT 2;"]


def test_database_name_is_safe_identifier() -> None:
    assert SAFE_DATABASE_NAME.fullmatch("DairySubscriptionDB")
    assert not SAFE_DATABASE_NAME.fullmatch("Dairy DB; DROP DATABASE x")


def test_product_price_and_date_must_be_paired() -> None:
    service = MasterDataService(repository=object())
    with pytest.raises(ValueError):
        service.create_product({"initial_price": Decimal("4.20"), "price_effective_from": None}, "tester")


def test_master_schema_includes_constraints_and_no_hard_delete_path() -> None:
    migration = (MIGRATIONS_DIR / "001_master_data.sql").read_text(encoding="utf-8")
    for expected in ("UQ_Customers_CustomerCode", "FK_Customers_DeliveryRoutes",
                     "CK_ProductPrices_Price", "UQ_ProductPrices_Product_EffectiveFrom",
                     "CREATE TABLE dbo.AuditLogs"):
        assert expected in migration


def test_audit_summary_omits_customer_contact_details() -> None:
    summary = _safe_audit_value({
        "id": 7, "customer_code": "C-7", "full_name": "Private Name",
        "mobile": "5551234567", "email": "private@example.com", "address": "Private address",
        "is_active": True,
    })
    assert summary == "id=7; customer_code=C-7; is_active=True"
    assert "private" not in summary

