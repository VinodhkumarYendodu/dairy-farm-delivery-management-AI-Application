"""Allowlisted, read-only business data reports for the local AI assistant."""

from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any

from ai.schemas import IntentPlan
from database.repositories.billing import BillingRepository
from database.repositories.deliveries import DeliveryRepository
from database.repositories.master_data import MasterDataRepository
from database.repositories.subscriptions import SubscriptionRepository


def month_range(today: date, period: str) -> tuple[date, date]:
    if period == "THIS_MONTH":
        return date(today.year, today.month, 1), date(today.year, today.month, monthrange(today.year, today.month)[1])
    if period == "LAST_MONTH":
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    raise ValueError("A calendar month period is required")


class ReportingService:
    """Runs validated intents through existing parameterized repositories."""

    def __init__(self, *, master=None, subscriptions=None, deliveries=None, billing=None):
        self.master = master or MasterDataRepository()
        self.subscriptions = subscriptions or SubscriptionRepository()
        self.deliveries = deliveries or DeliveryRepository()
        self.billing = billing or BillingRepository()

    def _range(self, plan: IntentPlan, today: date) -> tuple[date, date]:
        if plan.period in {"THIS_MONTH", "LAST_MONTH"}:
            return month_range(today, plan.period)
        if plan.period == "CUSTOM" and plan.from_date and plan.through_date:
            return plan.from_date, plan.through_date
        if plan.intent == "monthly_charges":
            return month_range(today, "LAST_MONTH")
        return month_range(today, "THIS_MONTH")

    def execute(self, plan: IntentPlan, today: date) -> dict[str, Any]:
        if plan.intent == "unsupported":
            return {"message": "I can answer read-only questions about active subscriptions, today's demand, pending confirmations, outstanding balances, monthly charges, and delivered route volumes."}

        if plan.intent == "active_subscriptions":
            rows = self.subscriptions.list_subscriptions(status="APPROVED")
            active = [row for row in rows if row["start_date"] <= today <= row["end_date"]]
            return {"as_of": today, "count": len(active)}

        if plan.intent == "today_demand":
            products = self.master.list_products(active=True)
            if plan.product:
                needle = plan.product.casefold().strip()
                matches = [row for row in products if needle in row["product_name"].casefold()
                           or needle in row["product_code"].casefold()]
                if not matches:
                    raise ValueError("No active product matches that name or code")
                if len(matches) > 1:
                    raise ValueError("That product name is ambiguous; specify a more exact name or code")
                products = matches
            product_map = {row["id"]: row for row in products}
            totals: dict[int, Decimal] = {row["id"]: Decimal("0.000") for row in products}
            subscriptions = self.subscriptions.list_subscriptions(status="APPROVED")
            for row in subscriptions:
                if row["product_id"] not in totals or not row["start_date"] <= today <= row["end_date"]:
                    continue
                if row["frequency"] == "SELECTED_DAYS" and today.isoweekday() not in row.get("selected_days", []):
                    continue
                totals[row["product_id"]] += row["quantity_per_delivery"]
            result = [{"product_code": product_map[pid]["product_code"],
                       "product_name": product_map[pid]["product_name"],
                       "unit": product_map[pid]["unit_of_measure"], "required_quantity": quantity}
                      for pid, quantity in totals.items()]
            return {"delivery_date": today, "products": result}

        if plan.intent == "pending_confirmations":
            rows = self.subscriptions.list_subscriptions(status="PENDING_CUSTOMER_CONFIRMATION")
            allowed_fields = ("subscription_number", "customer_name", "product_name", "quantity_per_delivery",
                              "frequency", "start_date", "end_date", "status")
            safe_rows = [{key: row[key] for key in allowed_fields if key in row} for row in rows]
            return {"count": len(safe_rows), "subscriptions": safe_rows[:100], "truncated": len(safe_rows) > 100}

        if plan.intent == "outstanding_balances":
            customers = self.master.list_customers()
            results = []
            for customer in customers:
                ledger = self.billing.customer_ledger(customer["id"])
                balance = ledger["outstanding_balance"] if ledger else Decimal("0.00")
                if balance > 0:
                    results.append({"customer_code": customer["customer_code"],
                                    "customer_name": customer["full_name"], "outstanding_balance": balance})
            results.sort(key=lambda row: row["outstanding_balance"], reverse=True)
            return {"count": len(results), "customers": results[:100], "truncated": len(results) > 100}

        if plan.intent == "monthly_charges":
            start, end = self._range(plan, today)
            charges = self.billing.list_charges(start=start, end=end)
            amount = sum((row["amount"] for row in charges), Decimal("0.00"))
            return {"from_date": start, "through_date": end, "charge_count": len(charges),
                    "total_charges": amount, "basis": "delivered customer charges; excludes payments collected"}

        if plan.intent == "route_volume":
            start, end = self._range(plan, today)
            deliveries = self.deliveries.list_deliveries(start, end, status="DELIVERED")
            volumes: dict[tuple[str, str], Decimal] = {}
            counts: dict[tuple[str, str], int] = {}
            for row in deliveries:
                route = row["route_name"] or "Unassigned"
                unit = row["unit_of_measure"]
                key = (route, unit)
                quantity = row["delivered_quantity"]
                if quantity is None:
                    quantity = row["planned_quantity"]
                volumes[key] = volumes.get(key, Decimal("0.000")) + quantity
                counts[key] = counts.get(key, 0) + 1
            results = [{"route_name": route, "unit": unit, "delivered_quantity": quantity,
                        "delivery_count": counts[(route, unit)]}
                       for (route, unit), quantity in volumes.items()]
            results.sort(key=lambda row: (row["unit"], -row["delivered_quantity"]))
            return {"from_date": start, "through_date": end, "routes": results,
                    "note": "Volumes are grouped by unit and include delivered records only."}

        return {"message": "This question is outside the approved read-only intent catalogue."}
