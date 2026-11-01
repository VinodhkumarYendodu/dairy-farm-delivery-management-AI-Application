"""SQL Server persistence for delivery charges, payments, and ledger entries."""

from __future__ import annotations

from datetime import date
from calendar import monthrange
from decimal import Decimal
from typing import Any

from database.connection import sql_connection
from database.repositories.notifications import NotificationRepository
from services.billing_service import calculate_charge_amount, calculate_ledger_totals, validate_payment_allocations


class BillingRepository:
    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def generate_charges(self, start: date, end: date, actor: str) -> dict[str, Any]:
        created = already_charged = 0
        missing_price: list[int] = []
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT d.DeliveryId AS delivery_id, d.CustomerId AS customer_id, d.DeliveryDate AS charge_date, "
                "COALESCE(d.DeliveredQuantity,d.PlannedQuantity) AS quantity, s.UnitPriceSnapshot AS subscription_price, "
                "price.PricePerUnit AS effective_price, p.ProductName AS product_name "
                "FROM dbo.Deliveries d WITH (UPDLOCK,HOLDLOCK) "
                "JOIN dbo.Subscriptions s ON s.SubscriptionId=d.SubscriptionId "
                "JOIN dbo.MilkProducts p ON p.MilkProductId=d.MilkProductId "
                "OUTER APPLY (SELECT TOP(1) pp.PricePerUnit FROM dbo.ProductPrices pp "
                "WHERE pp.MilkProductId=d.MilkProductId AND pp.EffectiveFrom<=d.DeliveryDate "
                "AND (pp.EffectiveTo IS NULL OR pp.EffectiveTo>=d.DeliveryDate) ORDER BY pp.EffectiveFrom DESC) price "
                "WHERE d.Status='DELIVERED' AND d.DeliveryDate BETWEEN ? AND ? "
                "AND COALESCE(d.DeliveredQuantity,d.PlannedQuantity)>0 ORDER BY d.DeliveryDate,d.DeliveryId",
                start, end,
            )
            deliveries = self._rows(cursor)
            for delivery in deliveries:
                cursor.execute(
                    "SELECT ChargeId FROM dbo.CustomerCharges WITH (UPDLOCK,HOLDLOCK) WHERE DeliveryId=?",
                    delivery["delivery_id"],
                )
                if cursor.fetchone():
                    already_charged += 1
                    continue
                price = delivery["subscription_price"]
                if price is None:
                    price = delivery["effective_price"]
                if price is None:
                    missing_price.append(delivery["delivery_id"])
                    continue
                quantity = delivery["quantity"]
                amount = calculate_charge_amount(quantity, price)
                description = f"{delivery['product_name']} delivery on {delivery['charge_date'].isoformat()}"
                cursor.execute(
                    "INSERT INTO dbo.CustomerCharges(CustomerId,DeliveryId,ChargeDate,Quantity,UnitPrice,Amount,Description) "
                    "OUTPUT inserted.ChargeId VALUES (?,?,?,?,?,?,?)",
                    delivery["customer_id"], delivery["delivery_id"], delivery["charge_date"],
                    quantity, price, amount, description,
                )
                charge_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                    actor, "CHARGE_GENERATED", "CustomerCharge", str(charge_id),
                    f"delivery={delivery['delivery_id']}; quantity={quantity}; unit_price={price}; amount={amount}",
                )
                created += 1
            connection.commit()
            cursor.close()
        return {"from_date": start, "through_date": end, "created": created,
                "already_charged": already_charged, "missing_price_delivery_ids": missing_price}

    def list_charges(
        self, customer_id: int | None = None, start: date | None = None,
        end: date | None = None, open_only: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT c.ChargeId AS id, c.CustomerId AS customer_id, cust.CustomerCode AS customer_code, "
            "cust.FullName AS customer_name, c.DeliveryId AS delivery_id, c.ChargeDate AS charge_date, "
            "c.Quantity AS quantity, c.UnitPrice AS unit_price, c.Amount AS amount, "
            "COALESCE(alloc.AllocatedAmount,0) AS allocated_amount, "
            "c.Amount-COALESCE(alloc.AllocatedAmount,0) AS amount_due, c.Description AS description "
            "FROM dbo.CustomerCharges c JOIN dbo.Customers cust ON cust.CustomerId=c.CustomerId "
            "OUTER APPLY (SELECT SUM(pa.AllocatedAmount) AS AllocatedAmount FROM dbo.PaymentAllocations pa "
            "WHERE pa.ChargeId=c.ChargeId) alloc WHERE 1=1 "
        )
        params: list[Any] = []
        if customer_id is not None:
            query += "AND c.CustomerId=? "
            params.append(customer_id)
        if start is not None:
            query += "AND c.ChargeDate>=? "
            params.append(start)
        if end is not None:
            query += "AND c.ChargeDate<=? "
            params.append(end)
        if open_only:
            query += "AND c.Amount>COALESCE(alloc.AllocatedAmount,0) "
        query += "ORDER BY c.ChargeDate,c.ChargeId"
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, *params)
            rows = self._rows(cursor)
            cursor.close()
            return rows

    def record_payment(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        allocations = item.get("allocations", [])
        validate_payment_allocations(item["amount"], allocations)
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT FullName,Email FROM dbo.Customers WITH (UPDLOCK,HOLDLOCK) WHERE CustomerId=?", item["customer_id"])
            customer = cursor.fetchone()
            if not customer:
                raise LookupError("Customer not found")

            allocation_details = []
            for allocation in sorted(allocations, key=lambda row: row["charge_id"]):
                cursor.execute(
                    "SELECT c.CustomerId AS customer_id, c.Amount AS amount, "
                    "COALESCE(SUM(pa.AllocatedAmount),0) AS allocated "
                    "FROM dbo.CustomerCharges c WITH (UPDLOCK,HOLDLOCK) "
                    "LEFT JOIN dbo.PaymentAllocations pa WITH (UPDLOCK,HOLDLOCK) ON pa.ChargeId=c.ChargeId "
                    "WHERE c.ChargeId=? GROUP BY c.CustomerId,c.Amount", allocation["charge_id"],
                )
                charge = cursor.fetchone()
                if not charge:
                    raise LookupError(f"Charge {allocation['charge_id']} not found")
                charge_customer, amount, already_allocated = charge
                if charge_customer != item["customer_id"]:
                    raise ValueError(f"Charge {allocation['charge_id']} belongs to a different customer")
                if allocation["amount"] > amount - already_allocated:
                    raise ValueError(f"Allocation exceeds the remaining balance on charge {allocation['charge_id']}")
                allocation_details.append(allocation)

            cursor.execute(
                "INSERT INTO dbo.Payments(CustomerId,PaymentDate,Amount,PaymentMethod,Reference,Notes,Actor) "
                "OUTPUT inserted.PaymentId AS id VALUES (?,?,?,?,?,?,?)",
                item["customer_id"], item["payment_date"], item["amount"], item["payment_method"],
                item.get("reference"), item.get("notes"), actor,
            )
            payment_id = cursor.fetchone()[0]
            for allocation in allocation_details:
                cursor.execute(
                    "INSERT INTO dbo.PaymentAllocations(PaymentId,ChargeId,AllocatedAmount) VALUES (?,?,?)",
                    payment_id, allocation["charge_id"], allocation["amount"],
                )
            allocated_total = sum((allocation["amount"] for allocation in allocation_details), Decimal("0.00"))
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                actor, "PAYMENT_RECORDED", "Payment", str(payment_id),
                f"customer={item['customer_id']}; amount={item['amount']}; allocated={allocated_total}; method={item['payment_method']}",
            )
            NotificationRepository.enqueue_with_cursor(cursor, "payment_receipt", f"payment:{payment_id}:receipt", customer[1], {
                "customer_name": customer[0], "payment_id": payment_id, "payment_date": item["payment_date"],
                "amount": item["amount"], "payment_method": item["payment_method"],
                "reference": item.get("reference"), "allocated_amount": allocated_total,
            })
            connection.commit()
            cursor.close()
        return {"id": payment_id, "customer_id": item["customer_id"], "payment_date": item["payment_date"],
                "amount": item["amount"], "payment_method": item["payment_method"],
                "reference": item.get("reference"), "allocated_amount": allocated_total,
                "unallocated_amount": item["amount"] - allocated_total,
                "allocations": allocation_details}

    def list_payments(
        self, customer_id: int | None = None, start: date | None = None, end: date | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT p.PaymentId AS id, p.CustomerId AS customer_id, c.CustomerCode AS customer_code, "
            "c.FullName AS customer_name, p.PaymentDate AS payment_date, p.Amount AS amount, "
            "p.PaymentMethod AS payment_method, p.Reference AS reference, p.Notes AS notes, p.Actor AS actor, "
            "COALESCE(a.AllocatedAmount,0) AS allocated_amount, p.Amount-COALESCE(a.AllocatedAmount,0) AS unallocated_amount "
            "FROM dbo.Payments p JOIN dbo.Customers c ON c.CustomerId=p.CustomerId "
            "OUTER APPLY (SELECT SUM(AllocatedAmount) AS AllocatedAmount FROM dbo.PaymentAllocations "
            "WHERE PaymentId=p.PaymentId) a WHERE 1=1 "
        )
        params: list[Any] = []
        if customer_id is not None:
            query += "AND p.CustomerId=? "
            params.append(customer_id)
        if start is not None:
            query += "AND p.PaymentDate>=? "
            params.append(start)
        if end is not None:
            query += "AND p.PaymentDate<=? "
            params.append(end)
        query += "ORDER BY p.PaymentDate DESC,p.PaymentId DESC"
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, *params)
            rows = self._rows(cursor)
            cursor.close()
            return rows

    def create_adjustment(self, item: dict[str, Any], actor: str) -> dict[str, Any]:
        signed_amount = item["amount"] if item["direction"] == "DEBIT" else -item["amount"]
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT CustomerId FROM dbo.Customers WITH (UPDLOCK,HOLDLOCK) WHERE CustomerId=?", item["customer_id"])
            if not cursor.fetchone():
                raise LookupError("Customer not found")
            cursor.execute(
                "INSERT INTO dbo.CustomerAdjustments(CustomerId,AdjustmentDate,EntryType,Direction,Amount,Reason,Actor) "
                "OUTPUT inserted.AdjustmentId AS id VALUES (?,?,?,?,?,?,?)",
                item["customer_id"], item["adjustment_date"], item["entry_type"], item["direction"],
                item["amount"], item["reason"], actor,
            )
            adjustment_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                actor, item["entry_type"], "CustomerAdjustment", str(adjustment_id),
                f"customer={item['customer_id']}; direction={item['direction']}; amount={item['amount']}; reason={item['reason']}"[:2000],
            )
            connection.commit()
            cursor.close()
        return {"id": adjustment_id, **item, "signed_amount": signed_amount, "actor": actor}

    def customer_ledger(self, customer_id: int) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT CustomerCode,FullName FROM dbo.Customers WHERE CustomerId=?", customer_id)
            customer = cursor.fetchone()
            if not customer:
                return None
            cursor.execute(
                "SELECT ChargeId AS id, ChargeDate AS entry_date, Amount AS amount, UnitPrice AS unit_price, "
                "Quantity AS quantity, DeliveryId AS delivery_id, Description AS description "
                "FROM dbo.CustomerCharges WHERE CustomerId=? ORDER BY ChargeDate,ChargeId", customer_id,
            )
            charges = self._rows(cursor)
            cursor.execute(
                "SELECT p.PaymentId AS id, p.PaymentDate AS entry_date, p.Amount AS amount, p.PaymentMethod AS payment_method, "
                "p.Reference AS reference, COALESCE(a.AllocatedAmount,0) AS allocated_amount "
                "FROM dbo.Payments p OUTER APPLY (SELECT SUM(AllocatedAmount) AS AllocatedAmount "
                "FROM dbo.PaymentAllocations WHERE PaymentId=p.PaymentId) a "
                "WHERE p.CustomerId=? ORDER BY p.PaymentDate,p.PaymentId", customer_id,
            )
            payments = self._rows(cursor)
            cursor.execute(
                "SELECT AdjustmentId AS id, AdjustmentDate AS entry_date, EntryType AS entry_type, "
                "Direction AS direction, Amount AS amount, Reason AS reason, Actor AS actor "
                "FROM dbo.CustomerAdjustments WHERE CustomerId=? ORDER BY AdjustmentDate,AdjustmentId", customer_id,
            )
            adjustments = self._rows(cursor)
            cursor.execute(
                "SELECT c.ChargeId AS charge_id, c.ChargeDate AS charge_date, c.Description AS description, "
                "c.Amount-COALESCE(a.AllocatedAmount,0) AS amount_due "
                "FROM dbo.CustomerCharges c OUTER APPLY (SELECT SUM(AllocatedAmount) AS AllocatedAmount "
                "FROM dbo.PaymentAllocations WHERE ChargeId=c.ChargeId) a "
                "WHERE c.CustomerId=? AND c.Amount>COALESCE(a.AllocatedAmount,0) ORDER BY c.ChargeDate,c.ChargeId",
                customer_id,
            )
            open_charges = self._rows(cursor)
            cursor.close()

        entries: list[dict[str, Any]] = []
        for charge in charges:
            entries.append({"entry_date": charge["entry_date"], "entry_type": "CHARGE", "id": charge["id"],
                            "signed_amount": charge["amount"], "description": charge["description"],
                            "quantity": charge["quantity"], "unit_price": charge["unit_price"],
                            "delivery_id": charge["delivery_id"]})
        for payment in payments:
            entries.append({"entry_date": payment["entry_date"], "entry_type": "PAYMENT", "id": payment["id"],
                            "signed_amount": -payment["amount"], "description": f"{payment['payment_method']} payment "
                            f"{payment['reference'] or ''}".strip(), "payment_amount": payment["amount"],
                            "allocated_amount": payment["allocated_amount"],
                            "unallocated_amount": payment["amount"] - payment["allocated_amount"]})
        for adjustment in adjustments:
            signed_amount = adjustment["amount"] if adjustment["direction"] == "DEBIT" else -adjustment["amount"]
            entries.append({"entry_date": adjustment["entry_date"], "entry_type": adjustment["entry_type"],
                            "id": adjustment["id"], "signed_amount": signed_amount,
                            "description": adjustment["reason"], "direction": adjustment["direction"],
                            "actor": adjustment["actor"]})
        entries.sort(key=lambda row: (row["entry_date"], row["entry_type"], row["id"]))
        totals = calculate_ledger_totals(charges, payments, adjustments)
        return {
            "customer_id": customer_id, "customer_code": customer[0], "customer_name": customer[1],
            "entries": entries, "open_charges": open_charges, **totals,
        }

    def enqueue_monthly_statement(self, customer_id: int, year: int, month: int) -> int:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT FullName,Email FROM dbo.Customers WITH (UPDLOCK,HOLDLOCK) WHERE CustomerId=?", customer_id)
            customer = cursor.fetchone()
            if not customer:
                raise LookupError("Customer not found")
            cursor.execute("SELECT COUNT_BIG(*),COALESCE(SUM(Amount),0) FROM dbo.CustomerCharges WHERE CustomerId=? AND ChargeDate BETWEEN ? AND ?", customer_id, start, end)
            charge_count, charges = cursor.fetchone()
            cursor.execute("SELECT COUNT_BIG(*),COALESCE(SUM(Amount),0) FROM dbo.Payments WHERE CustomerId=? AND PaymentDate BETWEEN ? AND ?", customer_id, start, end)
            payment_count, payments = cursor.fetchone()
            dedupe_key = f"statement:{customer_id}:{year:04d}-{month:02d}"
            cursor.execute("SELECT NotificationId FROM dbo.NotificationOutbox WITH (UPDLOCK,HOLDLOCK) WHERE DeduplicationKey=?", dedupe_key)
            existing = cursor.fetchone()
            if existing:
                notification_id = int(existing[0])
            else:
                notification_id = NotificationRepository.enqueue_with_cursor(cursor, "monthly_statement", dedupe_key, customer[1], {
                    "customer_name": customer[0], "period": f"{year:04d}-{month:02d}", "from_date": start,
                    "through_date": end, "charge_count": charge_count, "charges_total": charges,
                    "payment_count": payment_count, "payments_total": payments,
                })
            connection.commit()
            cursor.close()
            return notification_id
