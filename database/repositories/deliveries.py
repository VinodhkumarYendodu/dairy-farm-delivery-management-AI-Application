"""Idempotent SQL Server delivery planning and status tracking."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from core.config import get_settings
from database.connection import sql_connection
from database.repositories.notifications import NotificationRepository
from database.repositories.subscriptions import SubscriptionRepository
from services.subscription_engine import delivery_dates


class DeliveryRepository:
    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def generate(self, start: date, end: date, actor: str) -> dict[str, Any]:
        created = skipped = 0
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT s.SubscriptionId AS subscription_id, s.CustomerId AS customer_id, "
                "s.MilkProductId AS product_id, s.QuantityPerDelivery AS planned_quantity, "
                "s.Frequency AS frequency, s.StartDate AS start_date, s.EndDate AS end_date, "
                "c.RouteId AS route_id, d.DayOfWeek AS weekday "
                "FROM dbo.Subscriptions s WITH (UPDLOCK,HOLDLOCK) "
                "JOIN dbo.Customers c ON c.CustomerId=s.CustomerId "
                "LEFT JOIN dbo.SubscriptionDays d ON d.SubscriptionId=s.SubscriptionId "
                "WHERE s.Status='APPROVED' AND s.StartDate<=? AND s.EndDate>=? "
                "ORDER BY s.SubscriptionId,d.DayOfWeek", end, start,
            )
            subscriptions: dict[int, dict[str, Any]] = {}
            for row in self._rows(cursor):
                item = subscriptions.setdefault(row["subscription_id"], {**row, "weekdays": set()})
                if row["weekday"] is not None:
                    item["weekdays"].add(row["weekday"])
            for sub in subscriptions.values():
                range_start = max(start, sub["start_date"])
                range_end = min(end, sub["end_date"])
                for delivery_date in delivery_dates(range_start, range_end, sub["frequency"], sub["weekdays"]):
                    cursor.execute(
                        "SELECT DeliveryId FROM dbo.Deliveries WITH (UPDLOCK,HOLDLOCK) "
                        "WHERE SubscriptionId=? AND DeliveryDate=?",
                        sub["subscription_id"], delivery_date,
                    )
                    if cursor.fetchone():
                        skipped += 1
                        continue
                    cursor.execute(
                        "INSERT INTO dbo.Deliveries(SubscriptionId,CustomerId,MilkProductId,RouteId,DeliveryDate,PlannedQuantity) "
                        "OUTPUT inserted.DeliveryId VALUES (?,?,?,?,?,?)",
                        sub["subscription_id"], sub["customer_id"], sub["product_id"], sub["route_id"],
                        delivery_date, sub["planned_quantity"],
                    )
                    delivery_id = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                        actor, "DELIVERY_GENERATED", "Delivery", str(delivery_id),
                        f"subscription={sub['subscription_id']}; date={delivery_date.isoformat()}; quantity={sub['planned_quantity']}",
                    )
                    created += 1
            connection.commit()
            cursor.close()
        return {"from_date": start, "through_date": end, "created": created, "already_existed": skipped}

    def list_deliveries(
        self, start: date, end: date, *, route_id: int | None = None,
        customer_id: int | None = None, status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT d.DeliveryId AS id, d.SubscriptionId AS subscription_id, s.SubscriptionNumber AS subscription_number, "
            "d.CustomerId AS customer_id, c.CustomerCode AS customer_code, c.FullName AS customer_name, "
            "d.RouteId AS route_id, r.RouteName AS route_name, d.MilkProductId AS product_id, "
            "p.ProductCode AS product_code, p.ProductName AS product_name, p.UnitOfMeasure AS unit_of_measure, "
            "d.DeliveryDate AS delivery_date, d.PlannedQuantity AS planned_quantity, "
            "d.DeliveredQuantity AS delivered_quantity, d.Status AS status, d.DeliveredAt AS delivered_at, d.Notes AS notes "
            "FROM dbo.Deliveries d JOIN dbo.Subscriptions s ON s.SubscriptionId=d.SubscriptionId "
            "JOIN dbo.Customers c ON c.CustomerId=d.CustomerId "
            "JOIN dbo.MilkProducts p ON p.MilkProductId=d.MilkProductId "
            "LEFT JOIN dbo.DeliveryRoutes r ON r.RouteId=d.RouteId "
            "WHERE d.DeliveryDate BETWEEN ? AND ? "
        )
        params: list[Any] = [start, end]
        for expression, value in (("d.RouteId=?", route_id), ("d.CustomerId=?", customer_id), ("d.Status=?", status)):
            if value is not None:
                query += f"AND {expression} "
                params.append(value)
        query += "ORDER BY d.DeliveryDate,r.RouteName,c.FullName,p.ProductName"
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(query, *params)
            rows = self._rows(cursor)
            cursor.close()
            return rows

    def change_customer_delivery(
        self, delivery_id: int, customer_id: int, quantity: Any | None, cancel: bool, actor: str,
    ) -> dict[str, Any]:
        """Allow a customer to change one planned delivery before the published cutoff."""
        settings = get_settings()
        now = datetime.now(ZoneInfo(settings.app_timezone))
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT d.DeliveryId AS id,d.DeliveryDate AS delivery_date,d.PlannedQuantity AS planned_quantity,"
                "d.Status AS status,d.MilkProductId AS product_id,s.Status AS subscription_status,"
                "s.Frequency AS frequency,s.QuantityPerDelivery AS subscription_quantity,c.CustomerId AS customer_id "
                "FROM dbo.Deliveries d WITH (UPDLOCK,HOLDLOCK) "
                "JOIN dbo.Subscriptions s ON s.SubscriptionId=d.SubscriptionId "
                "JOIN dbo.Customers c ON c.CustomerId=d.CustomerId "
                "WHERE d.DeliveryId=? AND d.CustomerId=?",
                delivery_id, customer_id,
            )
            rows = self._rows(cursor)
            if not rows:
                cursor.close()
                raise LookupError("Scheduled delivery not found")
            delivery = rows[0]
            if delivery["status"] != "PLANNED":
                cursor.close()
                raise ValueError("Only planned deliveries can be changed")
            deadline = datetime.combine(
                delivery["delivery_date"] - timedelta(days=1),
                time(settings.customer_change_cutoff_hour), tzinfo=ZoneInfo(settings.app_timezone),
            )
            if now >= deadline:
                cursor.close()
                raise ValueError(
                    f"The change cutoff was {settings.customer_change_cutoff_hour:02d}:00 on the day before delivery"
                )

            new_quantity = delivery["planned_quantity"] if cancel else quantity
            if not cancel and delivery["subscription_status"] == "APPROVED":
                commitments = SubscriptionRepository()._approved_commitments(
                    cursor, delivery["product_id"], delivery["delivery_date"], delivery["delivery_date"]
                )
                own_commitment = delivery["planned_quantity"] if delivery["frequency"] == "DAILY" else Decimal("0")
                if delivery["frequency"] == "SELECTED_DAYS":
                    cursor.execute(
                        "SELECT 1 FROM dbo.SubscriptionDays WHERE SubscriptionId=(SELECT SubscriptionId FROM dbo.Deliveries WHERE DeliveryId=?) "
                        "AND DayOfWeek=?", delivery_id, delivery["delivery_date"].isoweekday(),
                    )
                    if cursor.fetchone():
                        own_commitment = delivery["planned_quantity"]
                cursor.execute(
                    "SELECT AvailableQuantity FROM dbo.DailyAvailability WITH (UPDLOCK,HOLDLOCK) "
                    "WHERE AvailabilityDate=? AND MilkProductId=?", delivery["delivery_date"], delivery["product_id"],
                )
                available_row = cursor.fetchone()
                available = available_row[0] if available_row else 0
                other_commitments = commitments.get(delivery["delivery_date"], 0) - own_commitment
                if new_quantity + other_commitments > available:
                    cursor.close()
                    raise ValueError("That quantity exceeds the remaining availability for this delivery date")

            new_status = "CANCELLED" if cancel else "PLANNED"
            cursor.execute(
                "UPDATE dbo.Deliveries SET PlannedQuantity=?,Status=?,UpdatedAt=SYSUTCDATETIME() "
                "OUTPUT inserted.DeliveryId AS id,inserted.DeliveryDate AS delivery_date,"
                "inserted.PlannedQuantity AS planned_quantity,inserted.Status AS status "
                "WHERE DeliveryId=?",
                new_quantity, new_status, delivery_id,
            )
            updated = self._rows(cursor)[0]
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) "
                "VALUES (?,?,?,?,?,?)",
                actor, "CUSTOMER_DELIVERY_CANCEL" if cancel else "CUSTOMER_DELIVERY_CHANGE", "Delivery", str(delivery_id),
                f"status={delivery['status']}; planned_quantity={delivery['planned_quantity']}",
                f"status={new_status}; planned_quantity={new_quantity}",
            )
            connection.commit()
            cursor.close()
            return {**updated, "customer_change_allowed": False, "change_deadline": deadline}

    def update_delivery(
        self, delivery_id: int, *, status: str | None, delivered_quantity: Any,
        notes: str | None, reason: str | None, actor: str,
    ) -> dict[str, Any] | None:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT d.DeliveryId AS id,d.SubscriptionId AS subscription_id,d.CustomerId AS customer_id,"
                "d.MilkProductId AS product_id,d.DeliveryDate AS delivery_date,d.PlannedQuantity AS planned_quantity,"
                "d.DeliveredQuantity AS delivered_quantity,d.Status AS status,d.DeliveredAt AS delivered_at,d.Notes AS notes,"
                "c.FullName AS customer_name,c.Email AS email,p.ProductName AS product_name "
                "FROM dbo.Deliveries d WITH (UPDLOCK,HOLDLOCK) JOIN dbo.Customers c ON c.CustomerId=d.CustomerId "
                "JOIN dbo.MilkProducts p ON p.MilkProductId=d.MilkProductId WHERE d.DeliveryId=?", delivery_id,
            )
            rows = self._rows(cursor)
            if not rows:
                cursor.close()
                return None
            before = rows[0]
            next_status = status or before["status"]
            next_quantity = delivered_quantity if delivered_quantity is not None else before["delivered_quantity"]
            if before["status"] in {"DELIVERED", "MISSED", "CANCELLED"} and (
                next_status != before["status"] or next_quantity != before["delivered_quantity"]
            ) and not (reason and reason.strip()):
                raise ValueError("A reason is required when correcting a completed or cancelled delivery")
            if next_status == "DELIVERED" and next_quantity is None:
                next_quantity = before["planned_quantity"]
            delivered_at = before["delivered_at"] if next_status == "DELIVERED" and before["status"] == "DELIVERED" else None
            if next_status == "DELIVERED" and delivered_at is None:
                cursor.execute("SELECT SYSUTCDATETIME()")
                delivered_at = cursor.fetchone()[0]
            next_notes = notes if notes is not None else before["notes"]
            cursor.execute(
                "UPDATE dbo.Deliveries SET Status=?,DeliveredQuantity=?,DeliveredAt=?,Notes=?,UpdatedAt=SYSUTCDATETIME() "
                "WHERE DeliveryId=?", next_status, next_quantity, delivered_at, next_notes, delivery_id,
            )
            if next_status != before["status"] or next_quantity != before["delivered_quantity"]:
                cursor.execute(
                    "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) "
                    "OUTPUT inserted.AuditLogId VALUES (?,?,?,?,?,?)", actor, "DELIVERY_CORRECTED", "Delivery", str(delivery_id),
                    f"status={before['status']}; delivered_quantity={before['delivered_quantity']}",
                    f"status={next_status}; delivered_quantity={next_quantity}; reason={reason or ''}"[:2000],
                )
                audit_id = cursor.fetchone()[0]
                if next_status == "MISSED" and before["status"] != "MISSED":
                    NotificationRepository.enqueue_with_cursor(cursor, "delivery_exception", f"delivery-missed:{delivery_id}", before["email"], {
                        "customer_name": before["customer_name"], "delivery_id": delivery_id,
                        "delivery_date": before["delivery_date"], "product_name": before["product_name"],
                        "planned_quantity": before["planned_quantity"], "reason": reason or "Delivery marked missed",
                        "audit_id": audit_id,
                    })
            cursor.execute(
                "SELECT DeliveryId AS id, SubscriptionId AS subscription_id, DeliveryDate AS delivery_date, "
                "PlannedQuantity AS planned_quantity, DeliveredQuantity AS delivered_quantity, "
                "Status AS status, DeliveredAt AS delivered_at, Notes AS notes "
                "FROM dbo.Deliveries WHERE DeliveryId=?", delivery_id,
            )
            updated = self._rows(cursor)[0]
            connection.commit()
            cursor.close()
            return updated
