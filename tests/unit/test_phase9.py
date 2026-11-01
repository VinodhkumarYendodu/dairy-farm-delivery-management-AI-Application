from datetime import date
from decimal import Decimal

import pytest

from services.advanced_reporting_service import AdvancedReportingService


class Master:
    def list_products(self, active=None):
        return [{"id": 1, "product_code": "MILK", "product_name": "Milk", "unit_of_measure": "litre", "is_active": True}]

    def list_customers(self, search=None, active=None):
        return []


class Subs:
    def list_subscriptions(self, status=None, customer_id=None):
        return [{"id": 1, "product_id": 1, "start_date": date(2026, 10, 1), "end_date": date(2026, 11, 30),
                 "frequency": "SELECTED_DAYS", "selected_days": [6], "quantity_per_delivery": Decimal("2.500"),
                 "status": "APPROVED"}]

    def list_availability(self, start, end, product_id=None):
        return [{"product_id": 1, "availability_date": date(2026, 10, 31), "available_quantity": Decimal("2.000"),
                 "committed_quantity": Decimal("2.500"), "remaining_quantity": Decimal("-0.500")}]


class Deliveries:
    def list_deliveries(self, start, end, *, route_id=None, customer_id=None, status=None):
        return [
            {"route_name": "North", "product_name": "Milk", "unit_of_measure": "litre", "status": "DELIVERED",
             "delivered_quantity": Decimal("1.250"), "planned_quantity": Decimal("1.500")},
            {"route_name": "North", "product_name": "Milk", "unit_of_measure": "litre", "status": "MISSED",
             "delivered_quantity": None, "planned_quantity": Decimal("1.500")},
        ]


class Billing:
    def list_payments(self, customer_id=None, start=None, end=None):
        return [{"payment_date": date(2026, 10, 31), "payment_method": "UPI", "amount": Decimal("10.00")},
                {"payment_date": date(2026, 10, 31), "payment_method": "UPI", "amount": Decimal("5.00")}]


def service(**kwargs):
    return AdvancedReportingService(master=Master(), subscriptions=Subs(), deliveries=Deliveries(),
                                    billing=Billing(), today=date(2026, 10, 31), **kwargs)


def test_demand_report_respects_selected_weekday_and_date_overlap():
    result = service().report("demand", from_date=date(2026, 10, 31), through_date=date(2026, 11, 1))
    assert result["count"] == 1
    assert result["rows"][0]["delivery_date"] == date(2026, 10, 31)
    assert result["rows"][0]["required_quantity"] == Decimal("2.500")


def test_route_summary_groups_volume_and_delivery_outcomes():
    result = service().report("routes", from_date=date(2026, 10, 31), through_date=date(2026, 10, 31))
    assert result["rows"] == [{"route_name": "North", "product_name": "Milk", "unit": "litre",
        "delivery_count": 2, "delivered_count": 1, "missed_count": 1, "cancelled_count": 0,
        "delivered_quantity": Decimal("1.250")}]


def test_collections_roll_up_by_day_and_payment_method():
    result = service().report("collections", from_date=date(2026, 10, 1), through_date=date(2026, 10, 31))
    assert result["rows"] == [{"payment_date": date(2026, 10, 31), "payment_method": "UPI",
        "payment_count": 2, "collected_amount": Decimal("15.00")}]


def test_report_date_range_is_bounded_and_validated():
    with pytest.raises(ValueError, match="366 days"):
        service().report("sales", from_date=date(2025, 1, 1), through_date=date(2026, 10, 31))
    with pytest.raises(ValueError, match="on or after"):
        service().report("sales", from_date=date(2026, 11, 1), through_date=date(2026, 10, 31))


def test_dashboard_calculates_schedule_and_stock_without_custom_threshold(monkeypatch):
    from contextlib import contextmanager
    import services.advanced_reporting_service as reporting

    class Cursor:
        def execute(self, sql, *params):
            self.sql = sql
        def fetchone(self):
            sql = self.sql
            if "COUNT_BIG(*) FROM dbo.Customers" in sql: return (2,)
            if "COUNT_BIG(*) FROM dbo.Subscriptions" in sql: return (3,)
            if "COUNT_BIG(*) FROM dbo.CustomerCharges WHERE ChargeDate=?" in sql: return (1,)
            if "SUM(Amount),0) FROM dbo.CustomerCharges WHERE ChargeDate=?" in sql: return (Decimal("5.00"),)
            if "SUM(Amount),0) FROM dbo.CustomerCharges WHERE ChargeDate BETWEEN" in sql: return (Decimal("25.00"),)
            if "SUM(Amount),0) FROM dbo.Payments WHERE PaymentDate=?" in sql: return (Decimal("10.00"),)
            if "SUM(Amount),0) FROM dbo.Payments WHERE PaymentDate BETWEEN" in sql: return (Decimal("50.00"),)
            return (Decimal("15.00"),)
        def close(self): pass
    class Connection:
        def cursor(self): return Cursor()
    @contextmanager
    def fake_connection(): yield Connection()

    monkeypatch.setattr(reporting, "sql_connection", fake_connection)
    dash = AdvancedReportingService(master=Master(), subscriptions=Subs(), deliveries=Deliveries(),
                                   billing=Billing(), today=date(2026, 10, 31)).dashboard()
    assert dash["active_customers"] == 2
    assert dash["active_subscriptions"] == 1
    assert dash["today_demand_and_stock"][0]["required_quantity"] == Decimal("2.500")
    assert dash["depleted_stock"][0]["product_name"] == "Milk"
    assert dash["daily_sales"] == Decimal("5.00")
    assert dash["monthly_collections"] == Decimal("50.00")


def test_report_exports_csv_and_xlsx(monkeypatch):
    import io
    import zipfile
    from api.v1.routes import reports as route_module

    class FakeService:
        def report(self, name, **kwargs):
            return {"report": name, "count": 1, "rows": [{"amount": Decimal("123456789012.34"), "name": "Milk", "customer_value": "=HYPERLINK(\"https://bad\")"}]}
    monkeypatch.setattr(route_module, "_service", lambda: FakeService())
    filters = {"customer_id": None, "product_id": None, "route_id": None, "status": None,
               "active": None, "search": None}
    csv_response = route_module.report("sales", output="csv", **filters)
    assert b"123456789012.34" in csv_response.body
    assert b"'=HYPERLINK" in csv_response.body
    xlsx_response = route_module.report("sales", output="xlsx", **filters)
    with zipfile.ZipFile(io.BytesIO(xlsx_response.body)) as workbook:
        assert "xl/worksheets/sheet1.xml" in workbook.namelist()
        worksheet = workbook.read("xl/worksheets/sheet1.xml")
        assert b"'=HYPERLINK" in worksheet
