"""Transactional SQL Server repository for availability and subscriptions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import get_settings
from database.connection import sql_connection
from services.subscription_engine import calculate_shortages, delivery_dates
from database.repositories.notifications import NotificationRepository


class SubscriptionRepository:
    @staticmethod
    def _rows(cursor) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _approved_commitments(self, cursor, product_id: int, start: date, end: date) -> dict[date, Decimal]:
        cursor.execute(
            "SELECT s.SubscriptionId AS id, s.QuantityPerDelivery AS quantity, s.Frequency AS frequency, "
            "s.Status AS status, "
            "s.StartDate AS start_date, s.EndDate AS end_date, d.DayOfWeek AS weekday "
            "FROM dbo.Subscriptions s WITH (UPDLOCK,HOLDLOCK) "
            "LEFT JOIN dbo.SubscriptionDays d ON d.SubscriptionId=s.SubscriptionId "
            "WHERE s.MilkProductId=? AND s.StartDate<=? AND s.EndDate>=? AND "
            "(s.Status='APPROVED' OR (s.Status='CANCELLED' AND EXISTS ("
            "SELECT 1 FROM dbo.Deliveries planned WHERE planned.SubscriptionId=s.SubscriptionId "
            "AND planned.Status='PLANNED' AND planned.DeliveryDate BETWEEN ? AND ?)))",
            product_id, end, start, start, end,
        )
        subscriptions: dict[int, dict[str, Any]] = {}
        for row in self._rows(cursor):
            entry = subscriptions.setdefault(row["id"], {**row, "weekdays": set()})
            if row["weekday"] is not None:
                entry["weekdays"].add(row["weekday"])
        cursor.execute(
            "SELECT SubscriptionId AS subscription_id,DeliveryDate AS delivery_date,Status AS status,"
            "PlannedQuantity AS planned_quantity FROM dbo.Deliveries "
            "WHERE MilkProductId=? AND DeliveryDate BETWEEN ? AND ?",
            product_id, start, end,
        )
        overrides = {(row["subscription_id"], row["delivery_date"]): row for row in self._rows(cursor)}
        committed: dict[date, Decimal] = {}
        for sub in subscriptions.values():
            range_start = max(start, sub["start_date"])
            range_end = min(end, sub["end_date"])
            for day in delivery_dates(range_start, range_end, sub["frequency"], sub["weekdays"]):
                override = overrides.get((sub["id"], day))
                if override and override["status"] == "CANCELLED":
                    continue
                if sub["status"] == "CANCELLED" and not override:
                    continue
                quantity = override["planned_quantity"] if override else sub["quantity"]
                committed[day] = committed.get(day, Decimal("0")) + quantity
        return committed

    def _locked_availability(self, cursor, product_id: int, dates: list[date]) -> dict[date, Decimal]:
        result: dict[date, Decimal] = {}
        for day in sorted(set(dates)):
            cursor.execute(
                "SELECT AvailableQuantity FROM dbo.DailyAvailability WITH (UPDLOCK,HOLDLOCK) "
                "WHERE AvailabilityDate=? AND MilkProductId=?", day, product_id,
            )
            row = cursor.fetchone()
            if row:
                result[day] = row[0]
        return result

    def list_availability(self, start: date, end: date, product_id: int | None = None) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            query = (
                "SELECT a.AvailabilityDate AS availability_date, a.MilkProductId AS product_id, "
                "p.ProductCode AS product_code, p.ProductName AS product_name, p.UnitOfMeasure AS unit_of_measure, "
                "a.AvailableQuantity AS available_quantity "
                "FROM dbo.DailyAvailability a JOIN dbo.MilkProducts p ON p.MilkProductId=a.MilkProductId "
                "WHERE a.AvailabilityDate BETWEEN ? AND ? "
            )
            params: list[Any] = [start, end]
            if product_id is not None:
                query += "AND a.MilkProductId=? "
                params.append(product_id)
            query += "ORDER BY a.AvailabilityDate,p.ProductName"
            cursor.execute(query, *params)
            rows = self._rows(cursor)
            by_product: dict[int, dict[date, Decimal]] = {}
            for product in {row["product_id"] for row in rows}:
                by_product[product] = self._approved_commitments(cursor, product, start, end)
            cursor.close()
        for row in rows:
            committed = by_product[row["product_id"]].get(row["availability_date"], Decimal("0"))
            row["committed_quantity"] = committed
            row["remaining_quantity"] = row["available_quantity"] - committed
        return rows

    def set_availability(self, day: date, product_id: int, quantity: Decimal, actor: str) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT IsActive FROM dbo.MilkProducts WITH (UPDLOCK,HOLDLOCK) WHERE MilkProductId=?", product_id)
            product = cursor.fetchone()
            if not product:
                raise LookupError("Product not found")
            if not product[0]:
                raise ValueError("Availability can only be set for an active product")
            existing_availability = self._locked_availability(cursor, product_id, [day])
            committed = self._approved_commitments(cursor, product_id, day, day).get(day, Decimal("0"))
            if quantity < committed:
                raise ValueError(f"Available quantity cannot be below the {committed} already committed")
            if day in existing_availability:
                cursor.execute(
                    "UPDATE dbo.DailyAvailability SET AvailableQuantity=?, UpdatedAt=SYSUTCDATETIME() "
                    "WHERE AvailabilityDate=? AND MilkProductId=?", quantity, day, product_id,
                )
                action = "AVAILABILITY_UPDATE"
            else:
                cursor.execute(
                    "INSERT INTO dbo.DailyAvailability(AvailabilityDate,MilkProductId,AvailableQuantity) VALUES (?,?,?)",
                    day, product_id, quantity,
                )
                action = "AVAILABILITY_CREATE"
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) "
                "VALUES (?,?,?,?,?)", actor, action, "DailyAvailability", f"{day.isoformat()}:{product_id}",
                f"available_quantity={quantity}; committed_quantity={committed}",
            )
            connection.commit()
            cursor.close()
        return {"availability_date": day, "product_id": product_id, "available_quantity": quantity,
                "committed_quantity": committed, "remaining_quantity": quantity - committed}

    def list_subscriptions(self, status: str | None = None, customer_id: int | None = None) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            query = (
                "SELECT s.SubscriptionId AS id, s.SubscriptionNumber AS subscription_number, "
                "s.CustomerId AS customer_id, c.FullName AS customer_name, s.MilkProductId AS product_id, "
                "p.ProductName AS product_name, s.QuantityPerDelivery AS quantity_per_delivery, "
                "s.Frequency AS frequency, s.StartDate AS start_date, s.EndDate AS end_date, "
                "s.Status AS status, s.ConfirmationStatus AS confirmation_status, s.ConfirmedAt AS confirmed_at, "
                "s.ApprovedAt AS approved_at, s.UnitPriceSnapshot AS unit_price_snapshot, s.Notes AS notes "
                "FROM dbo.Subscriptions s JOIN dbo.Customers c ON c.CustomerId=s.CustomerId "
                "JOIN dbo.MilkProducts p ON p.MilkProductId=s.MilkProductId WHERE 1=1 "
            )
            params: list[Any] = []
            if status:
                query += "AND s.Status=? "
                params.append(status)
            if customer_id is not None:
                query += "AND s.CustomerId=? "
                params.append(customer_id)
            query += "ORDER BY s.CreatedAt DESC"
            cursor.execute(query, *params)
            subscriptions = self._rows(cursor)
            if subscriptions:
                ids = [sub["id"] for sub in subscriptions]
                marks = ",".join("?" for _ in ids)
                cursor.execute(
                    f"SELECT SubscriptionId AS subscription_id, DayOfWeek AS day_of_week "
                    f"FROM dbo.SubscriptionDays WHERE SubscriptionId IN ({marks}) ORDER BY DayOfWeek", *ids,
                )
                days = self._rows(cursor)
                day_map: dict[int, list[int]] = {}
                for row in days:
                    day_map.setdefault(row["subscription_id"], []).append(row["day_of_week"])
                for sub in subscriptions:
                    sub["selected_days"] = day_map.get(sub["id"], [])
            cursor.close()
            return subscriptions

    def create_subscription(
        self, item: dict[str, Any], actor: str, *, notify_confirmation: bool = True,
        require_available: bool = False,
    ) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("SELECT FullName,Email FROM dbo.Customers WITH (UPDLOCK,HOLDLOCK) WHERE CustomerId=? AND IsActive=1", item["customer_id"])
            customer = cursor.fetchone()
            if not customer:
                raise LookupError("Active customer not found")
            cursor.execute("SELECT ProductName FROM dbo.MilkProducts WITH (UPDLOCK,HOLDLOCK) WHERE MilkProductId=? AND IsActive=1", item["product_id"])
            product = cursor.fetchone()
            if not product:
                raise LookupError("Active product not found")
            cursor.execute(
                "SELECT TOP(1) PricePerUnit FROM dbo.ProductPrices WHERE MilkProductId=? AND EffectiveFrom<=? "
                "AND (EffectiveTo IS NULL OR EffectiveTo>=?) ORDER BY EffectiveFrom DESC",
                item["product_id"], item["start_date"], item["start_date"],
            )
            price_row = cursor.fetchone()
            number = "SUB-" + uuid4().hex[:12].upper()
            cursor.execute(
                "INSERT INTO dbo.Subscriptions(SubscriptionNumber,CustomerId,MilkProductId,QuantityPerDelivery,Frequency,StartDate,EndDate,Status,ConfirmationStatus,UnitPriceSnapshot,Notes) "
                "OUTPUT inserted.SubscriptionId AS id, inserted.SubscriptionNumber AS subscription_number "
                "VALUES (?,?,?,?,?, ?,?,'PENDING_CUSTOMER_CONFIRMATION',?,?,?)",
                number, item["customer_id"], item["product_id"], item["quantity_per_delivery"], item["frequency"],
                item["start_date"], item["end_date"], "CONFIRMED" if require_available else "PENDING",
                price_row[0] if price_row else None, item.get("notes"),
            )
            row = dict(zip((column[0] for column in cursor.description), cursor.fetchone()))
            for weekday in sorted(item.get("selected_days", [])):
                cursor.execute("INSERT INTO dbo.SubscriptionDays(SubscriptionId,DayOfWeek) VALUES (?,?)", row["id"], weekday)
            cursor.execute(
                "INSERT INTO dbo.SubscriptionStatusHistory(SubscriptionId,OldStatus,NewStatus,Actor,Reason) "
                "VALUES (?,NULL,'PENDING_CUSTOMER_CONFIRMATION',?,?)", row["id"], actor,
                "Proposal created; awaiting customer confirmation" if notify_confirmation else "Customer self-service schedule submitted",
            )
            final_status = "PENDING_CUSTOMER_CONFIRMATION"
            if require_available:
                candidate = {
                    "id": row["id"], "customer_id": item["customer_id"], "product_id": item["product_id"],
                    "quantity_per_delivery": item["quantity_per_delivery"], "frequency": item["frequency"],
                    "start_date": item["start_date"], "end_date": item["end_date"],
                    "status": "PENDING_CUSTOMER_CONFIRMATION",
                }
                final_status, shortages = self._attempt_approval(
                    cursor, candidate, item.get("selected_days", []), actor, "Customer schedule submitted"
                )
                if final_status != "APPROVED":
                    sample = ", ".join(
                        f"{entry['date'].isoformat()} (need {entry['required']}, available {entry['available']})"
                        for entry in shortages[:5]
                    )
                    more = " and more dates" if len(shortages) > 5 else ""
                    raise ValueError(f"This product is unavailable for the requested schedule on {sample}{more}")
            cursor.execute(
                "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,AfterSummary) VALUES (?,?,?,?,?)",
                actor, "SUBSCRIPTION_PROPOSED", "Subscription", str(row["id"]),
                f"customer={item['customer_id']}; product={item['product_id']}; quantity={item['quantity_per_delivery']}",
            )
            if notify_confirmation:
                NotificationRepository.enqueue_with_cursor(cursor, "confirmation_request", f"subscription:{row['id']}:confirmation_request", customer[1], {
                    "customer_name": customer[0], "subscription_number": row["subscription_number"],
                    "product_name": product[0], "quantity_per_delivery": item["quantity_per_delivery"],
                    "frequency": item["frequency"], "start_date": item["start_date"], "end_date": item["end_date"],
                })
            connection.commit()
            cursor.close()
        return {**row, "status": final_status,
                "confirmation_status": "CONFIRMED" if require_available else "PENDING",
                "selected_days": item.get("selected_days", []), "unit_price_snapshot": price_row[0] if price_row else None}

    def _transition(self, cursor, subscription_id: int, old_status: str, new_status: str, actor: str, reason: str | None) -> int:
        cursor.execute(
            "UPDATE dbo.Subscriptions SET Status=?, UpdatedAt=SYSUTCDATETIME(), "
            "ApprovedAt=CASE WHEN ?='APPROVED' THEN SYSUTCDATETIME() ELSE ApprovedAt END "
            "WHERE SubscriptionId=?", new_status, new_status, subscription_id,
        )
        cursor.execute(
            "INSERT INTO dbo.SubscriptionStatusHistory(SubscriptionId,OldStatus,NewStatus,Actor,Reason) OUTPUT inserted.HistoryId VALUES (?,?,?,?,?)",
            subscription_id, old_status, new_status, actor, reason,
        )
        history_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) VALUES (?,?,?,?,?,?)",
            actor, "SUBSCRIPTION_STATUS", "Subscription", str(subscription_id), old_status, f"{new_status}; {reason or ''}"[:2000],
        )
        return history_id

    @staticmethod
    def _queue_status_notification(cursor, sub: dict[str, Any], new_status: str, history_id: int) -> None:
        event = {"APPROVED": "approved", "WAITLISTED": "waitlisted", "DECLINED": "declined"}.get(new_status)
        if not event:
            return
        cursor.execute(
            "SELECT c.FullName,c.Email,s.SubscriptionNumber,p.ProductName,s.QuantityPerDelivery,s.Frequency,s.StartDate,s.EndDate "
            "FROM dbo.Subscriptions s JOIN dbo.Customers c ON c.CustomerId=s.CustomerId "
            "JOIN dbo.MilkProducts p ON p.MilkProductId=s.MilkProductId WHERE s.SubscriptionId=?", sub["id"],
        )
        row = cursor.fetchone()
        if row:
            NotificationRepository.enqueue_with_cursor(cursor, event, f"subscription-history:{history_id}", row[1], {
                "customer_name": row[0], "subscription_number": row[2], "product_name": row[3],
                "quantity_per_delivery": row[4], "frequency": row[5], "start_date": row[6], "end_date": row[7],
            })

    def _attempt_approval(self, cursor, sub: dict[str, Any], weekdays: list[int], actor: str, reason: str | None):
        dates = delivery_dates(sub["start_date"], sub["end_date"], sub["frequency"], weekdays)
        availability = self._locked_availability(cursor, sub["product_id"], dates)
        committed = self._approved_commitments(cursor, sub["product_id"], sub["start_date"], sub["end_date"])
        shortages = calculate_shortages(dates, sub["quantity_per_delivery"], availability, committed)
        if shortages:
            old = sub["status"]
            history_id = self._transition(cursor, sub["id"], old, "WAITLISTED", actor,
                              f"Insufficient availability on {len(shortages)} requested delivery date(s)")
            self._queue_status_notification(cursor, sub, "WAITLISTED", history_id)
            return "WAITLISTED", shortages
        history_id = self._transition(cursor, sub["id"], sub["status"], "APPROVED", actor, reason or "All requested dates have sufficient stock")
        self._queue_status_notification(cursor, sub, "APPROVED", history_id)
        return "APPROVED", []

    def confirm_subscription(self, subscription_id: int, decision: str, reason: str | None, actor: str,
                             customer_id: int | None = None) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            owner_filter = " AND CustomerId=?" if customer_id is not None else ""
            parameters = (subscription_id, customer_id) if customer_id is not None else (subscription_id,)
            cursor.execute(
                "SELECT SubscriptionId AS id, CustomerId AS customer_id, MilkProductId AS product_id, "
                "QuantityPerDelivery AS quantity_per_delivery, Frequency AS frequency, StartDate AS start_date, "
                "EndDate AS end_date, Status AS status, ConfirmationStatus AS confirmation_status "
                "FROM dbo.Subscriptions WITH (UPDLOCK,HOLDLOCK) WHERE SubscriptionId=?" + owner_filter,
                parameters,
            )
            rows = self._rows(cursor)
            if not rows:
                raise LookupError("Subscription not found")
            sub = rows[0]
            if sub["status"] != "PENDING_CUSTOMER_CONFIRMATION" or sub["confirmation_status"] != "PENDING":
                raise ValueError("This proposal is no longer awaiting customer confirmation")
            cursor.execute("SELECT DayOfWeek FROM dbo.SubscriptionDays WHERE SubscriptionId=?", subscription_id)
            weekdays = [row[0] for row in cursor.fetchall()]
            if decision == "DECLINED":
                cursor.execute(
                    "UPDATE dbo.Subscriptions SET ConfirmationStatus='DECLINED',ConfirmedAt=SYSUTCDATETIME(),UpdatedAt=SYSUTCDATETIME() WHERE SubscriptionId=?",
                    subscription_id,
                )
                history_id = self._transition(cursor, subscription_id, sub["status"], "DECLINED", actor, reason or "Customer declined")
                self._queue_status_notification(cursor, sub, "DECLINED", history_id)
                result_status, shortages = "DECLINED", []
            else:
                cursor.execute(
                    "UPDATE dbo.Subscriptions SET ConfirmationStatus='CONFIRMED',ConfirmedAt=SYSUTCDATETIME(),UpdatedAt=SYSUTCDATETIME() WHERE SubscriptionId=?",
                    subscription_id,
                )
                result_status, shortages = self._attempt_approval(cursor, sub, weekdays, actor, reason)
            connection.commit()
            cursor.close()
        return {"subscription_id": subscription_id, "confirmation_status": decision, "status": result_status,
                "shortages": shortages}

    def approve_subscription(self, subscription_id: int, reason: str | None, actor: str) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT s.SubscriptionId AS id, s.CustomerId AS customer_id, s.MilkProductId AS product_id, "
                "s.QuantityPerDelivery AS quantity_per_delivery, s.Frequency AS frequency, s.StartDate AS start_date, "
                "s.EndDate AS end_date, s.Status AS status, s.ConfirmationStatus AS confirmation_status "
                "FROM dbo.Subscriptions s WITH (UPDLOCK,HOLDLOCK) WHERE s.SubscriptionId=?", subscription_id,
            )
            rows = self._rows(cursor)
            if not rows:
                raise LookupError("Subscription not found")
            sub = rows[0]
            if sub["confirmation_status"] != "CONFIRMED":
                raise ValueError("Customer confirmation is required before approval")
            if sub["status"] not in {"WAITLISTED", "REQUIRES_REVIEW"}:
                raise ValueError("Only a confirmed waitlisted or review-required proposal can be retried")
            cursor.execute("SELECT DayOfWeek FROM dbo.SubscriptionDays WHERE SubscriptionId=?", subscription_id)
            weekdays = [row[0] for row in cursor.fetchall()]
            result_status, shortages = self._attempt_approval(cursor, sub, weekdays, actor, reason)
            connection.commit()
            cursor.close()
        return {"subscription_id": subscription_id, "confirmation_status": "CONFIRMED", "status": result_status,
                "shortages": shortages}

    def cancel_subscription(self, subscription_id: int, reason: str, actor: str,
                            from_date: date | None = None) -> dict[str, Any]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute(
                "SELECT SubscriptionId AS id, Status AS status FROM dbo.Subscriptions WITH (UPDLOCK,HOLDLOCK) "
                "WHERE SubscriptionId=?", subscription_id,
            )
            rows = self._rows(cursor)
            if not rows:
                raise LookupError("Subscription not found")
            old_status = rows[0]["status"]
            if old_status in {"DECLINED", "CANCELLED"}:
                raise ValueError(f"A {old_status.lower()} subscription cannot be cancelled again")
            effective_from = from_date or datetime.now(ZoneInfo(get_settings().app_timezone)).date()
            cursor.execute(
                "UPDATE dbo.Deliveries SET Status='CANCELLED',UpdatedAt=SYSUTCDATETIME() "
                "OUTPUT deleted.DeliveryId,deleted.Status,inserted.Status,inserted.DeliveryDate "
                "WHERE SubscriptionId=? AND DeliveryDate>=? AND Status='PLANNED'",
                subscription_id, effective_from,
            )
            cancelled_deliveries = cursor.fetchall()
            for delivery_id, before_status, after_status, delivery_date in cancelled_deliveries:
                cursor.execute(
                    "INSERT INTO dbo.AuditLogs(Actor,Action,EntityType,EntityId,BeforeSummary,AfterSummary) "
                    "VALUES (?,?,?,?,?,?)", actor, "DELIVERY_CANCELLED_WITH_SUBSCRIPTION", "Delivery", str(delivery_id),
                    f"status={before_status}", f"status={after_status}; subscription={subscription_id}; reason={reason.strip()}"[:2000],
                )
            history_id = self._transition(cursor, subscription_id, old_status, "CANCELLED", actor, reason.strip())
            cursor.execute("SELECT c.FullName,c.Email,s.SubscriptionNumber,p.ProductName FROM dbo.Subscriptions s JOIN dbo.Customers c ON c.CustomerId=s.CustomerId JOIN dbo.MilkProducts p ON p.MilkProductId=s.MilkProductId WHERE s.SubscriptionId=?", subscription_id)
            contact = cursor.fetchone()
            if contact:
                NotificationRepository.enqueue_with_cursor(cursor, "cancelled", f"subscription-history:{history_id}", contact[1], {
                    "customer_name": contact[0], "subscription_number": contact[2], "product_name": contact[3], "reason": reason.strip(),
                })
            connection.commit()
            cursor.close()
        return {"subscription_id": subscription_id, "status": "CANCELLED",
                "cancelled_planned_deliveries": len(cancelled_deliveries), "effective_from": effective_from,
                "reason": reason.strip()}

    def get_status_history(self, subscription_id: int) -> list[dict[str, Any]]:
        with sql_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT OldStatus AS old_status, NewStatus AS new_status, OccurredAt AS occurred_at, Actor AS actor, Reason AS reason "
                "FROM dbo.SubscriptionStatusHistory WHERE SubscriptionId=? ORDER BY OccurredAt,HistoryId", subscription_id,
            )
            rows = self._rows(cursor)
            cursor.close()
            return rows
