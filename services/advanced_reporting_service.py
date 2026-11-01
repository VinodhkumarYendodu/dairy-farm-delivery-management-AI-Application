"""Operational dashboard and filterable read-only reports."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from core.config import get_settings
from database.connection import sql_connection
from database.repositories.billing import BillingRepository
from database.repositories.deliveries import DeliveryRepository
from database.repositories.master_data import MasterDataRepository
from database.repositories.notifications import NotificationRepository
from database.repositories.subscriptions import SubscriptionRepository
from services.subscription_engine import delivery_dates


class AdvancedReportingService:
    REPORTS = {"availability", "demand", "sales", "collections", "routes", "customers",
               "subscriptions", "deliveries", "ledger", "outstanding", "payments", "notifications"}

    def __init__(self, *, master=None, subscriptions=None, deliveries=None, billing=None,
                 notifications=None, today: date | None = None):
        self.master = master or MasterDataRepository()
        self.subscriptions = subscriptions or SubscriptionRepository()
        self.deliveries = deliveries or DeliveryRepository()
        self.billing = billing or BillingRepository()
        self.notifications = notifications or NotificationRepository()
        self.today = today or datetime.now(ZoneInfo(get_settings().app_timezone)).date()

    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _outstanding_total(self) -> Decimal:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COALESCE((SELECT SUM(Amount) FROM dbo.CustomerCharges),0) "
                "+ COALESCE((SELECT SUM(CASE WHEN Direction='DEBIT' THEN Amount ELSE -Amount END) FROM dbo.CustomerAdjustments),0) "
                "- COALESCE((SELECT SUM(Amount) FROM dbo.Payments),0)"
            )
            value = cursor.fetchone()[0]
            cursor.close()
        return value or Decimal("0.00")

    def _balance_rows(self) -> list[dict[str, Any]]:
        query = (
            "SELECT c.CustomerId AS customer_id,c.CustomerCode AS customer_code,c.FullName AS customer_name,"
            "COALESCE(ch.total,0) AS charges_total,COALESCE(adj.total,0) AS adjustments_net,"
            "COALESCE(pay.total,0) AS payments_total,"
            "COALESCE(ch.total,0)+COALESCE(adj.total,0)-COALESCE(pay.total,0) AS outstanding_balance "
            "FROM dbo.Customers c "
            "OUTER APPLY (SELECT SUM(Amount) AS total FROM dbo.CustomerCharges WHERE CustomerId=c.CustomerId) ch "
            "OUTER APPLY (SELECT SUM(CASE WHEN Direction='DEBIT' THEN Amount ELSE -Amount END) AS total FROM dbo.CustomerAdjustments WHERE CustomerId=c.CustomerId) adj "
            "OUTER APPLY (SELECT SUM(Amount) AS total FROM dbo.Payments WHERE CustomerId=c.CustomerId) pay "
            "ORDER BY outstanding_balance DESC,c.FullName"
        )
        with sql_connection() as connection:
            cursor = connection.cursor(); cursor.execute(query); rows = self._rows(cursor); cursor.close()
            return rows

    def dashboard(self, as_of: date | None = None) -> dict[str, Any]:
        day = as_of or self.today
        month_start = day.replace(day=1)
        subscriptions = self.subscriptions.list_subscriptions(status="APPROVED")
        active = [s for s in subscriptions if s["start_date"] <= day <= s["end_date"]]
        products = self.master.list_products()
        product_map = {p["id"]: p for p in products}
        demand: dict[int, Decimal] = defaultdict(lambda: Decimal("0.000"))
        for row in active:
            if row["frequency"] == "DAILY" or day.isoweekday() in row.get("selected_days", []):
                demand[row["product_id"]] += row["quantity_per_delivery"]
        stock_rows = self.subscriptions.list_availability(day, day)
        stock_by_product = {row["product_id"]: row for row in stock_rows}
        demand_rows = []
        for product_id in sorted(set(demand) | set(stock_by_product), key=lambda pid: product_map.get(pid, {}).get("product_name", "")):
            product = product_map.get(product_id, {})
            stock = stock_by_product.get(product_id, {})
            demand_rows.append({"product_id": product_id, "product_code": product.get("product_code"),
                "product_name": product.get("product_name"), "unit": product.get("unit_of_measure"),
                "required_quantity": demand.get(product_id, Decimal("0.000")),
                "available_quantity": stock.get("available_quantity", Decimal("0.000")),
                "committed_quantity": stock.get("committed_quantity", Decimal("0.000")),
                "remaining_quantity": stock.get("remaining_quantity", Decimal("0.000")),
                "availability_entered": product_id in stock_by_product})
        deliveries = self.deliveries.list_deliveries(day, day)
        delivery_statuses: dict[str, int] = defaultdict(int)
        for row in deliveries:
            delivery_statuses[row["status"]] += 1
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT_BIG(*) FROM dbo.Customers WHERE IsActive=1")
            active_customers = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT_BIG(*) FROM dbo.Subscriptions WHERE Status='PENDING_CUSTOMER_CONFIRMATION'")
            pending = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT_BIG(*) FROM dbo.CustomerCharges WHERE ChargeDate=?", day)
            daily_sales_count = int(cursor.fetchone()[0])
            cursor.execute("SELECT COALESCE(SUM(Amount),0) FROM dbo.CustomerCharges WHERE ChargeDate=?", day)
            daily_sales = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(Amount),0) FROM dbo.CustomerCharges WHERE ChargeDate BETWEEN ? AND ?", month_start, day)
            monthly_sales = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(Amount),0) FROM dbo.Payments WHERE PaymentDate=?", day)
            daily_collections = cursor.fetchone()[0]
            cursor.execute("SELECT COALESCE(SUM(Amount),0) FROM dbo.Payments WHERE PaymentDate BETWEEN ? AND ?", month_start, day)
            monthly_collections = cursor.fetchone()[0]
            cursor.close()
        return {"as_of": day, "active_customers": active_customers, "active_subscriptions": len(active),
                "pending_confirmations": pending, "outstanding_balance": self._outstanding_total(),
                "daily_sales": daily_sales or Decimal("0.00"), "daily_sales_count": daily_sales_count,
                "monthly_sales": monthly_sales or Decimal("0.00"),
                "daily_collections": daily_collections or Decimal("0.00"),
                "monthly_collections": monthly_collections or Decimal("0.00"),
                "today_demand_and_stock": demand_rows, "today_deliveries": deliveries,
                "delivery_status_counts": dict(delivery_statuses),
                "depleted_stock": [row for row in demand_rows if row["availability_entered"] and row["remaining_quantity"] <= 0],
                "stock_warning_basis": "Warnings show entered availability at or below zero remaining; no unconfigured low-stock threshold is assumed."}

    def _validate_dates(self, start: date | None, end: date | None) -> tuple[date, date]:
        end = end or self.today
        start = start or end.replace(day=1)
        if end < start:
            raise ValueError("through_date must be on or after from_date")
        if (end - start).days > 365:
            raise ValueError("Report date range cannot exceed 366 days")
        return start, end

    def _demand(self, start: date, end: date, product_id: int | None) -> list[dict[str, Any]]:
        products = self.master.list_products()
        if product_id is not None:
            products = [p for p in products if p["id"] == product_id]
        by_id = {p["id"]: p for p in products}
        totals: dict[tuple[date, int], Decimal] = defaultdict(lambda: Decimal("0.000"))
        for sub in self.subscriptions.list_subscriptions(status="APPROVED"):
            if sub["product_id"] not in by_id:
                continue
            overlap_start, overlap_end = max(start, sub["start_date"]), min(end, sub["end_date"])
            if overlap_end < overlap_start:
                continue
            for delivery_day in delivery_dates(overlap_start, overlap_end,
                                               sub["frequency"], set(sub.get("selected_days", []))):
                totals[(delivery_day, sub["product_id"])] += sub["quantity_per_delivery"]
        return [{"delivery_date": day, "product_id": pid, "product_code": by_id[pid]["product_code"],
                 "product_name": by_id[pid]["product_name"], "unit": by_id[pid]["unit_of_measure"],
                 "required_quantity": quantity}
                for (day, pid), quantity in sorted(totals.items(), key=lambda pair: (pair[0][0], by_id[pair[0][1]]["product_name"]))]

    def report(self, name: str, *, from_date: date | None = None, through_date: date | None = None,
               customer_id: int | None = None, product_id: int | None = None, route_id: int | None = None,
               status: str | None = None, active: bool | None = None, search: str | None = None) -> dict[str, Any]:
        name = name.lower()
        if name not in self.REPORTS:
            raise ValueError("Unsupported report name")
        start, end = self._validate_dates(from_date, through_date)
        if name == "availability":
            rows = self.subscriptions.list_availability(start, end, product_id)
        elif name == "demand":
            rows = self._demand(start, end, product_id)
        elif name == "sales":
            rows = self.billing.list_charges(customer_id, start, end)
        elif name == "collections":
            payments = self.billing.list_payments(customer_id, start, end)
            grouped: dict[tuple[date, str], dict[str, Any]] = {}
            for payment in payments:
                key = (payment["payment_date"], payment["payment_method"])
                row = grouped.setdefault(key, {"payment_date": key[0], "payment_method": key[1],
                    "payment_count": 0, "collected_amount": Decimal("0.00")})
                row["payment_count"] += 1
                row["collected_amount"] += payment["amount"]
            rows = sorted(grouped.values(), key=lambda row: (row["payment_date"], row["payment_method"]))
        elif name == "payments":
            rows = self.billing.list_payments(customer_id, start, end)
        elif name == "routes":
            deliveries = self.deliveries.list_deliveries(start, end, route_id=route_id, status=status)
            groups: dict[tuple[str, str, str], dict[str, Any]] = {}
            for delivery in deliveries:
                key = (delivery["route_name"] or "Unassigned", delivery["product_name"], delivery["unit_of_measure"])
                group = groups.setdefault(key, {"route_name": key[0], "product_name": key[1], "unit": key[2],
                    "delivery_count": 0, "delivered_count": 0, "missed_count": 0, "cancelled_count": 0,
                    "delivered_quantity": Decimal("0.000")})
                group["delivery_count"] += 1
                if delivery["status"] == "DELIVERED":
                    group["delivered_count"] += 1
                    group["delivered_quantity"] += delivery["delivered_quantity"] if delivery["delivered_quantity"] is not None else delivery["planned_quantity"]
                elif delivery["status"] == "MISSED":
                    group["missed_count"] += 1
                elif delivery["status"] == "CANCELLED":
                    group["cancelled_count"] += 1
            rows = sorted(groups.values(), key=lambda row: (row["route_name"], row["product_name"]))
        elif name == "deliveries":
            rows = self.deliveries.list_deliveries(start, end, route_id=route_id, customer_id=customer_id, status=status)
        elif name == "customers":
            rows = self.master.list_customers(search, active)
        elif name == "subscriptions":
            rows = self.subscriptions.list_subscriptions(status=status, customer_id=customer_id)
            rows = [row for row in rows if row["start_date"] <= end and row["end_date"] >= start]
        elif name == "ledger":
            if customer_id is None:
                raise ValueError("customer_id is required for a customer ledger report")
            ledger = self.billing.customer_ledger(customer_id)
            if ledger is None:
                raise LookupError("Customer not found")
            rows = [row for row in ledger["entries"] if start <= row["entry_date"] <= end]
            return {"report": name, "from_date": start, "through_date": end,
                    "customer_id": customer_id, "account_balance_as_of_today": ledger["outstanding_balance"],
                    "period_net_change": sum((row["signed_amount"] for row in rows), Decimal("0.00")),
                    "count": len(rows), "rows": rows}
        elif name == "outstanding":
            rows = [row for row in self._balance_rows() if row["outstanding_balance"] > 0]
            if customer_id is not None:
                rows = [row for row in rows if row["customer_id"] == customer_id]
            return {"report": name, "as_of": self.today, "count": len(rows), "rows": rows,
                    "summary": {"total_outstanding": sum((row["outstanding_balance"] for row in rows), Decimal("0.00"))}}
        elif name == "notifications":
            rows = self.notifications.list(status=status, limit=500)
            rows = [row for row in rows if start <= row["created_at"].date() <= end]
        else:
            rows = []
        return {"report": name, "from_date": start, "through_date": end, "count": len(rows), "rows": rows}
